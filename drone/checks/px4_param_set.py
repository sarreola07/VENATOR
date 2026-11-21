#!/usr/bin/env python3
"""Set ONE PX4 parameter from a short allowlist: disarmed only, typed YES, read back.

    ./venv/bin/python drone/checks/px4_param_set.py COM_POS_FS_EPH 20
    ./venv/bin/python drone/checks/px4_param_set.py --self-test

Refuses while venator-c2 (or anything else) holds the Pixhawk port, refuses when the
aircraft is armed or no fresh autopilot heartbeat arrives, shows the current and the
new value, and writes only after you type YES. It then reads the value back from PX4
and prints OK or FAILED (exit code 0 or 1). Nothing else is ever sent.
"""
import argparse
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# name: (kind, min, max, what it is)
ALLOWED = {
    "COM_POS_FS_EPH": ("float", 1.0, 50.0,
                       "position-accuracy limit for auto modes: 5 outdoors, 20 indoor flow"),
    "EKF2_HGT_REF": ("int", 0, 3, "height reference: 0 baro (indoor), 1 GPS (outdoor)"),
    "EKF2_GPS_CTRL": ("int", 0, 15, "GPS aiding: 0 indoor, 7 outdoor"),
    "MAN_ARM_GESTURE": ("int", 0, 1, "stick arm gesture: 0 indoor demo, 1 outdoor"),
}
MAV_PARAM_TYPE_INT32 = 6
MAV_PARAM_TYPE_REAL32 = 9


def int_to_wire(i):
    """PX4 sends and expects INT32 values bytewise inside PARAM_*'s float field."""
    return struct.unpack("<f", struct.pack("<i", int(i)))[0]


def wire_to_int(f):
    return struct.unpack("<i", struct.pack("<f", f))[0]


def param_name(pid):
    if isinstance(pid, bytes):
        pid = pid.decode("ascii", "replace")
    return pid.split("\x00", 1)[0].strip()


def parse_value(name, text):
    kind, lo, hi, _ = ALLOWED[name]
    v = float(text)
    if not math.isfinite(v):
        raise ValueError(f"{name} needs a number")
    if kind == "int":
        if v != int(v):
            raise ValueError(f"{name} takes a whole number")
        v = int(v)
    if not lo <= v <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return v


def decode(pv, kind):
    want = MAV_PARAM_TYPE_INT32 if kind == "int" else MAV_PARAM_TYPE_REAL32
    if pv.param_type != want:
        raise ValueError(f"PX4 reports type {pv.param_type}, expected {want}")
    return wire_to_int(pv.param_value) if kind == "int" else float(pv.param_value)


def same(kind, a, b):
    return a == b if kind == "int" else abs(a - b) < 1e-4


class Px4:
    def __init__(self, dev):
        from pymavlink import mavutil
        self.M = mavutil.mavlink
        self.m = mavutil.mavlink_connection(dev, baud=115200)
        self.m.mav.heartbeat_send(self.M.MAV_TYPE_GCS, self.M.MAV_AUTOPILOT_INVALID, 0, 0, 0)
        if self.m.wait_heartbeat(timeout=10) is None:
            sys.exit("REFUSED: no heartbeat from the Pixhawk.")

    def _drain(self, seconds=0.3):
        end = time.monotonic() + seconds
        while time.monotonic() < end and self.m.recv_match(blocking=False) is not None:
            pass

    def require_disarmed(self):
        """Fail closed: a NEW autopilot heartbeat that says disarmed, or refuse."""
        self._drain()
        end = time.monotonic() + 3
        while time.monotonic() < end:
            hb = self.m.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
            if hb is None or hb.autopilot != self.M.MAV_AUTOPILOT_PX4:
                continue
            if hb.base_mode & self.M.MAV_MODE_FLAG_SAFETY_ARMED:
                sys.exit("REFUSED: the aircraft is ARMED. Nothing was written.")
            return
        sys.exit("REFUSED: no fresh heartbeat from the autopilot. Nothing was written.")

    def _await_value(self, name, seconds=3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            pv = self.m.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.5)
            if pv is not None and param_name(pv.param_id) == name:
                return pv
        return None

    def read(self, name):
        self._drain()
        self.m.mav.param_request_read_send(self.m.target_system, self.m.target_component,
                                           name.encode(), -1)
        return self._await_value(name)

    def write(self, name, kind, value):
        if kind == "int":
            wire, ptype = int_to_wire(value), MAV_PARAM_TYPE_INT32
        else:
            wire, ptype = float(value), MAV_PARAM_TYPE_REAL32
        self.m.mav.param_set_send(self.m.target_system, self.m.target_component,
                                  name.encode(), wire, ptype)
        return self._await_value(name)

    def close(self):
        self.m.close()


def self_test():
    ok = True
    for i in (0, 1, 3, 7, 15):
        ok = ok and wire_to_int(int_to_wire(i)) == i
    for name, text, want in (("COM_POS_FS_EPH", "20", 20.0), ("COM_POS_FS_EPH", "5", 5.0),
                             ("EKF2_HGT_REF", "0", 0), ("EKF2_GPS_CTRL", "7", 7),
                             ("MAN_ARM_GESTURE", "1", 1)):
        ok = ok and parse_value(name, text) == want
    for name, text in (("COM_POS_FS_EPH", "0"), ("COM_POS_FS_EPH", "nan"), ("COM_POS_FS_EPH", "inf"),
                       ("COM_POS_FS_EPH", "500"), ("EKF2_HGT_REF", "0.5"), ("MAN_ARM_GESTURE", "2")):
        try:
            parse_value(name, text)
            ok = False
        except ValueError:
            pass
    ok = ok and param_name(b"COM_POS_FS_EPH\x00\x00") == "COM_POS_FS_EPH"
    ok = ok and same("float", 20.0, 20.000001) and not same("float", 20.0, 5.0)
    print("self-test", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?")
    ap.add_argument("value", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.name or a.value is None:
        ap.error("give NAME VALUE")
    name = a.name.strip().upper()
    if name not in ALLOWED:
        sys.exit(f"REFUSED: {name} is not on this tool's list ({', '.join(ALLOWED)}).")
    try:
        value = parse_value(name, a.value)
    except ValueError as exc:
        sys.exit(f"REFUSED: {exc}")
    kind, _, _, what = ALLOWED[name]

    from preflight_audit import find_fc        # noqa: E402
    from px4_shell_probe import interlock      # noqa: E402
    dev = find_fc()
    interlock(dev)
    px4 = Px4(dev)
    try:
        px4.require_disarmed()
        pv = px4.read(name)
        if pv is None:
            print(f"FAILED: PX4 did not report {name}. Nothing was written.")
            return 1
        cur = decode(pv, kind)
        print(f"\n  {name}: now {cur:g}  ->  new {value:g}\n  ({what})\n")
        if same(kind, cur, value):
            print(f"OK: {name} is already {cur:g}. Nothing written.")
            return 0
        if input("Type YES to write it: ").strip() != "YES":
            print("Not written. Nothing changed.")
            return 1
        px4.require_disarmed()
        px4.write(name, kind, value)
        back = px4.read(name)
        got = None if back is None else decode(back, kind)
        if got is None or not same(kind, got, value):
            print(f"FAILED: PX4 reads back {got}, not {value:g}. Check it before flying.")
            return 1
        print(f"OK: {name} = {got:g} (written and read back from PX4).")
        return 0
    finally:
        px4.close()


if __name__ == "__main__":
    sys.exit(main())
