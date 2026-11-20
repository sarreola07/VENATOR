#!/usr/bin/env python3
"""The captive portal: what an unauthenticated phone can and cannot reach.

Every portal route sits ahead of the token check, because a phone probing for
a login page has never seen the token and cannot be given one first. That makes
the exact boundary load-bearing, and these are the properties that hold it:

  * each operating system's probe path redirects, so the device opens a portal
    rather than showing a bare "no internet" warning;
  * the portal exposes a redirect, a JSON blob naming itself, and a landing
    page - and nothing else. No camera frames, no evidence, no configuration;
  * everything that is not a portal route stays behind the gate, including the
    GUI itself and /snapshot.jpg;
  * the redirect target carries the token, which is what makes the Wi-Fi
    password the real access control. That is deliberate (see docs/SECURITY.md)
    and this test records it rather than letting it drift silently.

Stdlib only, no camera, no sockets: the handler is driven in-process with a
fake request.
"""
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drone" / "wildlife"))

import gui_server      # noqa: E402
import portal_page     # noqa: E402

PASS = FAIL = 0
TOKEN = "0123456789abcdef"


def check(label, got, want=True):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"    {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"   got {got!r}"))


# --- a handler driven without a socket --------------------------------------

class FakeHub:
    """Just enough of Hub for the routes under test."""
    asked = []          # the rung each latest_jpeg() call named, newest last

    def __init__(self, jpeg=b"\xff\xd8fake\xff\xd9"):
        self._jpeg = jpeg

    def snapshot(self):
        return {"fps": 10.0, "frames": 1, "camera": "ok"}

    def latest_jpeg(self, quality=None):
        FakeHub.asked.append(quality)
        return self._jpeg


class Response:
    def __init__(self):
        self.code = None
        self.headers = {}
        self.body = b""

    @property
    def location(self):
        return self.headers.get("Location")


def request(path, host="10.42.0.1", token=TOKEN, jpeg=b"\xff\xd8fake\xff\xd9",
            query=""):
    """Drive do_GET for one path and capture what it sent."""
    hub = FakeHub(jpeg)
    cfg = {"conf": None, "classes": [], "quality": "hi", "save": True, "pm": "7W"}
    Handler = gui_server.make_handler(hub, token, "/tmp", cfg)
    resp = Response()

    class H(Handler):
        def __init__(self):            # bypass BaseHTTPRequestHandler's socket setup
            self.path = path + (("?" + query) if query else "")
            self.headers = {"Host": host} if host else {}
            self.wfile = io.BytesIO()
            self.rfile = io.BytesIO()
            self.connection = type("C", (), {"settimeout": lambda *a: None})()

        def send_response(self, code, *a):
            resp.code = code

        def send_header(self, k, v):
            resp.headers[k] = v

        def end_headers(self):
            pass

        def log_message(self, *a):
            pass

    h = H()
    h.do_GET()
    resp.body = h.wfile.getvalue()
    return resp


print("\nEvery OS probe path opens the portal")
check("the table has ten paths", len(gui_server.PROBE_PATHS), 10)
for p in sorted(gui_server.PROBE_PATHS):
    r = request(p)
    ok = r.code == 302 and r.location and r.location.startswith(
        f"http://{gui_server.PORTAL_HOST}/portal")
    check(f"{p} -> 302 to the portal", ok)

print("\nThe redirect works for clients that ignore the Location header")
r = request("/hotspot-detect.html")
check("body carries a meta refresh", b"http-equiv=\"refresh\"" in r.body)
check("body carries a plain link too", b"<a href=" in r.body)
check("the token is in the redirect", TOKEN in (r.location or ""))

print("\nApple's probe must NOT get the success body it looks for")
# iOS treats a 200 containing "Success" as "this network is fine" and never
# opens a portal. This is the single most important negative assertion here.
r = request("/hotspot-detect.html")
check("status is not 200", r.code != 200)
check("body does not contain 'Success'", b"Success" not in r.body)

print("\nRFC 8908 captive portal API")
r = request("/captive-portal-api")
check("200", r.code, 200)
check("content type is application/captive+json",
      r.headers.get("Content-Type"), "application/captive+json")
api = json.loads(r.body)
check("captive is true", api["captive"], True)
check("names a user portal url", api["user-portal-url"].startswith(
    f"http://{gui_server.PORTAL_HOST}/portal"))
check("session cannot be extended", api["can-extend-session"], False)
check("the token rides along", TOKEN in api["user-portal-url"])

