#!/usr/bin/env python3
"""
Operator GUI for camera 1 — live video and detections on a phone.

    /home/jetson/oak-venv/bin/python drone/wildlife/gui_server.py
    ./drone/wildlife/oak_camera.sh gui          # same, with device arbitration

Then open http://jetson.local:8080/?k=<token> on a phone. The token is printed
at startup, derived from whatever key radio/auth.py resolves -- which is this
service's OWN key, not the C2 one. venator-gui.service sets
VENATOR_KEY_FILE=~/.venator/gui-key and venator-c2.service points at a separate
path. Two secrets on the aircraft, deliberately: serial_link.py verifies against
the C2 key and drops anything unsigned, and the handheld remote does not sign --
so one shared key meant that creating a key for the camera silently muted
RUN 1/2/7 from the remote, on every boot.

WHY THE CAMERA DOES THE ENCODING
--------------------------------
The Jetson Orin Nano has no hardware video encoder - no NVENC, and
nvv4l2h264enc does not exist; only nvv4l2decoder is present. H.264 here means
software x264enc burning CPU, which does not fit a 7 W budget.

So the OAK encodes MJPEG on its own fixed-function codec block and this process
relays the bytes without ever decoding them. Detection boxes are drawn
client-side on a <canvas>, not burned into the frame, which avoids a decode and
re-encode per frame. The Jetson's video path is a memcpy.

Measured on this rig, 3 cameras + stereo + the detector + both encoders:

    NN                       10.01 fps   (unchanged - encoders cost it nothing)
    MJPEG 1280x720 q80       10.01 fps   28.6 KB/frame   2.24 Mbps
    MJPEG  640x360 q75        8.00 fps    7.9 KB/frame   0.50 Mbps
    board draw               6.65 W mean

MJPEG also beats H.264 on a drone link for a reason that has nothing to do with
the encoder: every frame is an I-frame, so a frame lost to a weak signal costs
one frame rather than the rest of a GOP.

RANGE, HONESTLY
---------------
5 GHz at 13 dBm from antennas inside an airframe gives usable video to roughly
60-120 m line of sight, and the moment the aircraft is behind a tree line it is
gone. Wi-Fi is the cockpit - preflight, ground testing, hover-and-inspect. LoRa
is the nervous system for anything beyond that. The status and alert panel is
therefore built to stay useful with no video at all, because past 100 m that is
the normal case.
"""

import argparse
import collections
import glob
import hmac
import ipaddress
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import classes
import gui_page
import portal_page
import ports
import tracking
from radio import auth

MODEL = "luxonis/wildlife-megadetector:mdv6-yolov10-c"
DEFAULT_SHAVES = 5          # measured fastest; see oak_wildlife.py

#: name -> (size, jpeg quality, fps). Two rungs so the operator can trade
#: picture for link margin without restarting the pipeline - setQuality is
#: build-time only, so the alternative would be a rebuild mid-flight.
QUALITIES = {
    "hi": ((1280, 720), 80, 10.0),
    "lo": ((640, 360), 75, 8.0),
}

#: One thread per connection, held for the life of the stream. A phone that
#: locks and unlocks leaks one each time, and this box has zero swap, so this
#: is a resource limit rather than a nicety.
#:
#: 8 suits one or two operators. A demo audience will blow straight through it
#: and the ninth person gets a 503, so GUI_MAX_VIEWERS raises it. Budget the
#: bandwidth before going far above ~16: a 20 MHz 5 GHz channel carries
#: 70-100 Mbps in practice, and the "hi" rung is 2.24 Mbps per viewer against
#: the "lo" rung's 0.50. Sixteen on "hi" is 36 Mbps and workable; the same
#: sixteen on "lo" is 8 Mbps and comfortable. Point an audience at ?q=lo.
def _env_int(name, default, lo, hi):
    try:
        return max(lo, min(hi, int(os.environ.get(name, default))))
    except ValueError:
        return default


def _env_float(name, default, lo, hi):
    try:
        return max(lo, min(hi, float(os.environ.get(name, default))))
    except ValueError:
        return default


MAX_VIEWERS = _env_int("GUI_MAX_VIEWERS", 8, 1, 64)
#: The failure that actually happens in the field: the operator walks out of
#: range, TCP goes quiet, and a write blocks forever. A timeout turns that into
#: an OSError the handler already catches.
SOCKET_TIMEOUT_S = 10.0
#: iOS Safari suspends EventSource on lock. Comment frames keep it honest.
SSE_PING_S = 15.0
#: Alerts and evidence must not be dropped for a viewer that was briefly slow.
RELIABLE_BACKLOG = 32

EVIDENCE_NAME = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9]{4}\.jpg$")

#: The name a phone reaches the drone by. Served over plain HTTP, which is not
#: a shortcut: captive-portal probes are HTTP by design, no certificate
#: authority will issue for an unregistered domain, and a self-signed cert
#: would replace the automatic popup with a warning the captive sheet has no
#: button to dismiss. See docs/FIELD_MODE.md.
PORTAL_HOST = "venatordrone.com"

#: Paths each operating system fetches to decide whether a network has
#: internet. Answering any of them with something other than the expected
#: success response is what makes the device say "this network has a login
#: page" and open it. Ten of them because the set differs by OS and version,
#: and a probe that goes unanswered produces a bare warning triangle rather
#: than a portal.
PROBE_PATHS = frozenset({
    "/hotspot-detect.html",        # iOS, macOS
    "/library/test/success.html",  # iOS, macOS - older
    "/generate_204",               # Android, Chrome
    "/gen_204",                    # Chrome - alternate
    "/connecttest.txt",            # Windows NCSI
    "/ncsi.txt",                   # Windows NCSI - older
    "/redirect",                   # Windows NCSI redirect probe
    "/success.txt",                # Firefox
    "/canonical.html",             # Ubuntu, GNOME
    "/nm-check.txt",               # NetworkManager connectivity check
})

