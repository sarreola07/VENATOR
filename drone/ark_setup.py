#!/usr/bin/env python3
"""
ARK Flow sensor setup and validation for indoor hovering.

Can be run standalone (manual validation) or imported and called as a module
from c2_server.py for automated preflight checks.

    # Standalone:
    python drone/ark_setup.py
    python drone/ark_setup.py --device /dev/ttyACM0
    python drone/ark_setup.py --apply      # write the indoor PX4 settings (asks first)

    # From c2_server.py (programmatic):
    from drone.ark_setup import ARKSetup
    ark = ARKSetup()
    status = ark.validate()  # returns dict with ready/issues/quality
"""
import argparse
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from pymavlink import mavutil
except ImportError:
    sys.exit("pymavlink not installed. Run: ./venv/bin/python")

# find_fc() and readp() both live here: one Pixhawk-probing helper for the whole
# repo rather than a second copy that drifts. readp() in particular decodes PX4's
# INT32 parameters, which every parameter in PARAMS below happens to be.
from checks import preflight_audit

# Copied from check_flow.py for consistency
LIFT_SPAN_M = 0.3
FLOW_QUALITY_MIN = 100
LOCAL_RATE_MIN_HZ = 5.0
HORIZ_SPAN_MIN_M = 0.05
WATCH_S = 15.0

POS_HORIZ_REL = 8
POS_VERT_AGL = 64
CONST_POS_MODE = 128

PARAMS = (
    ("UAVCAN_ENABLE", lambda v: v >= 2, "2 or more: ARK Flow talks DroneCAN", "FAIL"),
    ("UAVCAN_SUB_FLOW", lambda v: v == 1, "1: take ARK Flow's optical flow", "FAIL"),
    ("UAVCAN_SUB_RNG", lambda v: v == 1, "1: take ARK Flow's distance sensor", "FAIL"),
    ("EKF2_OF_CTRL", lambda v: v == 1, "1: use optical flow for position", "FAIL"),
    ("EKF2_RNG_CTRL", lambda v: v >= 1, "1 or more: use distance sensor", "FAIL"),
    ("EKF2_HGT_REF", lambda v: v == 2, "2: height from distance sensor", "FAIL"),
    ("EKF2_GPS_CTRL", lambda v: v == 0, "0 indoors: no GPS to use", "WARN"),
    ("COM_ARM_WO_GPS", lambda v: v == 1, "1: allow arming without GPS", "WARN"),
)

# What --apply writes, for each PARAMS entry that fails its test. All INT32.
# EKF2_HGT_REF and EKF2_GPS_CTRL are the two that change for indoor flight on
# this aircraft; their outdoor values (1 and 7) are printed before any write so
# they can be put back. Not applied while the sensor is silent: pointing height
# at a rangefinder that sends nothing and switching GPS off would leave no
# reference at all (see docs/ARK_SETUP.md).
WANT = {
    "UAVCAN_ENABLE": 2,
    "UAVCAN_SUB_FLOW": 1,
    "UAVCAN_SUB_RNG": 1,
    "EKF2_OF_CTRL": 1,
    "EKF2_RNG_CTRL": 1,
    "EKF2_HGT_REF": 2,
    "EKF2_GPS_CTRL": 0,
    "COM_ARM_WO_GPS": 1,
}

STREAMS = {
    "LOCAL_POSITION_NED": 32,
    "OPTICAL_FLOW_RAD": 106,
    "DISTANCE_SENSOR": 132,
    "ESTIMATOR_STATUS": 230,
}

COLOUR = {
    "OK": "\033[92m[OK]\033[0m",
    "WARN": "\033[93m[WARN]\033[0m",
    "FAIL": "\033[91m[FAIL]\033[0m",
    "INFO": "\033[94m[INFO]\033[0m",
}


def judge_param(name, value):
    test, want, level = next((t, w, lv) for n, t, w, lv in PARAMS if n == name)
    if value is None:
        return (level or "INFO", f"{name}: no answer ({want})")
    if test is None:
        return ("INFO", f"{name} = {value}  ({want})")
    if test(value):
        return ("OK", f"{name} = {value}")
    return (level, f"{name} = {value}, want {want}")


