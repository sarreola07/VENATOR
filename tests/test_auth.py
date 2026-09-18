#!/usr/bin/env python3
"""Message authentication on the C2 link.

Without a key the link must behave exactly as it did before — that is what makes
this safe to deploy ahead of switching it on. With a key on both ends, anything
unsigned, tampered with, replayed, or signed with a different key must be dropped
before the caller sees it.

Stdlib only, no hardware: a loopback fake serial carries bytes between two links.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PASS = FAIL = 0


def check(label, got, want=True):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"    {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"   got {got!r}"))


class Wire:
    """A shared byte queue standing in for the air between two sticks."""
    def __init__(self):
        self.a_to_b, self.b_to_a = bytearray(), bytearray()


class FakeSerial:
    def __init__(self, port, baud, timeout=0.2, exclusive=False):
        self.port, self.exclusive, self.alive = port, exclusive, True
        self.tx, self.rx = WIRE_FOR[port]

    def write(self, data):
        self.tx.extend(data)

    def read(self, n):
        out, self.rx[:] = bytes(self.rx[:n]), self.rx[n:]
        return out

    def flush(self):
        pass

    def reset_input_buffer(self):
        self.rx.clear()

    def close(self):
        self.alive = False


WIRE = Wire()
WIRE_FOR = {"/dev/a": (WIRE.a_to_b, WIRE.b_to_a),
            "/dev/b": (WIRE.b_to_a, WIRE.a_to_b)}
sys.modules["serial"] = types.SimpleNamespace(Serial=FakeSerial)

from radio import auth                      # noqa: E402
from radio.serial_link import SerialLink     # noqa: E402

KEY = b"a" * 64
OTHER = b"b" * 64


def pair(ka, kb):
    return (SerialLink("/dev/a", auth_key=ka, send_gap=0, log=lambda m: None),
            SerialLink("/dev/b", auth_key=kb, send_gap=0, log=lambda m: None))


def drain(link, tries=4):
    for _ in range(tries):
        m = link.poll()
        if m is not None:
            return m
    return None


print("\n  No key: the link behaves exactly as it did before")
a, b = pair(None, None)
check("reports unauthenticated", a.authenticated, False)
a.send({"t": "RUN", "seq": 1, "id": 4})
check("message arrives unsigned", drain(b), {"t": "RUN", "seq": 1, "id": 4})

print("\n  Same key on both ends")
a, b = pair(KEY, KEY)
check("reports authenticated", a.authenticated, True)
a.send({"t": "RUN", "seq": 2, "id": 4})
got = drain(b)
check("message arrives", got, {"t": "RUN", "seq": 2, "id": 4})
check("auth fields are stripped before the caller sees it",
      got is not None and "m" not in got and "n" not in got)

print("\n  A signed message really is signed on the wire")
a.send({"t": "CONFIRM", "seq": 3})
raw = bytes(WIRE.a_to_b).decode()
check("tag present on the wire", '"m":' in raw)
check("nonce present on the wire", '"n":' in raw)
drain(b)

print("\n  What a receiver with a key must refuse")
unsigned, b2 = pair(None, KEY)
unsigned.send({"t": "RUN", "seq": 4, "id": 4})
check("unsigned message from a stranger is dropped", drain(b2), None)

wrong, b3 = pair(OTHER, KEY)
wrong.send({"t": "RUN", "seq": 5, "id": 4})
check("message signed with a different key is dropped", drain(b3), None)

a4, b4 = pair(KEY, KEY)
a4.send({"t": "CONFIRM", "seq": 6})
captured = bytes(WIRE.a_to_b)
check("the genuine one is accepted", drain(b4) is not None)
WIRE.a_to_b.extend(captured)                # attacker replays what they heard
check("the same packet replayed is dropped", drain(b4), None)

tampered = captured.decode().replace('"seq":6', '"seq":9').encode()
WIRE.a_to_b.extend(tampered)
check("a modified packet is dropped", drain(b4), None)

print("\n  Key handling")
import os, tempfile                          # noqa: E402
with tempfile.TemporaryDirectory() as d:
    kp = Path(d) / "key"
    auth.create_key(kp)
    check("key file is 0600", oct(kp.stat().st_mode)[-3:], "600")
    check("loads back", auth.load_key(kp) is not None)
    check("missing key file reads as None", auth.load_key(Path(d) / "nope"), None)

print("\n  ====================================================")
print(f"  {'ALL CHECKS PASSED' if not FAIL else f'{FAIL} CHECK(S) FAILED'}")
sys.exit(1 if FAIL else 0)