#: Host header *names* that mean the request was aimed at us deliberately.
#: Any other name arrived because the drone's DNS answered for something it
#: does not own, so it gets redirected to the portal. IP addresses are handled
#: separately by _is_ip() - they are never redirected, because nobody reaches
#: an IP by accident.
LOCAL_HOSTS = frozenset({
    PORTAL_HOST, "localhost", "venator.drone",
    socket.gethostname(), f"{socket.gethostname()}.local",
})


def _is_ip(host):
    """True when the Host header is a bare address rather than a name.

    An address was typed, bookmarked, or copied from the reachable-URL list
    this server prints at startup - it cannot be the product of DNS
    redirection, so it is always served directly.
    """
    try:
        ipaddress.ip_address(host.strip("[]"))   # strip() for IPv6 literals
        return True
    except ValueError:
        return False

#: Seconds between attempts to reopen a camera that is not there. Matches
#: camera_publisher.py's RECONNECT_WAIT_S, which solves the same problem.
RECONNECT_WAIT_S = 5

#: Minimum seconds between saved evidence frames.
#:
#: Without this, every detection frame became a file: a subject in view at
#: 10 fps wrote ten JPEGs a second, about 18 MB a minute, and the filmstrip
#: showed forty copies of the same second rather than forty sightings. It also
#: wasted the point of the archive - forty near-identical frames are one
#: training example, not forty.
#:
#: 2 s is the interim rule. Once a track is genuinely new the floor is bypassed
#: (see save_evidence), so a creature walking into frame is never missed while
#: one standing still cannot flood the disk.
SAVE_MIN_INTERVAL_S = _env_float("GUI_SAVE_INTERVAL", 2.0, 0.0, 600.0)

#: Set by the signal handlers. Module level because the camera is reopened in a
#: loop, so the flag has to outlive any one pipeline.
STOP = {"flag": False}


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


# --- this service's secret --------------------------------------------------

def make_token(key):
    """A GUI token derived from whichever key was loaded, or None if there is none.

    Still a derivation rather than the key itself, so someone who sees a browser
    URL, a bookmark or a photographed QR code learns nothing about the key it
    came from.

    The caller decides WHICH key: venator-gui.service sets VENATOR_KEY_FILE to
    ~/.venator/gui-key, so in production this is the camera's own secret and not
    the one that signs flight commands. It used to be the C2 key, which coupled
    the two: creating a key so the phone could reach the camera also made
    serial_link.py start verifying, and the handheld remote does not sign.
    """
    if not key:
        return None
    return hmac.new(key, b"venator-gui-v1", sha256).hexdigest()[:16]


# --- host telemetry, all readable without root ------------------------------

def soc_temp_c():
    hottest = None
    for p in glob.glob("/sys/devices/virtual/thermal/thermal_zone*/temp"):
        try:
            v = int(Path(p).read_text().strip()) / 1000.0
        except (OSError, ValueError):
            continue
        if hottest is None or v > hottest:
            hottest = v
    return round(hottest, 1) if hottest is not None else None


def board_watts():
    """VDD_IN from the INA3221. Includes the OAK's bus draw, so this reads
    above the nvpmodel budget even when the mode is honoured - the mode caps
    SoC clocks and cores, not total board input."""
    try:
        c = int(Path(glob.glob("/sys/class/hwmon/hwmon*/curr1_input")[0]).read_text())
        v = int(Path(glob.glob("/sys/class/hwmon/hwmon*/in1_input")[0]).read_text())
        return round(c * v / 1e6, 2)
    except (OSError, ValueError, IndexError):
        return None