def judge_readings(r, seconds):
    out = []
    lifted = False

    d = r.get("distance_m") or []
    if not d:
        out.append(("FAIL", "DISTANCE_SENSOR: nothing received"))
    else:
        lo, hi = min(d), max(d)
        lifted = hi - lo >= LIFT_SPAN_M
        if lifted:
            out.append(("OK", f"DISTANCE_SENSOR: {lo:.2f}–{hi:.2f} m (lifted)"))
        else:
            out.append(("WARN", f"DISTANCE_SENSOR: {lo:.2f}–{hi:.2f} m (flat—lift drone)"))

    q = r.get("flow_quality") or []
    if not q:
        out.append(("FAIL", "OPTICAL_FLOW_RAD: nothing received"))
    else:
        med = statistics.median(q)
        if med >= FLOW_QUALITY_MIN:
            out.append(("OK", f"OPTICAL_FLOW_RAD: quality {med:.0f}"))
        elif med > 0:
            out.append(("WARN", f"OPTICAL_FLOW_RAD: quality {med:.0f} < {FLOW_QUALITY_MIN}"))
        else:
            out.append(("FAIL", "OPTICAL_FLOW_RAD: quality 0 (lens covered/dirty)"))

    z = r.get("local_z_m") or []
    if not z:
        out.append(("FAIL", "LOCAL_POSITION_NED: nothing received"))
    else:
        rate = len(z) / seconds if seconds > 0 else 0.0
        span = max(z) - min(z)
        if rate < LOCAL_RATE_MIN_HZ:
            out.append(("WARN", f"LOCAL_POSITION_NED: only {rate:.1f} Hz"))
        else:
            out.append(("OK", f"LOCAL_POSITION_NED: {rate:.0f} Hz, height moved {span:.2f} m"))

    xy = r.get("local_xy_m") or []
    trusted_horiz = any(f & POS_HORIZ_REL for f in (r.get("est_flags") or []))
    if not xy:
        out.append(("FAIL", "Horizontal position: no LOCAL_POSITION_NED"))
    elif not trusted_horiz:
        out.append(("FAIL", "Horizontal position: not trusted by EKF"))
    else:
        xs = [p[0] for p in xy]
        ys = [p[1] for p in xy]
        span = max(max(xs) - min(xs), max(ys) - min(ys))
        if span < HORIZ_SPAN_MIN_M:
            out.append(("WARN", f"Horizontal position: only {span:.3f} m moved"))
        else:
            out.append(("OK", f"Horizontal position: x {min(xs):+.2f}–{max(xs):+.2f} m"))

    return out


def exit_code(results):
    return 1 if any(level == "FAIL" for level, _ in results) else 0


def c2_running(run=subprocess.run):
    try:
        return run(["systemctl", "is-active", "--quiet", "venator-c2"]).returncode == 0
    except (FileNotFoundError, OSError):
        return False


def _readp(m, name):
    """Read a PX4 parameter from the Pixhawk, or None if it never answers.

    Delegates to preflight_audit.readp, which is the version that has actually
    been run against this aircraft. Two things it gets right that are easy to
    miss: pymavlink hands PARAM_VALUE.param_id over already decoded to str on
    2.4.50 (so stripping it as bytes raises TypeError on the first reply), and
    PX4 sends INT32 parameters as reinterpreted float bits -- every parameter in
    PARAMS is an INT32, so the raw param_value would not compare as written."""
    return preflight_audit.readp(m, name)


def int32_as_float(value):
    """PX4 sends and expects INT32 parameters as their bit pattern reinterpreted
    as a float (the MAVLink "byte-wise" encoding), the inverse of what
    preflight_audit.readp() undoes on the way in."""
    return struct.unpack("<f", struct.pack("<i", int(value)))[0]


def writep(m, name, value, readp=None):
    """Write one INT32 parameter and read it back. True if PX4 now holds value."""
    readp = readp or _readp
    m.mav.param_set_send(m.target_system, m.target_component, name.encode(),
                         int32_as_float(value), mavutil.mavlink.MAV_PARAM_TYPE_INT32)
    time.sleep(0.2)
    return readp(m, name) == value


