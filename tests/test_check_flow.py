#!/usr/bin/env python3
"""The verdicts the ARK Flow check prints, pinned without a Pixhawk.

drone/checks/check_flow.py is what decides whether the indoor hover can be
tried, so what it calls OK, WARN or FAIL matters more than how it talks to PX4.
Those verdicts are plain functions of plain numbers, and this feeds them the
readings a working sensor, a covered lens, a drone nobody lifted and a missing
setting would produce.

Stdlib only: the check imports pymavlink only when it really talks to PX4.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "drone" / "checks"))

import check_flow as cf  # noqa: E402

PASS = FAIL = 0


def check(label, got, want=True):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"    {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"   got {got!r}"))


def levels(results):
    return [level for level, _ in results]


def reading(results, name):
    """The verdict about one message, by the name its text starts with."""
    return next(r for r in results if r[1].startswith(name))


print("\nImporting the check needs no pymavlink")
check("pymavlink is not loaded by importing the verdicts", "pymavlink" in sys.modules, False)

print("\nPX4 settings")
check("UAVCAN_ENABLE 2 is right", cf.judge_param("UAVCAN_ENABLE", 2)[0], "OK")
check("UAVCAN_ENABLE 3 is right too", cf.judge_param("UAVCAN_ENABLE", 3)[0], "OK")
check("UAVCAN_ENABLE 0 fails: DroneCAN is off", cf.judge_param("UAVCAN_ENABLE", 0)[0], "FAIL")
for name in ("UAVCAN_SUB_FLOW", "UAVCAN_SUB_RNG", "EKF2_OF_CTRL"):
    check(f"{name} 1 is right", cf.judge_param(name, 1)[0], "OK")
    check(f"{name} 0 fails", cf.judge_param(name, 0)[0], "FAIL")
check("EKF2_RNG_CTRL 2 is right", cf.judge_param("EKF2_RNG_CTRL", 2)[0], "OK")
check("EKF2_HGT_REF 0 (baro) fails: the hover plan assumes range",
      cf.judge_param("EKF2_HGT_REF", 0)[0], "FAIL")
check("EKF2_GPS_CTRL left on only warns: there's no GPS to fuse anyway",
      cf.judge_param("EKF2_GPS_CTRL", 7)[0], "WARN")
check("a setting PX4 doesn't answer for fails, rather than crashing",
      cf.judge_param("EKF2_OF_CTRL", None)[0], "FAIL")
check("  naming the setting", "EKF2_OF_CTRL: no answer" in cf.judge_param("EKF2_OF_CTRL", None)[1])
check("an unanswered WARN-only setting only warns", cf.judge_param("COM_ARM_WO_GPS", None)[0],
      "WARN")
check("a reported-only setting is information, whatever it is",
      (cf.judge_param("SENS_FLOW_ROT", 6)[0], cf.judge_param("SENS_FLOW_ROT", None)[0]),
      ("INFO", "INFO"))
check("every setting in the list has a verdict",
      all(cf.judge_param(name, 1)[0] in ("OK", "WARN", "FAIL", "INFO")
          for name, *_ in cf.PARAMS))

print("\nLive readings: a working sensor, lifted by hand")
good = {"distance_m": [0.15, 0.16, 0.40, 0.62, 0.61, 0.30, 0.15],
        "flow_quality": [180, 200, 210, 190, 205],
        "local_z_m": [-0.1 - 0.5 * (i % 2) for i in range(150)],
        "global_alt_m": [],
        "est_flags": [cf.CONST_POS_MODE] * 20
                     + [cf.POS_HORIZ_REL | cf.POS_VERT_AGL] * 30}
results = cf.judge_readings(good, 15.0)
check("distance, flow, position and estimator all pass",
      [lv for lv in levels(results) if lv != "INFO"], ["OK", "OK", "OK", "OK"])
check("constant-position mode on the bench is fine once it leaves it while lifted",
      reading(results, "ESTIMATOR_STATUS")[0], "OK")
check("no GPS position indoors is information, not a failure",
      reading(results, "GLOBAL_POSITION_INT")[0], "INFO")
check("and it names the C2 server's altitude source",
      "C2 server" in reading(results, "GLOBAL_POSITION_INT")[1])
check("all of that exits 0", cf.exit_code(results), 0)

print("\nLive readings: what goes wrong")
flat = dict(good, distance_m=[0.15] * 50)
check("a drone nobody lifted warns, and asks for a lift",
      (reading(cf.judge_readings(flat, 15.0), "DISTANCE_SENSOR")[0],
       "Lift" in reading(cf.judge_readings(flat, 15.0), "DISTANCE_SENSOR")[1]), ("WARN", True))
check("no distance sensor fails",
      reading(cf.judge_readings(dict(good, distance_m=[]), 15.0), "DISTANCE_SENSOR")[0], "FAIL")
check("no optical flow fails",
      reading(cf.judge_readings(dict(good, flow_quality=[]), 15.0), "OPTICAL_FLOW_RAD")[0], "FAIL")
check("low flow quality warns: the floor needs texture",
      reading(cf.judge_readings(dict(good, flow_quality=[40, 60, 50]), 15.0),
              "OPTICAL_FLOW_RAD")[0], "WARN")
check("quality 0 fails: the lens sees nothing",
      reading(cf.judge_readings(dict(good, flow_quality=[0, 0, 0]), 15.0),
              "OPTICAL_FLOW_RAD")[0], "FAIL")
check("no local position fails",
      reading(cf.judge_readings(dict(good, local_z_m=[]), 15.0), "LOCAL_POSITION_NED")[0], "FAIL")
check("a slow local position warns",
      reading(cf.judge_readings(dict(good, local_z_m=[-0.1] * 30), 15.0),
              "LOCAL_POSITION_NED")[0], "WARN")
check("a height that ignores a lift the distance sensor saw warns",
      reading(cf.judge_readings(dict(good, local_z_m=[-0.1] * 150), 15.0),
              "LOCAL_POSITION_NED")[0], "WARN")
check("stuck in constant-position mode the whole time fails",
      reading(cf.judge_readings(dict(good, est_flags=[cf.CONST_POS_MODE] * 50), 15.0),
              "ESTIMATOR_STATUS")[0], "FAIL")
no_agl = cf.judge_readings(dict(good, est_flags=[cf.POS_HORIZ_REL] * 50), 15.0)
check("a position with no height above the ground fails", reading(no_agl, "ESTIMATOR_STATUS")[0],
      "FAIL")
check("  and says which is missing", "height above the ground" in reading(no_agl,
                                                                          "ESTIMATOR_STATUS")[1])
check("no ESTIMATOR_STATUS at all only warns",
      reading(cf.judge_readings(dict(good, est_flags=[]), 15.0), "ESTIMATOR_STATUS")[0], "WARN")
check("a GPS position, if there is one, is reported with its altitude",
      "0.10 to 0.60" in reading(cf.judge_readings(dict(good, global_alt_m=[0.1, 0.6]), 15.0),
                                "GLOBAL_POSITION_INT")[1])
check("nothing at all from PX4: distance, flow and position fail, the estimator warns",
      levels(cf.judge_readings({}, 15.0)), ["FAIL", "FAIL", "FAIL", "WARN", "INFO"])
check("any FAIL exits 1", cf.exit_code([("OK", "a"), ("FAIL", "b")]), 1)
check("WARNs alone exit 0", cf.exit_code([("WARN", "a"), ("INFO", "b")]), 0)
check("a zero-length watch can't divide by zero",
      levels(cf.judge_readings(dict(good, global_alt_m=[1.0]), 0.0))[-1], "INFO")


class Ran:
    def __init__(self, code):
        self.returncode = code


def no_systemd(*args, **kwargs):
    raise FileNotFoundError("systemctl")


print("\nIt won't fight venator-c2 for the port")
check("venator-c2 active: it refuses", cf.c2_running(lambda cmd: Ran(0)), True)
check("venator-c2 stopped: it goes ahead", cf.c2_running(lambda cmd: Ran(3)), False)
check("no systemd (a laptop): it goes ahead", cf.c2_running(no_systemd), False)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
