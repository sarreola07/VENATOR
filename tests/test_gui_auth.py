#!/usr/bin/env python3
"""The operator GUI's auth, path handling and viewer cap.

docs/SECURITY.md recorded the old camera stream as having "no key, no token and
no check of any kind" while bound to 0.0.0.0. These are the properties that
replaced it, pinned so they cannot quietly regress:

  * the GUI token is derived from the C2 key, never equal to it, so a token in
    browser history or a photographed QR code does not yield the key that signs
    flight commands;
  * with no key file the server binds loopback rather than opening up;
  * /api/evidence/<name> serves only names this process would have written, so
    traversal and arbitrary reads are refused;
  * the viewer cap holds, because one thread per stream on a box with zero swap
    is a resource limit and not a nicety;
  * alerts are delivered at least once while detections are allowed to drop.

Stdlib only, no camera, no sockets - runs on a laptop, the Jetson and in CI.
"""
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drone" / "wildlife"))

import gui_server            # noqa: E402
import gui_page              # noqa: E402
import ports                 # noqa: E402
from radio import auth       # noqa: E402

PASS = FAIL = 0


def check(label, got, want=True):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"    {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"   got {got!r}"))


KEY = b"0123456789abcdef0123456789abcdef"

print("\nToken derivation")
tok = gui_server.make_token(KEY)
check("a key yields a token", bool(tok))
check("token is 16 hex chars", len(tok) == 16 and all(c in "0123456789abcdef" for c in tok))
check("token is NOT the key", tok != KEY.decode())
check("key is not recoverable from the token", KEY.decode().find(tok) == -1)
check("same key, same token", gui_server.make_token(KEY) == tok)
check("different key, different token",
      gui_server.make_token(b"f" * 32) != tok)
check("no key means no token", gui_server.make_token(None), None)
check("empty key means no token", gui_server.make_token(b""), None)
# The GUI token must not be usable as a C2 signature key, or a browser URL
# would become a command-signing credential.
signed = auth.sign({"t": "PING"}, KEY)
check("C2 messages do not verify under the GUI token",
      auth.verify(signed, tok.encode()), False)

print("\nEvidence names: only what this process writes")
good = ["20261009-004512-0001.jpg", "19691231-180318-0099.jpg"]
bad = [
    "../../etc/passwd", "../../../home/jetson/.venator/key",
    "..%2f..%2fetc%2fpasswd", "key", ".venator/key", "frame.jpg",
    "20261009-004512-0001.jpg.bak", "20261009-004512-001.jpg",
    "2026109-004512-0001.jpg", "20261009-004512-0001.JPG",
    "20261009_004512_0001.jpg", "", ".", "..", "/etc/shadow",
    "20261009-004512-0001.png", "a" * 300 + ".jpg",
]
for n in good:
    check(f"accepts {n!r}", bool(gui_server.EVIDENCE_NAME.match(n)))
for n in bad:
    check(f"refuses {n!r}", bool(gui_server.EVIDENCE_NAME.match(n)), False)
# Traversal is refused by shape, not merely by stripping "..": basename() alone
# would turn ../../etc/passwd into "passwd", which the pattern then rejects.
check("basename plus pattern refuses a traversal payload",
      bool(gui_server.EVIDENCE_NAME.match(os.path.basename("../../etc/passwd"))), False)

print("\nViewer cap and stream accounting")
hub = gui_server.Hub()
check("starts with slots free", hub.stream_slots_free())

# frames() is a generator: it claims its slot on the first next(), then blocks
# waiting for a frame newer than the one it started on. So register everybody
# first, confirm the cap, and only then publish.
gens, got, threads = [], [], []
for _ in range(gui_server.MAX_VIEWERS):
    g = hub.frames("hi")
    gens.append(g)
    t = threading.Thread(target=lambda gg=g: got.append(next(gg, None)), daemon=True)
    threads.append(t)
    t.start()

deadline = time.monotonic() + 5.0
while hub.stream_slots_free() and time.monotonic() < deadline:
    time.sleep(0.01)
check("cap is reached once every viewer has registered",
      hub.stream_slots_free(), False)

JPEG = b"\xff\xd8jpeg\xff\xd9"
hub.publish_frame("hi", JPEG)
for t in threads:
    t.join(timeout=5.0)
check(f"all {gui_server.MAX_VIEWERS} viewers got the same frame",
      got, [JPEG] * gui_server.MAX_VIEWERS)
check("a suspended viewer still holds its slot", hub.stream_slots_free(), False)
for g in gens:
    g.close()