def power_mode():
    try:
        out = subprocess.run(["nvpmodel", "-q"], capture_output=True, text=True,
                             timeout=4).stdout
        for line in out.splitlines():
            if "Power Mode" in line:
                return line.split(":", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def usb_speed_mbps():
    """The OAK's negotiated link speed. It renegotiates across re-enumeration,
    so this is read live rather than cached - 5000 and 480 have both been seen
    on this rig from the same socket."""
    for d in glob.glob("/sys/bus/usb/devices/*/"):
        try:
            if Path(d, "idVendor").read_text().strip() != "03e7":
                continue
            return int(Path(d, "speed").read_text().strip())
        except (OSError, ValueError):
            continue
    return None


def wifi_link():
    """RSSI and client count, whichever way the radio is pointing."""
    info = {}
    try:
        out = subprocess.run(["iw", "dev"], capture_output=True, text=True,
                             timeout=4).stdout
        iface = next((l.split()[1] for l in out.splitlines()
                      if l.strip().startswith("Interface")), None)
        if not iface:
            return info
        dump = subprocess.run(["iw", "dev", iface, "station", "dump"],
                              capture_output=True, text=True, timeout=4).stdout
        signals = [int(l.split(":")[1].split()[0])
                   for l in dump.splitlines() if "signal:" in l]
        info["clients"] = dump.count("Station ")
        if signals:
            info["rssi"] = max(signals)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    return info


def reachable_urls(port, token):
    """Every address this GUI just became reachable on, named.

    Printed at startup on purpose: on the school SSID, that list is the
    warning. docs/SECURITY.md item 4 was that this bound 0.0.0.0 silently.
    """
    urls = []
    labels = {"10.42.0.1": "Jetson Wi-Fi hotspot", "192.168.55.1": "USB-C cable"}
    try:
        out = subprocess.run(["ip", "-4", "-br", "addr"], capture_output=True,
                             text=True, timeout=4).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 3 or parts[0] == "lo":
                continue
            for cidr in parts[2:]:
                ip = cidr.split("/")[0]
                label = labels.get(ip, parts[0])
                q = f"?k={token}" if token else ""
                urls.append((f"http://{ip}:{port}/{q}", label))
    except (OSError, subprocess.SubprocessError):
        pass
    q = f"?k={token}" if token else ""
    urls.append((f"http://{socket.gethostname()}.local:{port}/{q}", "mDNS, any interface"))
    return urls


# --- the hub ----------------------------------------------------------------

class Viewer:
    """One SSE subscriber's state.

    Two delivery policies on purpose. det/status coalesce - the latest wins and
    older ones are dropped freely, because a stale detection frame is worthless.
    alert/evidence go in a bounded queue and are delivered at least once,
    because a missed frame is nothing and a missed SAR alert is the whole point
    of the system.
    """

    def __init__(self):
        self.latest = {}
        self.queue = collections.deque(maxlen=RELIABLE_BACKLOG)
        self.seq = 0

    def offer(self, name, payload, reliable):
        if reliable:
            self.queue.append((name, payload))
        else:
            self.latest[name] = payload

    def drain(self):
        """Reliable events first, in order, then one of each coalesced kind."""
        out = []
        while self.queue:
            out.append(self.queue.popleft())
        for name in sorted(self.latest):
            out.append((name, self.latest.pop(name)))
        return out

    def pending(self):
        return bool(self.queue or self.latest)


class Hub:
    """Shares camera JPEGs and detection events with web viewers.

    The frames() generator yields *outside* the lock and only ever reads the
    newest JPEG, never a queue. That is lifted verbatim from
    camera_publisher.py:204-218 and it is load-bearing twice over: slow viewers
    drop frames for free, and a blocked phone can never stall the camera loop.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._jpeg = {name: None for name in QUALITIES}
        self._seq = {name: 0 for name in QUALITIES}
        self._bytes = {name: 0 for name in QUALITIES}
        self._viewers = []
        self._streams = 0
        self._status = {}
        self._dets = {}
        self._alerts = collections.deque(maxlen=64)
        self._unacked = set()

    # -- producer side (camera thread) --

    def publish_frame(self, name, jpeg):
        with self._cond:
            self._jpeg[name] = jpeg
            self._seq[name] += 1
            self._bytes[name] = len(jpeg)
            self._cond.notify_all()

    def publish(self, name, payload, reliable=False):
        with self._cond:
            if name == "det":
                self._dets = payload
            elif name == "status":
                self._status = payload
            elif name == "alert":
                self._alerts.appendleft(payload)
                self._unacked.add(payload.get("id"))
            for v in self._viewers:
                v.offer(name, payload, reliable)
            self._cond.notify_all()

    def ack(self, alert_id):
        with self._cond:
            self._unacked.discard(alert_id)
            return len(self._unacked)

    # -- consumer side (one thread per connection) --

    def stream_slots_free(self):
        with self._cond:
            return self._streams < MAX_VIEWERS

    def frames(self, quality):
        """Yield each new JPEG to one viewer, counting it as watching."""
        with self._cond:
            self._streams += 1
            seen = self._seq[quality]
        try:
            while True:
                with self._cond:
                    if not self._cond.wait_for(
                            lambda: self._seq[quality] != seen, timeout=1.0):
                        continue      # camera quiet; keep the connection open
                    seen, jpeg = self._seq[quality], self._jpeg[quality]
                if jpeg is not None:
                    yield jpeg        # outside the lock, always
        finally:
            with self._cond:
                self._streams -= 1

    def events(self):
        """Yield (name, payload) for one SSE subscriber until it disconnects."""
        viewer = Viewer()
        with self._cond:
            self._viewers.append(viewer)
            viewer.offer("status", self._status, False)
            if self._dets:
                viewer.offer("det", self._dets, False)
        try:
            while True:
                with self._cond:
                    if not self._cond.wait_for(viewer.pending, timeout=SSE_PING_S):
                        yield None, None      # heartbeat
                        continue
                    batch = viewer.drain()
                for name, payload in batch:
                    yield name, payload
        finally:
            with self._cond:
                if viewer in self._viewers:
                    self._viewers.remove(viewer)

    def latest_jpeg(self):
        """The newest encoded frame, preferring the high rung.

        Evidence frames come from here rather than from a raw passthrough:
        the bytes are already a JPEG off the camera's codec, so writing one
        costs no decode, no PIL and no USB bandwidth beyond the stream that
        is running anyway.
        """
        with self._cond:
            return self._jpeg.get("hi") or self._jpeg.get("lo")

    def snapshot(self):
        with self._cond:
            s = dict(self._status)
            s["viewers"] = self._streams
            s["sse"] = len(self._viewers)
            s["alerts_unacked"] = len(self._unacked)
            s["jpeg_bytes"] = dict(self._bytes)
            s["recent_alerts"] = list(self._alerts)[:5]
            return s


# --- HTTP -------------------------------------------------------------------

def make_handler(hub, token, save_dir, cfg):
    wrong = {"count": 0}
    wrong_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        # BaseHTTPRequestHandler speaks HTTP/1.0 by default, under which a
        # response with no Content-Length is merely "read until close". The
        # streaming routes rely on that, so they send Connection: close
        # explicitly and everything else carries a length.
        protocol_version = "HTTP/1.1"
        server_version = "venator-gui/1"

        def _authorised(self, url):
            if token is None:
                return True        # no key file: bound to loopback, see main()
            given = (parse_qs(url.query).get("k", [""])[0]
                     or self.headers.get("X-Venator-Token", "")
                     or self._cookie_token())
            if secrets.compare_digest(given, token):
                with wrong_lock:
                    wrong["count"] = 0
                return True
            # Growing delay on failure, the same shape as
            # radio/phone_relay.py:286-291.
            with wrong_lock:
                wrong["count"] += 1
                delay = min(0.5 * wrong["count"], 5.0)
            time.sleep(delay)
            return False

        def _cookie_token(self):
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == "vt":
                    return v
            return ""

        # --- captive portal helpers --------------------------------------

        def _portal_url(self, path="/portal"):
            """Where a probe gets sent.

            The token rides in the URL because that is the only thing that
            survives the handoff out of a captive sheet - iOS cookies set
            inside it never reach Safari. The consequence is deliberate and
            documented: once the portal hands the token to whoever joins the
            network, the Wi-Fi password is the access control. See
            docs/SECURITY.md.
            """
            q = f"?k={token}" if token else ""
            return f"http://{PORTAL_HOST}{path}{q}"

        def _redirect(self, location, code=302):
            """A redirect that also works for clients that ignore Location.

            Some captive WebViews render the body instead of following the
            header, so the body carries a meta refresh and a plain link too.
            """
            esc = location.replace("&", "&amp;").replace('"', "&quot;")
            body = (
                "<!doctype html><html><head><meta charset=utf-8>"
                f'<meta http-equiv="refresh" content="0;url={esc}">'
                "<title>Venator Drone</title></head><body>"
                f'<p><a href="{esc}">Open the Venator Drone camera</a></p>'
                "</body></html>\n").encode()
            return self._body(code, "text/html; charset=utf-8", body,
                              [("Location", location)])

        def do_GET(self):
            url = urlparse(self.path)
            path = url.path

            if path == "/healthz":
                # Unauthenticated on purpose: deploy/net_fallback.sh polls it to
                # decide whether the aircraft is reachable, and it leaks nothing.
                return self._body(200, "text/plain; charset=utf-8", b"ok\n")

            # --- captive portal, all of it ahead of the auth gate -----------
            #
            # These have to be unauthenticated and there is no way around it: a
            # phone probing for a login page has never seen our token and
            # cannot be given one first. What they expose is a redirect, a
            # JSON blob naming the portal, and a landing page - no camera
            # frames, no evidence, no configuration. The GUI itself stays
            # behind the gate below.
            #
            # They also sit above the gate for a second reason: _authorised()
            # sleeps up to 5 s on a failed attempt (:437-440), and a phone
            # firing five probes would otherwise be throttled into deciding
            # the network is dead.
            if path in PROBE_PATHS:
                return self._redirect(self._portal_url())

            if path == "/captive-portal-api":
                # RFC 8908. iOS 14+ and Android 11+ are handed this URL in DHCP
                # option 114, fetch it, and open user-portal-url themselves -
                # no intercepted request, no certificate warning, and nothing
                # for the operator to type. This is the route that actually
                # delivers the automatic popup; the probe redirects above are
                # the fallback for everything older.
                return self._body(
                    200, "application/captive+json",
                    json.dumps({
                        "captive": True,
                        "user-portal-url": self._portal_url(),
                        "venue-info-url": self._portal_url(),
                        "can-extend-session": False,
                    }, separators=(",", ":")).encode())

            if path == "/portal":
                page = portal_page.render(token, hub.snapshot()).encode()
                extra = []
                if token:
                    # Same mechanism as "/" below. Of limited use inside the
                    # iOS captive sheet, whose cookies never reach Safari, but
                    # it helps every other browser.
                    extra.append(("Set-Cookie",
                                  f"vt={token}; Path=/; HttpOnly; "
                                  f"SameSite=Strict; Max-Age=86400"))
                return self._body(200, "text/html; charset=utf-8", page, extra)

            if path == "/favicon.ico":
                # 204, not a redirect: some captive WebViews follow a 302 here
                # and loop.
                return self._body(204, "image/x-icon", b"",
                                  [("Cache-Control", "public, max-age=86400")])

            # Anything arriving under a hostname we do not own got here because
            # the drone's DNS answered for a name it has no business answering
            # for. Send it to the portal.
            #
            # But a bare IP address is never hijacked - it was typed, or came
            # from the list of reachable URLs this server prints at startup. An
            # earlier version redirected those too, which meant every LAN
            # address the server advertised bounced the browser to
            # venatordrone.com, a name that only resolves on the drone's own
            # hotspot. Serving IPs unconditionally also keeps the USB-C link and
            # any future interface working without maintaining a list.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
            if host and not _is_ip(host) and host not in LOCAL_HOSTS:
                return self._redirect(self._portal_url())

            if not self._authorised(url):
                return self._body(403, "text/plain; charset=utf-8",
                                  b"Wrong or missing key.\n"
                                  b"Use the address the GUI printed at startup.\n")

            if path == "/":
                page = gui_page.render(token, cfg, QUALITIES).encode()
                extra = None
                if token and parse_qs(url.query).get("k"):
                    # Stop the token riding in every subsequent URL, where it
                    # would leak through history and Referer on thumbnails.
                    extra = [("Set-Cookie",
                              f"vt={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400")]
                return self._body(200, "text/html; charset=utf-8", page, extra)
            if path == "/api/status":
                return self._json(hub.snapshot())
            if path == "/api/evidence":
                n = int(parse_qs(url.query).get("n", ["40"])[0] or 40)
                return self._json(self._evidence_list(min(max(n, 1), 200)))
            if path.startswith("/api/evidence/"):
                return self._evidence_file(path[len("/api/evidence/"):])
            if path == "/live.mjpg":
                q = parse_qs(url.query).get("q", ["hi"])[0]
                return self._mjpeg(q if q in QUALITIES else "hi")
            if path == "/snapshot.jpg":
                # One frame, not a stream. The portal page polls this instead
                # of opening an MJPEG connection, because a captive WebView
                # that gets killed mid-stream holds a viewer slot until the
                # socket timeout expires - and a restricted WebView may not
                # render multipart/x-mixed-replace at all.
                jpeg = hub.latest_jpeg()
                if jpeg is None:
                    return self._body(503, "text/plain; charset=utf-8",
                                      b"no frame yet\n")
                return self._body(200, "image/jpeg", jpeg,
                                  [("Cache-Control", "no-store")])
            if path == "/events":
                return self._sse()
            return self._body(404, "text/plain; charset=utf-8", b"not found\n")

        def do_POST(self):
            url = urlparse(self.path)
            if not self._authorised(url):
                return self._body(403, "text/plain; charset=utf-8", b"forbidden\n")
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 8192)
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, OSError):
                return self._body(400, "text/plain; charset=utf-8", b"bad json\n")
            if not isinstance(payload, dict):
                return self._body(400, "text/plain; charset=utf-8", b"bad json\n")

            if url.path == "/api/ack":
                return self._json({"unacked": hub.ack(payload.get("alert_id"))})
            if url.path == "/api/config":
                return self._json(self._apply_config(payload))
            if url.path == "/api/verdict":
                return self._json(self._write_verdict(payload))
            return self._body(404, "text/plain; charset=utf-8", b"not found\n")

        # -- config the operator can change without a restart --

        def _apply_config(self, payload):
            if "conf" in payload:
                try:
                    want = max(0.0, min(1.0, float(payload["conf"])))
                except (TypeError, ValueError):
                    want = None
                if want is not None:
                    # Clamp up to the device floor rather than accepting a
                    # value that cannot work. Asking for 0.10 when the network
                    # itself is thresholded at 0.35 would otherwise report
                    # success and change nothing.
                    floor = cfg.get("device_floor")
                    cfg["conf"] = max(want, floor) if floor else want
                    cfg["conf_requested"] = want
            if "classes" in payload and isinstance(payload["classes"], list):
                cfg["classes"] = [str(c) for c in payload["classes"]][:16]
            if "quality" in payload and payload["quality"] in QUALITIES:
                cfg["quality"] = payload["quality"]
            if "save" in payload:
                cfg["save"] = bool(payload["save"])
            return {k: cfg[k] for k in
                    ("conf", "conf_requested", "device_floor", "classes",
                     "quality", "save") if k in cfg}

        # -- evidence --

        def _evidence_list(self, n):
            out = []
            try:
                names = sorted(os.listdir(save_dir), reverse=True)
            except OSError:
                return out
            for name in names:
                if not EVIDENCE_NAME.match(name):
                    continue
                p = Path(save_dir, name)
                try:
                    st = p.stat()
                except OSError:
                    continue
                item = {"name": name, "t": int(st.st_mtime), "bytes": st.st_size}
                side = p.with_suffix(".json")
                try:
                    item.update(json.loads(side.read_text()))
                except (OSError, ValueError):
                    pass
                out.append(item)
                if len(out) >= n:
                    break
            return out

        def _evidence_file(self, name):
            # Basename only, and an allowlisted shape. Rejecting ".." is not
            # enough on its own; this refuses anything that is not a frame name
            # this process would have written.
            name = os.path.basename(name)
            if name.endswith(".json"):
                if not EVIDENCE_NAME.match(name[:-5] + ".jpg"):
                    return self._body(400, "text/plain; charset=utf-8", b"bad name\n")
                ctype = "application/json"
            elif EVIDENCE_NAME.match(name):
                ctype = "image/jpeg"
            else:
                return self._body(400, "text/plain; charset=utf-8", b"bad name\n")
            try:
                data = Path(save_dir, name).read_bytes()
            except OSError:
                return self._body(404, "text/plain; charset=utf-8", b"not found\n")
            return self._body(200, ctype, data,
                              [("Cache-Control", "private, max-age=3600")])

        def _write_verdict(self, payload):
            """One tap of right/wrong in the filmstrip, into the sidecar.

            This is the active-learning loop: every evidence frame is in-domain
            training data for the species classifier that does not exist yet,
            and the operator's verdict is its label.
            """
            name = os.path.basename(str(payload.get("name", "")))
            if not EVIDENCE_NAME.match(name):
                return {"ok": False, "error": "bad name"}
            side = Path(save_dir, name).with_suffix(".json")
            try:
                data = json.loads(side.read_text())
            except (OSError, ValueError):
                data = {}
            data["verdict"] = {
                "ok": bool(payload.get("ok")),
                "cls": str(payload.get("cls", ""))[:32] or None,
                "t": int(time.time()),
            }
            try:
                side.write_text(json.dumps(data, indent=1))
            except OSError as e:
                return {"ok": False, "error": str(e)}
            return {"ok": True, "name": name}

        # -- streaming --

        def _mjpeg(self, quality):
            if not hub.stream_slots_free():
                return self._body(503, "text/plain; charset=utf-8",
                                  b"too many viewers\n")
            self.connection.settimeout(SOCKET_TIMEOUT_S)
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            frames = hub.frames(quality)
            try:
                for jpeg in frames:
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            except (OSError, ValueError):
                pass        # viewer closed, or walked out of range
            finally:
                frames.close()

        def _sse(self):
            self.connection.settimeout(SOCKET_TIMEOUT_S)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            events = hub.events()
            seq = 0
            try:
                self.wfile.write(b": hello\n\n")
                for name, payload in events:
                    if name is None:
                        self.wfile.write(b": ping\n\n")   # keeps iOS honest
                        continue
                    seq += 1
                    self.wfile.write(
                        f"id: {seq}\nevent: {name}\ndata: ".encode()
                        + json.dumps(payload, separators=(",", ":")).encode()
                        + b"\n\n")
            except (OSError, ValueError):
                pass
            finally:
                events.close()

        # -- plumbing --

        def _json(self, obj):
            self._body(200, "application/json",
                       json.dumps(obj, separators=(",", ":")).encode())

        def _body(self, code, ctype, data, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            if code >= 400 or "html" in ctype or "json" in ctype:
                self.send_header("Cache-Control", "no-store")
            for k, v in (extra or []):
                self.send_header(k, v)
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass

        def log_message(self, *args):
            pass        # the detector's own output is the interesting log

    return Handler


def start_server(hub, token, host, port, save_dir, cfg):
    handler = make_handler(hub, token, save_dir, cfg)
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        log(f"GUI disabled: cannot bind {host}:{port} ({exc})")
        return None
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="gui-http",
                     daemon=True).start()
    return server


# --- camera -----------------------------------------------------------------

def run(args, hub, cfg):
    import depthai as dai

    os.environ.setdefault("DEPTHAI_ZOO_CACHE_PATH", "/home/jetson/oak-venv/zoo-cache")

    desc = dai.NNModelDescription(args.model)
    desc.platform = "RVC2"
    archive = dai.NNArchive(dai.getModelFromZoo(desc))
    nn_w, nn_h = archive.getInputSize()

    with dai.Pipeline() as pipeline:
        colour = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        left = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_B)
        right = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_C)

        stereo = pipeline.create(dai.node.StereoDepth)
        stereo.setDefaultProfilePreset(
            getattr(dai.node.StereoDepth.PresetMode, args.preset))
        stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
        left.requestOutput((640, 400)).link(stereo.left)
        right.requestOutput((640, 400)).link(stereo.right)

        # CROP for the network, and CROP again for every video rung below.
        # Both are 16:9 views of a 4:3 sensor, and because the crop is
        # identical the network's normalised boxes land on the video frame with
        # no transform at all. That is why the client can draw them directly.
        # Stated explicitly rather than inherited: CROP happens to be the
        # library default for both calls, and a silent default drift here would
        # misplace every box on screen.
        nn = pipeline.create(dai.node.SpatialDetectionNetwork).build(
            colour, stereo, archive, fps=args.fps,
            resizeMode=dai.ImgResizeMode.CROP)
        if args.shaves:
            nn.setBlob(archive.getSuperBlob().getBlobWithNumShaves(args.shaves))
        labels = list(nn.getClasses() or [])
        # Published into cfg so the HTTP handler can clamp a live --conf
        # against it; the HTTP server starts before this, so it has to cope
        # with the key being absent for the first few seconds.
        device_floor = classes.device_floor(labels, args.conf)
        cfg["device_floor"] = device_floor
        nn.setConfidenceThreshold(device_floor)
        nn.setDepthLowerThreshold(int(args.min_dist * 1000))
        nn.setDepthUpperThreshold(int(args.max_dist * 1000))
        nn.setBoundingBoxScaleFactor(0.5)

        # MJPEG on the Myriad X's fixed-function codec. Measured: costs the
        # network nothing, and both rungs together are 2.74 Mbps.
        queues = {}
        for name, (size, quality, fps) in QUALITIES.items():
            out = colour.requestOutput(size, dai.ImgFrame.Type.NV12,
                                       resizeMode=dai.ImgResizeMode.CROP, fps=fps)
            enc = pipeline.create(dai.node.VideoEncoder).build(
                out, frameRate=fps,
                profile=dai.VideoEncoderProperties.Profile.MJPEG, quality=quality)
            queues[name] = enc.out.createOutputQueue(maxSize=2, blocking=False)

        # Tracking, which the detector had none of. ZERO_TERM_IMAGELESS uses no
        # image features, so it costs no SHAVE cores and no CMX - it is pure box
        # arithmetic on the device.
        tracker = pipeline.create(dai.node.ObjectTracker)
        tracker.setTrackerType(dai.TrackerType.ZERO_TERM_IMAGELESS)
        # UNIQUE_ID, not SMALLEST_ID: ids must never be recycled, or a count of
        # distinct animals over a sortie is meaningless and a SAR alert could
        # name a track that is now a different subject.
        tracker.setTrackerIdAssignmentPolicy(dai.TrackerIdAssignmentPolicy.UNIQUE_ID)
        # The one setting that matters on a moving platform: associate on the
        # stereo Z as well as image overlap. Image-plane IOU alone is unreliable
        # when the camera translates between frames, which it always does here.
        tracker.setSpatialAssociation(True)
        tracker.setTrackletMaxLifespan(int(args.fps))     # ~1 s of prediction
        tracker.setMaxObjectsToTrack(20)
        tracker.setTrackingPerClass(False)
        # Only track what the policy would report, so the tracker's 20 slots are
        # not spent on classes classes.py suppresses anyway.
        keep = [i for i, name in enumerate(labels) if name in classes.CLASS_POLICY]
        if keep:
            tracker.setDetectionLabelsToTrack(keep)

        nn.out.link(tracker.inputDetections)
        nn.passthrough.link(tracker.inputDetectionFrame)
        nn.passthrough.link(tracker.inputTrackerFrame)
        tq = tracker.out.createOutputQueue(maxSize=4, blocking=False)
        book = tracking.TrackBook()

        if cfg["save"]:
            os.makedirs(args.save_dir, exist_ok=True)

        pipeline.start()
        log(f"model {args.model} ({len(labels)} classes), {args.shaves or 'default'} shaves")
        log(f"video {', '.join(f'{k} {v[0][0]}x{v[0][1]} q{v[1]}' for k, v in QUALITIES.items())}")

        seq = 0
        frames = 0
        hits = 0
        hits_saved = 0
        last_save = 0.0
        fps_window = collections.deque(maxlen=40)
        last_status = 0.0
        counts = {}

        while not STOP["flag"] and pipeline.isRunning():
            size = QUALITIES[cfg["quality"]][0]
            for name, q in queues.items():
                enc = q.tryGet()
                if enc is not None:
                    hub.publish_frame(name, bytes(enc.getData()))

            # Read tracklets rather than raw detections: same boxes, plus a
            # stable id, an age and a status. Everything downstream - dwell
            # timers, distinct-object counts, the SAR gate - needs the identity.
            msg = tq.tryGet()
            if msg is not None:
                frames += 1
                seq += 1
                now = time.monotonic()
                fps_window.append(now)
                dets, raw_tracklets = [], []
                for t in msg.tracklets:
                    src = t.srcImgDetection
                    raw = labels[t.label] if t.label < len(labels) else str(t.label)
                    conf = float(getattr(src, "confidence", 0.0) or 0.0)
                    if cfg["conf"] is not None:
                        # A live override from /api/config. It can only tighten:
                        # the device filter was programmed at build time to the
                        # policy's lowest threshold, so anything below that was
                        # already dropped in hardware and no host-side setting
                        # can bring it back. status reports the effective floor
                        # so the operator can see where the real limit is.
                        entry = classes.CLASS_POLICY.get(raw)
                        if entry is None or conf < cfg["conf"]:
                            continue
                        verdict = (entry[0], raw)
                    else:
                        verdict = classes.classify(raw, conf)
                    if verdict is None:
                        continue
                    reported, raw = verdict
                    if cfg["classes"] and reported not in cfg["classes"]:
                        continue

                    status = t.status.name
                    c = t.spatialCoordinates
                    z_m = c.z / 1000.0
                    xyz = [round(c.x / 1000.0, 2), round(c.y / 1000.0, 2), round(z_m, 2)]
                    raw_tracklets.append({"id": t.id, "cls": reported, "conf": conf,
                                          "status": status,
                                          "xyz": xyz if z_m > 0 else None})
                    # roi is normalised to the tracker frame, which is the
                    # network passthrough - the same 16:9 crop the video rungs
                    # use, so these land on the displayed frame untransformed.
                    #
                    # Checked rather than assumed: dai.Rect can hold either
                    # normalised or pixel coordinates, and a denormalised roi
                    # would put every box off-screen with no other symptom.
                    r = t.roi
                    if not r.isNormalized():
                        r = r.normalize(nn_w, nn_h)
                    dets.append({
                        "id": t.id,
                        "c": reported,
                        "raw": raw if raw != reported else None,
                        "p": round(conf, 3),
                        "st": status,
                        "b": [round(r.x, 4), round(r.y, 4),
                              round(r.x + r.width, 4), round(r.y + r.height, 4)],
                        "xyz": xyz,
                        # Metric long-axis extent from stereo Z. The SAR
                        # prone-detection gate needs this, and it is also what
                        # separates a person from a wild turkey, which both
                        # models score as "person" at about 71%.
                        "len_m": round(max(r.width, r.height) * 1.374 * z_m, 2)
                                 if z_m > 0 else None,
                    })

                touched = book.update(raw_tracklets, now=now)
                dwell = {t.id: round(t.dwell, 1) for t in touched}
                for d in dets:
                    d["dwell"] = dwell.get(d["id"], 0.0)
                # Distinct objects seen this sortie, not detections counted.
                counts = book.counts()
                if dets:
                    hits += 1
                hub.publish("det", {"seq": seq, "t": round(time.time(), 2),
                                    "w": size[0], "h": size[1], "d": dets,
                                    "tracks": len(book)})

                if dets and cfg["save"]:
                    # A genuinely new object always earns a frame; otherwise the
                    # interval floor applies. So a creature walking in is never
                    # missed, and one standing still cannot flood the disk.
                    fresh = book.new_tracks(touched)
                    due = (now - last_save) >= SAVE_MIN_INTERVAL_S
                    if fresh or due:
                        hits_saved += 1
                        if save_evidence(hub, args.save_dir, hits_saved, dets):
                            last_save = now
                            book.mark_reported(fresh)

            now = time.monotonic()
            if now - last_status >= 1.0:
                last_status = now
                fps = 0.0
                if len(fps_window) > 2:
                    fps = (len(fps_window) - 1) / (fps_window[-1] - fps_window[0])
                hub.publish("status", {
                    "t": round(time.time(), 2),
                    "fps": round(fps, 1),
                    "frames": frames,
                    "hits": hits,
                    # Distinct objects seen this sortie, from tracker ids - not
                    # a count of detection events, which double-counted anything
                    # that flickered.
                    "counts": counts,
                    "tracks": len(book),
                    "active": len(book.active()),
                    "saved": hits_saved,
                    "temp": soc_temp_c(),
                    "watts": board_watts(),
                    "pm": cfg["pm"],
                    "usb": usb_speed_mbps(),
                    "link": wifi_link(),
                    "model": args.model.split("/")[-1],
                    "quality": cfg["quality"],
                    "classes": classes.coarse_classes(labels),
                    "filter": cfg["classes"],
                    "save": cfg["save"],
                    # What the thresholds actually are right now, not what was
                    # asked for: device_floor is baked in at pipeline build, so
                    # a live --conf below it cannot take effect.
                    "conf": cfg["conf"],
                    "device_floor": round(device_floor, 2),
                    # No GPS is fitted, and the GUI must not imply otherwise.
                    "gps": {"fix": "not fitted"},
                    "fc": "not connected",
                })
            if msg is None:
                time.sleep(0.004)

        log(f"{frames} frames, {hits} with a detection")
    return 0


def save_evidence(hub, save_dir, hits, dets):
    """Write the encoder's JPEG straight to disk, plus a sidecar.

    No decode, no PIL, no re-encode: the bytes are already a JPEG. The old
    path pulled a raw BGR888p passthrough frame for this, which cost about
    35 Mbps of USB bandwidth purely so boxes could be burned in. Boxes now
    live in the browser, so the frame goes to disk untouched.

    Returns True when a frame was written, so the caller can hold off the
    interval timer on a failure rather than silently skipping ahead.
    """
    jpeg = hub.latest_jpeg()
    if not jpeg:
        return False
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{hits:04d}.jpg"
    try:
        Path(save_dir, name).write_bytes(jpeg)
        Path(save_dir, name).with_suffix(".json").write_text(json.dumps({
            "t": int(time.time()),
            "classes": sorted({d["c"] for d in dets}),
            "detections": dets,
        }, indent=1))
    except OSError as e:
        log(f"could not save evidence: {e}")
        return False
    hub.publish("evidence", {"name": name, "t": int(time.time()),
                             "classes": sorted({d["c"] for d in dets}),
                             "bytes": len(jpeg)}, reliable=True)
    return True


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--conf", type=float, default=None,
                    help="override every per-class threshold in classes.py")
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--shaves", type=int, default=DEFAULT_SHAVES)
    ap.add_argument("--preset", default="FAST_ACCURACY",
                    choices=("FAST_ACCURACY", "FAST_DENSITY", "DEFAULT", "ROBOTICS"))
    ap.add_argument("--min-dist", type=float, default=0.3)
    ap.add_argument("--max-dist", type=float, default=35.0)
    ap.add_argument("--port", type=int, default=ports.GUI_HTTP)
    ap.add_argument("--host", default=None,
                    help="bind address; defaults to 0.0.0.0 with a key, "
                         "127.0.0.1 without one")
    ap.add_argument("--save-dir", default="/home/jetson/Pictures/wildlife")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--quality", default="hi", choices=tuple(QUALITIES))
    args = ap.parse_args()

    token = make_token(auth.load_key())
    # Fail safe, not open. The old stream bound 0.0.0.0 with no check of any
    # kind (docs/SECURITY.md item 4); with no key there is nothing to check
    # with, so it stays on loopback and says so.
    host = args.host or ("0.0.0.0" if token else "127.0.0.1")

    cfg = {"conf": args.conf, "classes": [], "quality": args.quality,
           "save": not args.no_save, "pm": power_mode()}

    hub = Hub()
    server = start_server(hub, token, host, args.port, args.save_dir, cfg)
    if server is None:
        return 1

    if token:
        log(f"GUI token {token}")
        for url, label in reachable_urls(args.port, token):
            log(f"  reachable: {url}   ({label})")
    else:
        log("NO KEY FILE - the GUI is bound to 127.0.0.1 only.")
        # Name the GUI's own path explicitly. A bare `auth.py --init` writes to
        # auth.py's DEFAULT path, which is the C2 key -- and a key there makes
        # serial_link.py drop the handheld remote's unsigned commands. That is
        # the trap this whole split exists to close, so the fix printed here
        # must not walk back into it.
        log("Create one so a phone can reach it:")
        log("  VENATOR_KEY_FILE=~/.venator/gui-key python3 radio/auth.py --init")
        log("  (or just: bash deploy/field_mode.sh _require_key)")

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: STOP.__setitem__("flag", True))

    # Keep serving even with no camera. The OAK renegotiates its USB link and
    # has been seen to drop off the bus entirely, and a dropout used to take
    # the whole page down with it - including the evidence already on disk,
    # which is the part that needs no camera at all. Now the page stays up,
    # reports the camera as offline, and reopens it when it returns.
    attempts = 0
    while not STOP["flag"]:
        try:
            run(args, hub, cfg)
            break                      # clean exit: Ctrl+C or pipeline stopped
        except KeyboardInterrupt:
            break
        except Exception as exc:       # noqa: BLE001 - any device fault
            attempts += 1
            hub.publish("status", {
                "t": round(time.time(), 2),
                "camera": "offline",
                "error": str(exc)[:200],
                "attempts": attempts,
                "fps": 0.0,
                "pm": cfg["pm"],
                "usb": usb_speed_mbps(),
                "link": wifi_link(),
                "gps": {"fix": "not fitted"},
                "fc": "not connected",
            })
            if attempts == 1 or attempts % 12 == 0:
                log(f"camera unavailable ({exc}); evidence review still works. "
                    f"Retrying every {RECONNECT_WAIT_S}s")
            for _ in range(RECONNECT_WAIT_S * 10):
                if STOP["flag"]:
                    break
                time.sleep(0.1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
