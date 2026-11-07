#!/usr/bin/env python3
"""
ARK Flow check: can the Pixhawk keep a position indoors, with no GPS?

The indoor hover depends on the ARK Flow (optical flow plus a downward distance
sensor, on the Pixhawk's CAN port) giving PX4 a position and a height. This
reads whether PX4 is set up to use it, and whether it really does while you lift
the drone by hand. Its output is what the hover work is waiting on.

    sudo systemctl stop venator-c2          # one owner per serial port
    ./venv/bin/python drone/checks/check_flow.py
    sudo systemctl start venator-c2

Props off. While it watches (15 s), lift the drone about 0.5 m over a textured
floor, hold it there for about 5 s, and put it back down. PX4 only starts using
the flow once the sensor is in range and the picture is good, so a drone that
never leaves the bench can read as "no position" even with a working sensor.

Read-only. It never arms and changes no parameter and no flight mode. It sends
a heartbeat, because PX4 streams nothing over USB until it hears one, and asks
PX4 to stream the messages it reads at 10 Hz: a stream setting, not a
parameter, and it resets when PX4 reboots. It refuses to run while venator-c2
holds the port, and while the drone is armed.

The verdicts are plain functions of plain numbers, with no pymavlink import, so
tests/test_check_flow.py pins them in CI the way the aircraft runs them.
"""
import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

#: Lifting the drone by hand should move the distance reading at least this far.
LIFT_SPAN_M = 0.3
#: Optical flow quality is 0-255. Below about 100, PX4 struggles to use it: the
#: floor needs more texture or more light (a mat, or a tape pattern on a shiny floor).
FLOW_QUALITY_MIN = 100
#: A position PX4 can hold should arrive at least this often.
LOCAL_RATE_MIN_HZ = 5.0
WATCH_S = 15.0

#: ESTIMATOR_STATUS flags (MAVLink ESTIMATOR_STATUS_FLAGS).
POS_HORIZ_REL = 8           # a relative horizontal position PX4 trusts
POS_VERT_AGL = 64           # a height above the ground PX4 trusts
CONST_POS_MODE = 128        # no position aiding at all: it assumes it isn't moving

#: The PX4 settings the indoor hover needs, from the ARK Flow checklist:
#: (name, test or None, what it should be, level when it isn't).
#: A test of None is reported, not judged.
PARAMS = (
    ("UAVCAN_ENABLE", lambda v: v >= 2, "2 or more: the ARK Flow talks DroneCAN", "FAIL"),
    ("UAVCAN_SUB_FLOW", lambda v: v == 1, "1: take the ARK Flow's optical flow", "FAIL"),
    ("UAVCAN_SUB_RNG", lambda v: v == 1, "1: take the ARK Flow's distance sensor", "FAIL"),
    ("EKF2_OF_CTRL", lambda v: v == 1, "1: use optical flow for position", "FAIL"),
    ("EKF2_RNG_CTRL", lambda v: v >= 1, "1 or more: use the distance sensor", "FAIL"),
    ("EKF2_HGT_REF", lambda v: v == 2, "2: height from the distance sensor, as the hover plan assumes", "FAIL"),
    ("EKF2_GPS_CTRL", lambda v: v == 0, "0 indoors: there is no GPS to use", "WARN"),
    ("COM_ARM_WO_GPS", lambda v: v == 1, "1, as it was when last checked", "WARN"),
    ("SENS_FLOW_ROT", None, "how the sensor is turned on the frame", None),
    ("EKF2_OF_POS_X", None, "sensor offset forward of the centre, m", None),
    ("EKF2_OF_POS_Y", None, "sensor offset right of the centre, m", None),
    ("EKF2_OF_POS_Z", None, "sensor offset below the centre, m", None),
)

#: MAVLink message ids to ask PX4 for, at 10 Hz.
STREAMS = {"LOCAL_POSITION_NED": 32, "GLOBAL_POSITION_INT": 33, "OPTICAL_FLOW_RAD": 106,
           "DISTANCE_SENSOR": 132, "ESTIMATOR_STATUS": 230}


# --- verdicts: plain numbers in, (level, text) out ---------------------------

def judge_param(name, value):
    """(level, text) for one PX4 setting. value is None when PX4 didn't answer."""
    test, want, level = next((t, w, lv) for n, t, w, lv in PARAMS if n == name)
    if value is None:
        return (level or "INFO",
                f"{name}: no answer. Not a setting in this PX4, or the link is slow ({want})")
    if test is None:
        return ("INFO", f"{name} = {value}  ({want})")
    if test(value):
        return ("OK", f"{name} = {value}")
    return (level, f"{name} = {value}, want {want}")