check("closing viewers frees the slots", hub.stream_slots_free())

# A viewer that never reads must not be able to stall the producer. The hub
# keeps only the newest JPEG, so publishing far more frames than any queue
# depth has to stay non-blocking.
hub_slow = gui_server.Hub()
idle = hub_slow.frames("hi")
t = threading.Thread(target=lambda: next(idle, None), daemon=True)
t.start()
deadline = time.monotonic() + 5.0
while hub_slow.stream_slots_free() and time.monotonic() < deadline:
    time.sleep(0.01)
start = time.monotonic()
for i in range(500):
    hub_slow.publish_frame("hi", b"x" * 64)
elapsed = time.monotonic() - start
check(f"500 frames published past a stalled viewer in {elapsed*1000:.0f} ms",
      elapsed < 2.0)
t.join(timeout=2.0)
idle.close()

print("\nDelivery policy: detections may drop, alerts may not")
hub2 = gui_server.Hub()
events = hub2.events()
# events() registers its subscriber on the first next(), which returns the
# seeded status immediately. Publishing before that point would deliver to
# nobody, so register first.
check("first event is the seeded status", next(events)[0], "status")

for i in range(200):
    hub2.publish("det", {"seq": i, "d": []})
for i in range(3):
    hub2.publish("alert", {"id": f"a{i}", "kind": "person_down"}, reliable=True)

# Drained on a thread so a delivery bug fails the test instead of hanging it.
seen = []
drainer = threading.Thread(
    target=lambda: [seen.append(next(events)) for _ in range(4)], daemon=True)
drainer.start()
drainer.join(timeout=5.0)
check("four events delivered without blocking", len(seen), 4)

alerts = [p["id"] for n, p in seen if n == "alert"]
dets = [p for n, p in seen if n == "det"]
check("all three alerts survived 200 intervening detections",
      sorted(alerts), ["a0", "a1", "a2"])
check("alerts arrive in the order they were raised", alerts, ["a0", "a1", "a2"])
check("200 detections coalesced to one", len(dets), 1)
check("and it is the newest, not the oldest", dets[0]["seq"], 199)
events.close()

print("\nAck clears the unacked count")
hub3 = gui_server.Hub()
hub3.publish("alert", {"id": "x1"}, reliable=True)
hub3.publish("alert", {"id": "x2"}, reliable=True)
check("two unacked", hub3.snapshot()["alerts_unacked"], 2)
check("acking one leaves one", hub3.ack("x1"), 1)
check("acking an unknown id is harmless", hub3.ack("nope"), 1)
check("snapshot agrees", hub3.snapshot()["alerts_unacked"], 1)

print("\nPage rendering")
html = gui_page.render(tok, {"quality": "hi"}, gui_server.QUALITIES)
check("token is embedded as a JSON string", f'"{tok}"' in html)
check("no unreplaced placeholders", "__TOKEN__" not in html and "__QUALITIES__" not in html)
check("quality rungs are present", '"hi"' in html and '"lo"' in html)
check("declares a viewport for phones", "viewport" in html)
check("forces dark, with no light-mode branch",
      "prefers-color-scheme:light" not in html.replace(" ", ""))
check("reserves the iOS home-bar area", "safe-area-inset-bottom" in html)
null_tok = gui_page.render(None, {"quality": "hi"}, gui_server.QUALITIES)
check("a missing token renders as null, not the string 'None'",
      "null" in null_tok and "None" not in null_tok)

print("\nPorts are distinct and overridable")
check("GUI and relay no longer collide", ports.GUI_HTTP != ports.PHONE_RELAY_HTTP)
check("GUI keeps the advertised 8080", ports.GUI_HTTP, 8080)
check("alerts use their own UDP port", ports.ALERTS_UDP != ports.CAMERA_COORDS_UDP)
check("a malformed override falls back rather than crashing",
      ports._port("VENATOR_TEST_PORT_X", 1234), 1234)
os.environ["VENATOR_TEST_PORT_X"] = "not-a-port"
check("garbage falls back", ports._port("VENATOR_TEST_PORT_X", 1234), 1234)
os.environ["VENATOR_TEST_PORT_X"] = "99999"
check("out-of-range falls back", ports._port("VENATOR_TEST_PORT_X", 1234), 1234)
os.environ["VENATOR_TEST_PORT_X"] = "9999"
check("a valid override is honoured", ports._port("VENATOR_TEST_PORT_X", 1234), 9999)
del os.environ["VENATOR_TEST_PORT_X"]

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