print("\nThe portal landing page")
r = request("/portal")
check("200", r.code, 200)
check("is html", "text/html" in r.headers.get("Content-Type", ""))
check("sets the vt cookie", "vt=" in r.headers.get("Set-Cookie", ""))
check("cookie is HttpOnly", "HttpOnly" in r.headers.get("Set-Cookie", ""))
check("polls a still frame, not a stream", b"/snapshot.jpg" in r.body)
check("never opens an MJPEG stream", b"live.mjpg" not in r.body)
check("never opens an EventSource", b"EventSource" not in r.body)
check("offers a way out to the real browser", b"Open the full camera page" in r.body)
check("asks for the low rung", b"/snapshot.jpg?q=lo" in r.body)
# On Android with mobile data on, this window is the only place the camera can
# be seen: Chrome goes out over cellular. A 2 s slideshow is not a camera feed.
check("is live, not a 2 s slideshow", b"setInterval(refresh, 2000)" not in r.body)
m = re.search(rb"const FRAME_MS = (\d+)", r.body)
check("frame spacing is at most the low rung's 8 fps", bool(m) and int(m.group(1)) <= 125)
check("chains frames rather than firing on a timer",
      b"img.onload" in r.body and b"next(" in r.body)
check("has a watchdog for a request that never answers", b"STALL_MS" in r.body)
check("tells Android users to stay in the window", b"mobile data" in r.body)
check("names the typed-URL fallback", b"venator.com" in r.body)
check("wears the brand, like the camera page", b"--paper:#F2F1EE" in r.body and b"#05070a" not in r.body)

print("\nfavicon is 204, not a redirect")
# Some captive WebViews follow a 302 on /favicon.ico and loop forever.
r = request("/favicon.ico")
check("204", r.code, 204)
check("not a redirect", r.location, None)

print("\nA hijacked hostname is sent to the portal")
for host in ("captive.apple.com", "connectivitycheck.gstatic.com",
             "www.msftconnecttest.com", "example.com"):
    r = request("/some/random/path", host=host)
    check(f"Host: {host} -> 302", r.code == 302)

print("\nOur own hostnames are NOT hijacked — they fall through to the gate")
for host in ("10.42.0.1", "venator.com", "localhost", "127.0.0.1",
             "venator.drone"):
    r = request("/api/status", host=host)
    check(f"Host: {host} reaches the auth gate (403 without a token)",
          r.code, 403)

print("\nA bare IP is NEVER redirected, whatever subnet it is on")
# Regression: an earlier version redirected any Host not in a fixed list, so
# every LAN address this server prints at startup bounced the browser to
# venator.com - a name that only resolves on the drone's own hotspot. An
# address cannot arrive by DNS redirection, so it is always served.
for host in ("192.168.4.117", "192.168.4.95", "172.17.0.1", "192.168.55.1",
             "10.0.0.5", "127.0.0.1"):
    r = request("/", host=host, query="k=" + TOKEN)
    check(f"Host: {host} serves the GUI, not a redirect", r.code, 200)
check("_is_ip accepts IPv6 literals", gui_server._is_ip("[::1]"), True)
check("_is_ip rejects a hostname", gui_server._is_ip("captive.apple.com"), False)
check("_is_ip rejects an empty string", gui_server._is_ip(""), False)

print("\nA request with no Host header at all is served, not redirected")
# HTTP/1.0 clients and some probes omit it; redirecting them would be a loop.
r = request("/healthz", host=None)
check("/healthz with no Host -> 200", r.code, 200)

print("\nThe gate still protects everything that matters")
# Portal routes are the ONLY unauthenticated surface besides /healthz.
for path in ("/", "/api/status", "/api/evidence", "/live.mjpg", "/events",
             "/snapshot.jpg", "/api/health", "/api/metrics", "/api/trials/summary"):
    r = request(path, host="10.42.0.1")
    check(f"{path} without a token -> 403", r.code, 403)

print("\n/healthz stays open, because the boot fallback polls it")
r = request("/healthz", token=TOKEN)
check("200", r.code, 200)
check("says ok", r.body.strip(), b"ok")
check("leaks nothing else", len(r.body) < 16)

print("\n/snapshot.jpg with a token")
r = request("/snapshot.jpg", query=f"k={TOKEN}")
check("200", r.code, 200)
check("is a jpeg", r.headers.get("Content-Type"), "image/jpeg")
check("body is the encoder's bytes", r.body, b"\xff\xd8fake\xff\xd9")
r = request("/snapshot.jpg", query=f"k={TOKEN}", jpeg=None)
check("503 when no frame has arrived yet", r.code, 503)
FakeHub.asked.clear()
request("/snapshot.jpg", query=f"k={TOKEN}&q=lo")
check("?q=lo asks the hub for the low rung", FakeHub.asked[-1:], ["lo"])
request("/snapshot.jpg", query=f"k={TOKEN}&q=../../etc")
check("an unknown ?q= falls back to the default", FakeHub.asked[-1:], [None])
request("/snapshot.jpg", query=f"k={TOKEN}")
check("no ?q= keeps the default", FakeHub.asked[-1:], [None])