def apply_params(m, want=WANT, readp=None, writep_fn=None, log=print):
    """Bring every PARAMS entry that fails its test to its WANT value.

    Returns [(name, before, after, ok)]. A parameter already passing is left
    alone (before == after, ok True), so running this twice changes nothing,
    and a parameter whose write did not read back as written is ok False."""
    readp = readp or _readp
    writep_fn = writep_fn or (lambda mm, n, v: writep(mm, n, v, readp=readp))
    out = []
    for name, test, _, _ in PARAMS:
        before = readp(m, name)
        if before is not None and test(before):
            out.append((name, before, before, True))
            continue
        target = want[name]
        ok = writep_fn(m, name, target)
        after = readp(m, name)
        out.append((name, before, after, bool(ok) and after == target))
        log(f"  {COLOUR['OK' if out[-1][3] else 'FAIL']} {name}: {before} -> {after}"
            + ("" if out[-1][3] else f" (wanted {target})"))
    return out


def watch(m, seconds):
    """Collect the readings judge_readings() takes, for `seconds`.

    The moment PX4's HEARTBEAT shows the vehicle armed, a force-disarm is
    sent and RuntimeError raised: the operator is holding the aircraft during
    this, and with COM_ARM_WO_GPS the RC sticks can arm it."""
    r = {
        "distance_m": [],
        "flow_quality": [],
        "local_z_m": [],
        "local_xy_m": [],
        "est_flags": [],
    }
    def interval(micros):
        for msg_id in STREAMS.values():
            m.mav.command_long_send(
                m.target_system, m.target_component,
                mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                msg_id, micros, 0, 0, 0, 0, 0)

    interval(100000)
    try:
        end = time.time() + seconds
        next_beat = 0.0
        while time.time() < end:
            if time.time() >= next_beat:
                m.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
                next_beat = time.time() + 1.0
            msg = m.recv_match(type=list(STREAMS) + ["HEARTBEAT"], blocking=True, timeout=0.5)
            if msg is None:
                continue
            t = msg.get_type()
            if t == "HEARTBEAT":
                if (msg.get_srcSystem() == m.target_system
                        and msg.type != mavutil.mavlink.MAV_TYPE_GCS
                        and msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
                    # 21196 is PX4's force code: disarm even in the air / with
                    # motors turning. In hand, that is the point.
                    m.mav.command_long_send(
                        m.target_system, m.target_component,
                        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
                        0, 21196, 0, 0, 0, 0, 0)
                    raise RuntimeError("drone ARMED during the check — force-disarm sent; "
                                       "set it down, kill switch ON")
                continue
            if t == "DISTANCE_SENSOR":
                r["distance_m"].append(msg.current_distance / 100.0)
            elif t == "OPTICAL_FLOW_RAD":
                r["flow_quality"].append(msg.quality)
            elif t == "LOCAL_POSITION_NED":
                r["local_z_m"].append(msg.z)
                r["local_xy_m"].append((msg.x, msg.y))
            elif t == "ESTIMATOR_STATUS":
                r["est_flags"].append(msg.flags)
        return r
    finally:
        # Hand the streams back to PX4's default rates. When this runs on the C2
        # server's own connection, four extra 10 Hz streams left running would
        # eat link budget that in-flight STATUS needs for the rest of the day.
        interval(0)


class ARKSetup:
    """Jetson-side ARK sensor validator. Can run standalone or be called from C2 server.

    Pass `master` to borrow an already-open MAVLink connection -- that is how
    c2_server uses this, because only one reader can own the Pixhawk's tty. A
    borrowed connection is never closed here; the owner closes it."""

    def __init__(self, device=None, baud=115200, master=None):
        self.device = device
        self.baud = baud
        self.master = master
        self._owns_master = master is None

    def connect(self):
        if self.master is not None:
            return True
        if self.device is None:
            self.device = preflight_audit.find_fc()
        try:
            self.master = mavutil.mavlink_connection(self.device, baud=self.baud)
            self.master.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            hb = self.master.wait_heartbeat(timeout=12)
            if hb is None:
                return False
            if hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                return False
            return True
        except Exception:
            return False

    def validate(self, watch_seconds=WATCH_S, on_watch=None):
        """Check if ARK sensor is ready. Returns dict with ready/issues/quality.

        on_watch(seconds) is called once, immediately before the live watch
        starts. The parameter reads come first and can take twenty seconds, so
        an operator told to lift the aircraft when the check was *requested*
        lifts it far too early and the watch records a stationary drone. The
        standalone path prints a heading here; c2_server sends a radio LOG."""
        if not self.connect():
            return {
                "ready": False,
                "issues": ["Failed to connect to Pixhawk"],
                "quality": 0,
            }

        try:
            issues = []

            # Check parameters
            for name, *_ in PARAMS:
                level, text = judge_param(name, _readp(self.master, name))
                if level == "FAIL":
                    issues.append(text)

            # Collect readings
            if on_watch:
                on_watch(watch_seconds)
            raw = watch(self.master, watch_seconds)
            for level, text in judge_readings(raw, watch_seconds):
                if level == "FAIL":
                    issues.append(text)

            # Flow quality comes from the readings themselves rather than being
            # parsed back out of the text they were formatted into: a WARN-level
            # "quality 50 < 100" is not a number, and reported as 0.
            q = raw.get("flow_quality") or []

            # issues already holds every FAIL, from the parameters and the
            # readings both, so it is the whole verdict.
            return {
                "ready": not issues,
                "issues": issues,
                "quality": int(statistics.median(q)) if q else 0,
            }
        finally:
            self.close()

    def close(self):
        """Close the link, unless it was lent to us -- closing the C2 server's
        own connection would cut the drone off mid-session."""
        if self.master and self._owns_master:
            self.master.close()
            self.master = None


def show(results):
    for level, text in results:
        print(f"  {COLOUR[level]} {text}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", help="Pixhawk serial port (auto-detect if omitted)")
    ap.add_argument("--seconds", type=float, default=WATCH_S,
                    help=f"Watch duration while lifting drone (default {WATCH_S:g}s)")
    ap.add_argument("--apply", action="store_true",
                    help="write the indoor PX4 settings that are not yet set (asks for YES "
                         "first; then power-cycle the Pixhawk and run the check again)")
    args = ap.parse_args()

    if args.seconds <= 0:
        ap.error("--seconds must be > 0")

    if c2_running():
        print("venator-c2 holds the Pixhawk port. Stop it:\n"
              "    sudo systemctl stop venator-c2")
        return 2

    ark = ARKSetup(device=args.device)
    if not ark.connect():
        print(f"  {COLOUR['FAIL']} Failed to connect to Pixhawk")
        return 2

    try:
        print(f"\n== PX4 Settings ==")
        params = [judge_param(name, _readp(ark.master, name))
                  for name, *_ in PARAMS]
        show(params)

        if args.apply:
            todo = [t for t in params if t[0] != "OK"]
            if not todo:
                print("\nNothing to write: every setting is already as wanted.")
                return 0
            print("\n--apply would write, for the lines above that are not OK:")
            for name in (n for n, *_ in PARAMS if judge_param(n, _readp(ark.master, n))[0] != "OK"):
                print(f"    {name} = {WANT[name]}")
            print("Outdoor values to restore afterwards: EKF2_HGT_REF = 1, EKF2_GPS_CTRL = 7.")
            print("Only do this once DISTANCE_SENSOR and OPTICAL_FLOW_RAD both read OK in the")
            print("live readings; with the sensor silent these settings remove the only height")
            print("and position reference the EKF has.")
            if input("Type YES to write them now: ").strip() != "YES":
                print("Nothing written.")
                return 2
            results = apply_params(ark.master)
            bad = [r for r in results if not r[3]]
            print("\nPower-cycle the Pixhawk (EKF2 settings take effect at boot), then run")
            print("this check again without --apply.")
            return 1 if bad else 0

        print(f"\n== Live Readings ({args.seconds:g}s: lift drone ~0.5m) ==")
        readings = judge_readings(watch(ark.master, args.seconds), args.seconds)
        show(readings)

        results = params + readings
        print("\nSummary:")
        return exit_code(results)
    finally:
        ark.close()


if __name__ == "__main__":
    sys.exit(main())
