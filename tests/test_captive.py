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
    def __init__(self, jpeg=b"\xff\xd8fake\xff\xd9"):
        self._jpeg = jpeg

    def snapshot(self):
        return {"fps": 10.0, "frames": 1, "camera": "ok"}

    def latest_jpeg(self):
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
check("offers a way out to the real browser", b"Open the live camera" in r.body)
check("names the typed-URL fallback", b"venatordrone.com" in r.body)

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
for host in ("10.42.0.1", "venatordrone.com", "localhost", "127.0.0.1",
             "venator.drone"):
    r = request("/api/status", host=host)
    check(f"Host: {host} reaches the auth gate (403 without a token)",
          r.code, 403)

print("\nA bare IP is NEVER redirected, whatever subnet it is on")
# Regression: an earlier version redirected any Host not in a fixed list, so
# every LAN address this server prints at startup bounced the browser to
# venatordrone.com - a name that only resolves on the drone's own hotspot. An
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
             "/snapshot.jpg"):
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

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