print("\nHub.latest_jpeg picks the rung it is asked for, and falls back")
hub = gui_server.Hub()
check("nothing yet -> None", hub.latest_jpeg("lo"), None)
hub.publish_frame("lo", b"LO")
check("lo only: asking for lo -> lo", hub.latest_jpeg("lo"), b"LO")
check("lo only: the default falls back to lo", hub.latest_jpeg(), b"LO")
check("lo only: asking for hi falls back to lo", hub.latest_jpeg("hi"), b"LO")
hub.publish_frame("hi", b"HI")
check("both: the default prefers hi (evidence frames)", hub.latest_jpeg(), b"HI")
check("both: asking for lo -> lo", hub.latest_jpeg("lo"), b"LO")
check("both: an unknown rung -> hi", hub.latest_jpeg("nope"), b"HI")

print("\nWith no key file the portal still works, unauthenticated")
# gui_server binds loopback in this state, so this is a local-only situation -
# but the routes must not crash on a None token.
r = request("/hotspot-detect.html", token=None)
check("probe still redirects", r.code, 302)
check("and the url carries no k=", "k=" not in (r.location or ""))
r = request("/portal", token=None)
check("portal page still renders", r.code, 200)
check("and sets no cookie", "Set-Cookie" not in r.headers)

print("\nThe portal page escapes what it interpolates")
html = portal_page.render('</script><script>alert(1)</script>')
check("a hostile token cannot break out of the script",
      "</script><script>alert(1)" not in html)
check("it is JSON-encoded instead", "\\u003c" in html or "\\/script" in html
      or "<\\/script>" in html)

print("\nAndroid's probe resolves to an address Android will actually probe")
# Android's NetworkMonitor skips the HTTP probe - and so never shows "Sign in to
# network" - when the probe hostname resolves to an address Java calls
# site-local or link-local. Python's ipaddress.is_private is NOT that test (it
# also flags 192.0.2.0/24), so mirror Java's ranges exactly.
import ipaddress  # noqa: E402

JAVA_PRIVATE = [ipaddress.ip_network(n) for n in
                ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")]
ANDROID_PROBE_HOSTS = ("connectivitycheck.gstatic.com",
                       "connectivitycheck.android.com", "clients3.google.com")

conf = (ROOT / "deploy" / "dnsmasq" / "venator-portal.conf").read_text()
answers = dict(re.findall(r"^address=/([^/]+)/(\S+)", conf, re.M))
nft = (ROOT / "deploy" / "nft" / "venator-portal.nft").read_text()
chains = dict(re.findall(r"chain (\w+) \{(.*?)\n    \}", nft, re.S))

for host in ANDROID_PROBE_HOSTS:
    ip = answers.get(host)
    check(f"{host} is answered at all", ip is not None)
    if ip is None:
        continue
    addr = ipaddress.ip_address(ip)
    check(f"{host} -> {ip} is not private to Android",
          not any(addr in n for n in JAVA_PRIVATE))
    for chain in ("prerouting", "output"):
        rule = re.search(rf"^\s*[^#\n]*ip daddr {re.escape(ip)} tcp dport 80 "
                         r"dnat to 10\.42\.0\.1:8080", chains.get(chain, ""), re.M)
        check(f"  and the {chain} chain dnats {ip}:80 to the GUI", rule is not None)

check("captive.apple.com is left on 10.42.0.1 (iOS works there)",
      answers.get("captive.apple.com"), "10.42.0.1")
check("venator.com still resolves to the drone itself",
      answers.get("venator.com"), "10.42.0.1")

print("\nfield_mode.sh on: the GUI is up before the access point is")
# A phone that knows VenatorDrone joins and probes within a second of the AP
# appearing. Restarting the GUI after the AP refused those probes for ~40 s.
fm = (ROOT / "deploy" / "field_mode.sh").read_text()
body = fm[fm.index("field_on() {"):]
body = body[:body.index("\n}\n")]
restart = body.find('systemctl restart "${GUI_UNIT}"')
wait = body.find("wait_for_gui")
ap = body.find('wifi_mode.sh" on')
check("restarts the GUI", restart >= 0)
check("waits for it to answer", wait >= 0)
check("before bringing up the AP", 0 <= restart < wait < ap)
check("wait_for_gui polls the unauthenticated /healthz",
      "127.0.0.1:8080/healthz" in fm)
# The dispatcher loads the redirect asynchronously after the AP is up; status
# reported "not loaded" for a working portal when it ran inside that gap.
portal_wait = body.find("wait_for_portal")
status_call = body.rfind("status")
check("waits for the port-80 redirect after the AP, before status",
      0 <= ap < portal_wait < status_call)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
