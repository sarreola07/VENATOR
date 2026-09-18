#!/usr/bin/env python3
"""The LoRa stick disappearing must not kill the link object.

A stick re-enumerates when it is unplugged, when USB resets, or when the Jetson
browns out. Before this, the Link kept the dead handle and printed a read error
on every poll — tens of thousands of identical lines while the link sat there,
recoverable only by restarting. These checks pin the behaviour that replaced it.

Stdlib only and no hardware: a fake serial module is injected so this runs the
same on a laptop, the Jetson and CI.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PASS = FAIL = 0


def check(label, got, want):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"    {'PASS' if ok else 'FAIL'}  {label}"
          + ("" if ok else f"   got {got!r}, want {want!r}"))


class FakeSerial:
    """Minimal pyserial stand-in. `alive` flips to simulate the stick vanishing."""
    opened = 0

    def __init__(self, port, baud, timeout=0.2, exclusive=False):
        FakeSerial.opened += 1
        if not FakeSerial.available:
            raise OSError(f"could not open port {port}")
        self.port, self.exclusive, self.alive = port, exclusive, True
        self.written = []

    def _guard(self):
        if not self.alive:
            raise OSError("device reports readiness to read but returned no data")

    def read(self, n):
        self._guard()
        return b""

    def write(self, data):
        self._guard()
        self.written.append(data)

    def flush(self):
        self._guard()

    def reset_input_buffer(self):
        self._guard()

    def close(self):
        self.alive = False


FakeSerial.available = True
sys.modules["serial"] = types.SimpleNamespace(Serial=FakeSerial)

from radio.link_test import Link, LinkDown  # noqa: E402  (needs the fake first)

print("\n  Link survives the stick disappearing")
link = Link("/dev/fake", settle=0)
check("opens exclusively", link.ser.exclusive, True)
check("reports up", link.up, True)

link.ser.alive = False                      # stick yanked
check("poll returns None, does not raise", link.poll(), None)
check("reports down", link.up, False)

opened_before = FakeSerial.opened
check("does not hammer the port while waiting", link.poll(), None)
check("no reopen attempt before the retry timer", FakeSerial.opened, opened_before)

print("\n  Sending while down is an error the caller can show")
try:
    link.send({"t": "PING", "seq": 1})
    check("send raises LinkDown", "no exception", "LinkDown")
except LinkDown:
    check("send raises LinkDown", "LinkDown", "LinkDown")

print("\n  It comes back on its own")
link._retry_at = 0                          # the wait elapsed
check("poll reconnects", link.poll(), None)
check("reports up again", link.up, True)
link.send({"t": "PING", "seq": 2})
check("send works after reconnect", len(link.ser.written), 1)

print("\n  A port that will not open stays down without raising")
link2 = Link("/dev/fake2", settle=0)
link2.ser.alive = False
link2.poll()
FakeSerial.available = False
link2._retry_at = 0
check("poll still returns None", link2.poll(), None)
check("still down", link2.up, False)
FakeSerial.available = True

print("\n  ====================================================")
print(f"  {'ALL CHECKS PASSED' if not FAIL else f'{FAIL} CHECK(S) FAILED'}")
sys.exit(1 if FAIL else 0)