def judge_readings(r, seconds):
    """[(level, text)] for what PX4 sent while the drone was lifted.

    r holds plain lists: distance_m, flow_quality, local_z_m (NED, so up is
    negative), global_alt_m, est_flags (one int per ESTIMATOR_STATUS)."""
    out = []
    lifted = False

    d = r.get("distance_m") or []
    if not d:
        out.append(("FAIL", "DISTANCE_SENSOR: nothing. PX4 isn't getting the ARK Flow's "
                            "distance sensor (CAN wiring, termination, UAVCAN_SUB_RNG)"))
    else:
        lo, hi = min(d), max(d)
        lifted = hi - lo >= LIFT_SPAN_M
        if lifted:
            out.append(("OK", f"DISTANCE_SENSOR: {lo:.2f} to {hi:.2f} m, it followed the lift "
                              f"({len(d)} readings)"))
        else:
            out.append(("WARN", f"DISTANCE_SENSOR: {lo:.2f} to {hi:.2f} m, flat. Lift the drone "
                                f"about 0.5 m while this runs, and run it again"))

    q = r.get("flow_quality") or []
    if not q:
        out.append(("FAIL", "OPTICAL_FLOW_RAD: nothing. PX4 isn't getting optical flow "
                            "(CAN wiring, UAVCAN_SUB_FLOW)"))
    else:
        med = statistics.median(q)
        if med >= FLOW_QUALITY_MIN:
            out.append(("OK", f"OPTICAL_FLOW_RAD: quality {med:.0f} (median of {len(q)})"))
        elif med > 0:
            out.append(("WARN", f"OPTICAL_FLOW_RAD: quality {med:.0f}, under {FLOW_QUALITY_MIN}. "
                                f"The floor needs more texture or light: a mat, or a tape pattern"))
        else:
            out.append(("FAIL", "OPTICAL_FLOW_RAD: quality 0. The sensor sees nothing: lens "
                                "covered or dirty, or far too dark"))

    z = r.get("local_z_m") or []
    if not z:
        out.append(("FAIL", "LOCAL_POSITION_NED: nothing. PX4 has no local position, so it "
                            "can't hold one indoors"))
    else:
        rate = len(z) / seconds if seconds > 0 else 0.0
        span = max(z) - min(z)
        if rate < LOCAL_RATE_MIN_HZ:
            out.append(("WARN", f"LOCAL_POSITION_NED: only {rate:.1f} Hz"))
        elif lifted and span < LIFT_SPAN_M:
            out.append(("WARN", f"LOCAL_POSITION_NED: {rate:.0f} Hz, but its height moved only "
                                f"{span:.2f} m while the distance sensor saw the lift"))
        else:
            out.append(("OK", f"LOCAL_POSITION_NED: {rate:.0f} Hz, height moved {span:.2f} m"))

    flags = r.get("est_flags") or []
    if not flags:
        out.append(("WARN", "ESTIMATOR_STATUS: not received, so it can't say which "
                            "estimates PX4 trusts"))
    else:
        seen = 0
        for f in flags:
            seen |= f
        if all(f & CONST_POS_MODE for f in flags):
            out.append(("FAIL", "ESTIMATOR_STATUS: constant-position mode the whole time: PX4 "
                                "used no position aiding at all. Hold it lifted for about 5 s"))
        elif seen & POS_HORIZ_REL and seen & POS_VERT_AGL:
            out.append(("OK", "ESTIMATOR_STATUS: PX4 had a relative position and a height "
                              "above the ground"))
        else:
            missing = [what for bit, what in ((POS_HORIZ_REL, "a relative position"),
                                              (POS_VERT_AGL, "a height above the ground"))
                       if not seen & bit]
            out.append(("FAIL", "ESTIMATOR_STATUS: PX4 never had " + " or ".join(missing)))

    g = r.get("global_alt_m") or []
    if not g:
        out.append(("INFO", "GLOBAL_POSITION_INT: none indoors. The C2 server takes its "
                            "altitude only from this, so the hover needs another source"))
    else:
        rate = len(g) / seconds if seconds > 0 else 0.0
        out.append(("INFO", f"GLOBAL_POSITION_INT: {rate:.0f} Hz, relative "
                            f"altitude {min(g):.2f} to {max(g):.2f} m"))
    return out


def exit_code(results):
    """1 if anything failed, 0 if not."""
    return 1 if any(level == "FAIL" for level, _ in results) else 0


def c2_running(run=subprocess.run):
    """True while venator-c2 holds the Pixhawk's port. False where there is no
    systemd, a laptop standing in for the Jetson say."""
    try:
        return run(["systemctl", "is-active", "--quiet", "venator-c2"]).returncode == 0
    except (FileNotFoundError, OSError):
        return False


# --- talking to PX4 -----------------------------------------------------------

COLOUR = {"OK": "\033[92m[ OK ]\033[0m", "WARN": "\033[93m[WARN]\033[0m",
          "FAIL": "\033[91m[FAIL]\033[0m", "INFO": "\033[94m[INFO]\033[0m"}


def show(results):
    for level, text in results:
        print(f"  {COLOUR[level]} {text}")


def watch(m, mavutil, seconds):
    """Collect the readings judge_readings() takes, for `seconds`."""
    r = {"distance_m": [], "flow_quality": [], "local_z_m": [], "global_alt_m": [],
         "est_flags": []}
    for msg_id in STREAMS.values():
        m.mav.command_long_send(m.target_system, m.target_component,
                                mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                                msg_id, 100000, 0, 0, 0, 0, 0)
    end = time.time() + seconds
    next_beat = 0.0
    while time.time() < end:
        if time.time() >= next_beat:        # keep PX4 talking to us
            m.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS,
                                 mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            next_beat = time.time() + 1.0
        msg = m.recv_match(type=list(STREAMS), blocking=True, timeout=0.5)
        if msg is None:
            continue
        t = msg.get_type()
        if t == "DISTANCE_SENSOR":
            r["distance_m"].append(msg.current_distance / 100.0)
        elif t == "OPTICAL_FLOW_RAD":
            r["flow_quality"].append(msg.quality)
        elif t == "LOCAL_POSITION_NED":
            r["local_z_m"].append(msg.z)
        elif t == "GLOBAL_POSITION_INT":
            r["global_alt_m"].append(msg.relative_alt / 1000.0)
        elif t == "ESTIMATOR_STATUS":
            r["est_flags"].append(msg.flags)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", help="the Pixhawk's serial port (default: find it)")
    ap.add_argument("--seconds", type=float, default=WATCH_S,
                    help=f"how long to watch while you lift the drone (default {WATCH_S:g})")
    args = ap.parse_args()
    if args.seconds <= 0:
        ap.error("--seconds must be more than 0")

    if c2_running():
        print("venator-c2 holds the Pixhawk's port. Free it, then run this again:\n"
              "    sudo systemctl stop venator-c2\n"
              "and afterwards hand it back:\n"
              "    sudo systemctl start venator-c2")
        return 2

    # Imported here, not at the top, so the verdicts above import without
    # pymavlink. preflight_audit exits with a clear message if it is missing.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import preflight_audit as audit
    from pymavlink import mavutil

    dev = args.device or audit.find_fc()
    print(f"\nARK Flow check   {time.strftime('%F %H:%M:%S')}   {dev}")
    try:
        m = mavutil.mavlink_connection(dev, baud=115200)
    except Exception as exc:                 # no such port, or no permission
        print(f"  {COLOUR['FAIL']} can't open {dev}: {exc}\n"
              f"      Is the Pixhawk plugged in? (ls /dev/serial/by-id/)")
        return 2
    m.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                         0, 0, 0)
    hb = m.wait_heartbeat(timeout=12)
    if hb is None:
        print(f"  {COLOUR['FAIL']} no heartbeat from {dev}. Is venator-c2 still running?")
        return 2
    if hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
        print(f"  {COLOUR['FAIL']} the drone is ARMED. Disarm it; this check is for the bench")
        return 2

    try:
        print("\n== PX4 settings ==")
        params = [judge_param(name, audit.readp(m, name)) for name, *_ in PARAMS]
        show(params)

        print(f"\n== Live readings: lift the drone about 0.5 m now, hold it, put it down "
              f"({args.seconds:g} s) ==")
        readings = judge_readings(watch(m, mavutil, args.seconds), args.seconds)
        show(readings)
    except Exception as exc:                 # the USB link dropped, say
        print(f"  {COLOUR['FAIL']} lost the Pixhawk mid-check: {exc}")
        return 2

    results = params + readings
    print("\n---- send this to Claude ----")
    for level, text in results:
        print(f"{level:4s} {text}")
    print("-----------------------------")
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
