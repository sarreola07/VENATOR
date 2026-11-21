#!/usr/bin/env python3
"""
VENATOR - ARK Flow calibration, as a simple menu. Every check can be redone.

START: double-click "ARK calibration" on the Desktop, or in a terminal:

    bash ~/Desktop/VENATOR-flight/deploy/ark_calibration.sh

HOW IT WORKS: a menu lists every check and its result. Press Enter to do the
next thing, or type a check's number to do (or redo) it at any time - the
latest attempt counts, including a failed one. "A" writes the changes the
results support (only after you type YES for each, then reads them back). "V"
shows live readings. "Q" quits and saves a report. Ctrl+C or closing the
window also stops it. READY appears only when every row passes.

You need (everything is in INCHES): a tape measure taped upright to a wall
(zero at the floor); two tape marks on the floor exactly 36 in (3 ft) apart
(A and B); the RC on with the KILL SWITCH ON the whole time; a textured,
well-lit floor; the Pixhawk's USB cable plugged into the Jetson.

Safety: it reads the Pixhawk and changes nothing until you type YES in "A".
It never arms or sends a movement command, stops if the autopilot reports
ARMED, and refuses every hand-held check unless PX4 itself reads the kill
switch as engaged. Every cue is a big on-screen banner (the Jetson's audio
may be muted). Reports go to ~/.local/state/venator/ark-calibration-<time>.json.

Offline (no vehicle):
    ./venv/bin/python drone/ark_calibrate.py --self-test
    ./venv/bin/python drone/ark_calibrate.py --analyze FILE.json --before A B --after C D [--sideways] [--rot N]
"""
import argparse
import json
import math
import os
import select
import statistics as st
import struct
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "checks"))

REPORT_DIR = Path.home() / ".local" / "state" / "venator"

# PX4 SENS_FLOW_ROT (enum Rotation): pure yaw rotations in 45-degree steps.
# PX4 v1.17 parameter reference: "Zero rotation is defined as X on flow board
# pointing towards front of vehicle." ARK Flow guide: connectors toward the
# BACK of the vehicle = 0. So the board's X points away from its connectors:
#   connectors left  -> X points to the drone's right -> yaw  90 -> 2
#   connectors right -> X points to the drone's left  -> yaw 270 -> 6
ROT_DEG = {0: 0, 1: 45, 2: 90, 3: 135, 4: 180, 5: 225, 6: 270, 7: 315}
CONNECTORS = {"b": (0, "the tail (back)"), "l": (2, "the drone's left"), "f": (4, "the nose (front)"),
              "r": (6, "the drone's right")}
# ESTIMATOR_STATUS flags. The server's --indoor gate needs POS_HORIZ_REL and POS_VERT_AGL.
FLAG_HORIZ, FLAG_AGL, FLAG_CONST = 8, 64, 128

WALK_MIN_M = 0.5          # a walk shorter than this (PX4 position) cannot judge direction
WALK_START_M = 0.25       # distance from the hold point that means "walking"
HEADING_SPREAD_MAX = 20.0 # the heading must stay within this while walking (deg)
ROT_TOL_DEG = 20.0        # direction pass band (< the 22.5-degree half-step)
HEIGHT_TOL_M = 0.03       # rangefinder vs tape: max(3 cm, 5 %)
HEIGHT_TOL_FRAC = 0.05
TRACK_TOL_M = 0.10        # PX4 height change vs rangefinder change between two points
MIN_RNG_TOL = 0.03        # EKF2_MIN_RNG vs the tape floor distance
STILL_FLOOR = 0.08        # m/s: the drone sitting on the floor
STILL_HAND = 0.15         # m/s: a hand-held hold (bench: 0.04-0.13 m/s when "still")
RANGE_STABLE_TOL = 0.015  # m: +/- spread of the range for a hand-held height hold
RANGE_MIN_VALID = 0.08    # m: the AFBR-S50's minimum range

# The operator works in inches; PX4 and all maths stay in metres.
IN = 0.0254               # m per inch
HEIGHTS_IN = (20, 40)     # the two height holds, inches on the wall tape
HEIGHT_TARGET_TOL_IN = 3  # a typed hold height this far from the row's target is questioned
FLOOR_MAX_PLAUSIBLE_IN = 8
WALK_TAPE_IN = 36         # floor marks A and B are 36 in (3 ft) apart


def inch(m, nd=1):
    """Metres -> a short inches string, e.g. 0.1016 -> '4.0 in'."""
    return "--" if m is None else f"{m / IN:.{nd}f} in"


# ----------------------------------------------------------------------------
# Pure analysis (testable offline)
# ----------------------------------------------------------------------------
def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def circ_mean_deg(angles_rad):
    s = sum(math.sin(a) for a in angles_rad)
    c = sum(math.cos(a) for a in angles_rad)
    return math.degrees(math.atan2(s, c))


def _median_xy(pos, a, b):
    sel = [p for p in pos if a <= p[0] <= b]
    if not sel:
        return None
    return st.median(p[1] for p in sel), st.median(p[2] for p in sel)


def analyze_walk(rec, before, after, expect_offset_deg=0.0):
    """Displacement between two still windows, compared with the heading while moving.

    rec: {"pos": [(t, x, y, z, vxy)], "yaw": [(t, rad)], "flags": [(t, f)]} from
    LOCAL_POSITION_NED / ATTITUDE / ESTIMATOR_STATUS. expect_offset_deg: 0 for a walk
    toward the nose, +90 for a walk toward the right side. error_deg is the measured
    bearing minus the expected one, clockwise positive.
    """
    p0 = _median_xy(rec["pos"], *before)
    p1 = _median_xy(rec["pos"], *after)
    yaws = [y for t, y in rec["yaw"] if before[1] <= t <= after[0]]
    if p0 is None or p1 is None or not yaws:
        return None
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    heading = circ_mean_deg(yaws)
    spread = max(abs(wrap180(math.degrees(y) - heading)) for y in yaws)
    bearing = math.degrees(math.atan2(dy, dx))
    # Judge flow fusion only while MOVING: when the drone is held still, PX4 v1.17 sets the
    # constant-position bit (at-rest aiding) even though flow is fused (bench 2026-11-21:
    # flags 495 in the still holds, 367 = position + AGL, no const-pos, while walking).
    moving = [p[0] for p in rec["pos"] if before[1] <= p[0] <= after[0] and p[4] > STILL_HAND]
    # PX4's at-rest bit takes about a second to clear once motion starts (bench: 495 at t=312,
    # 367 from t=313), so skip the first second of motion when there is enough walk left.
    t_from = moving[0] + 1.0 if moving and moving[-1] - moving[0] > 2.0 else (moving[0] if moving else 0)
    fl = [f for t, f in rec.get("flags", [])
          if moving and t_from <= t <= moving[-1]
          and min(abs(t - m) for m in moving) <= 0.3]
    fused = None
    if fl:  # flow is the only horizontal aiding: it must be fused throughout the walk
        fused = all((f & FLAG_HORIZ) and (f & FLAG_AGL) and not (f & FLAG_CONST) for f in fl)
    return {
        "dx_m": round(dx, 3), "dy_m": round(dy, 3), "distance_m": round(math.hypot(dx, dy), 3),
        "bearing_deg": round(bearing, 1), "heading_deg": round(heading, 1),
        "heading_spread_deg": round(spread, 1), "expect_offset_deg": expect_offset_deg,
        "error_deg": round(wrap180(bearing - (heading + expect_offset_deg)), 1),
        "flow_fused": fused, "before": list(before), "after": list(after),
    }


def walk_usable(w):
    return (w is not None and not w.get("failed") and w["distance_m"] >= WALK_MIN_M
            and w["heading_spread_deg"] <= HEADING_SPREAD_MAX and w.get("flow_fused") is not False)


def walk_problem(w):
    if w is None:
        return "no data"
    if w.get("failed"):
        return w["text"]
    if w["distance_m"] < WALK_MIN_M:
        return f"PX4 saw only {inch(w['distance_m'], 0)} of movement (needs {inch(WALK_MIN_M, 0)})"
    if w["heading_spread_deg"] > HEADING_SPREAD_MAX:
        return f"the drone turned {w['heading_spread_deg']:.0f} deg while walking"
    if w.get("flow_fused") is False:
        return "PX4 was not using the flow during the walk"
    return None


def walk_flow_problem(w):
    """True when a walk failed in a way that is evidence about the flow itself (not handling)."""
    if w is None:
        return False
    if w.get("failed"):
        return "never moved" in w["text"] or "not using the flow" in w["text"]
    return w.get("flow_fused") is False


def needed_rotation(current_enum, error_deg):
    """PX4 rotates the board's flow by SENS_FLOW_ROT into the body frame (v_body = Rz(s) v_board).

    With the board really yawed by psi and SENS_FLOW_ROT = s, a body-frame motion shows up
    rotated by (s - psi), so a measured error e means psi = s - e. Returns the nearest
    45-degree enum, the exact psi, and the residual (deg)."""
    if current_enum not in ROT_DEG:
        raise ValueError(f"SENS_FLOW_ROT {current_enum!r} is not a yaw-only value 0-7")
    psi = (ROT_DEG[current_enum] - error_deg) % 360.0
    enum = int(round(psi / 45.0)) % 8
    return enum, round(psi, 1), round(wrap180(psi - ROT_DEG[enum]), 1)


def decide_rotation(walks, current_rot, predicted_rot):
    """Return (enum, why) when the evidence is consistent, else (None, why)."""
    usable = [w for w in walks.values() if walk_usable(w)]
    if not usable:
        return None, "no usable walk yet"
    if predicted_rot is None and len(usable) < 2:
        return None, "with the connector direction unknown, both walks must succeed and agree"
    needs = [(w, needed_rotation(w.get("rot_in_effect", current_rot), w["error_deg"])) for w in usable]
    for w, (enum, psi, resid) in needs:
        if abs(resid) > ROT_TOL_DEG:
            return None, (f"the {w['kind']} walk measures the sensor at {psi:.0f} deg, not near a 45-degree "
                          "step: redo it, straight and without turning the drone")
    enums = {n[0] for _, n in needs}
    if len(enums) > 1:
        return None, ("the walks disagree (" + ", ".join(f"{w['kind']} {w['error_deg']:+.0f} deg"
                                                         for w, _ in needs) + "): redo them")
    enum = needs[0][1][0]
    if ROT_DEG[enum] % 90 and predicted_rot is None:
        return None, f"the walks point to a diagonal mounting ({ROT_DEG[enum]} deg): check the board by eye"
    if predicted_rot is not None and predicted_rot != enum:
        return None, (f"the walks say SENS_FLOW_ROT {enum} but your connector answer says {predicted_rot}: "
                      "redo check 2 standing behind the drone, or redo the walks")
    return enum, f"SENS_FLOW_ROT {enum} ({ROT_DEG[enum]} deg)"


def height_tracking(points):
    """points: [(label, range_m, ekf_height_m)] in order. PX4's height must change as the
    rangefinder does between consecutive points. Returns (ok, [(a, b, mismatch_m)])."""
    pairs = []
    for (la, ra, ha), (lb, rb, hb) in zip(points, points[1:]):
        pairs.append((la, lb, round(abs((rb - ra) - (hb - ha)), 3)))
    return bool(pairs) and all(m <= TRACK_TOL_M for _, _, m in pairs), pairs


def px4_rotate_yaw(enum, x, y):
    """PX4's rotate_3f for the yaw-only rotations (src/lib/conversion/rotation.cpp)."""
    a = math.radians(ROT_DEG[enum])
    return x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)


def rc_normalized(v, mn, trim, mx, rev, dz=0.0):
    """PX4 rc_update's channel scaling: raw us -> [-1, 1], with reverse."""
    if v is None or mn is None or trim is None or mx is None:
        return None
    if v > trim + dz and mx - trim - dz > 0:
        n = (v - trim - dz) / (mx - trim - dz)
    elif v < trim - dz and trim - mn - dz > 0:
        n = (v - trim + dz) / (trim - mn - dz)
    else:
        n = 0.0
    n *= (rev if rev else 1.0)
    return max(-1.0, min(1.0, n))


def switch_on(v, mn, trim, mx, rev, threshold):
    """PX4 rc_update getRCSwitchOnOffPosition (v1.17.0 rc_update.cpp:522-531): True when ON."""
    n = rc_normalized(v, mn, trim, mx, rev)
    if n is None or threshold is None:
        return None
    value = 0.5 * n + 0.5
    return value < -threshold if threshold < 0 else value > threshold


def floor_target(tape_m):
    """One rounding rule for EKF2_MIN_RNG, used by both the floor row and the proposal."""
    return round(max(0.01, tape_m), 2)


def load_samples(path):
    """Read a saved recording: this program's report, or the bench recorder's samples file."""
    d = json.load(open(path))
    if "samples" in d:
        d = d["samples"]
    if "pos_t_x_y_z_vxy" in d:
        return {"pos": d["pos_t_x_y_z_vxy"], "yaw": d["yaw_t_rad"], "flags": d.get("flags_t", []),
                "flowq": d.get("flowq_t", []), "range": d.get("range_t_m", [])}
    return d


# ----------------------------------------------------------------------------
# Check status (pure: from the latest results and the parameters in effect)
# ----------------------------------------------------------------------------
STEPS = [("1", "sensors", "Sensors streaming"), ("2", "connectors", "Connector direction"),
         ("3", "floor", "Floor height + RUN 8 gate"), ("4", "h20", f"Rangefinder at {HEIGHTS_IN[0]} in"),
         ("5", "h40", f"Rangefinder at {HEIGHTS_IN[1]} in"), ("6", "forward", "Forward walk"),
         ("7", "sideways", "Sideways walk"), ("8", "rc", "RC kill + mode switch")]
TITLES = {k: t for _, k, t in STEPS}
TITLES.update({"tracking": "PX4 height follows", "direction": "Flow direction", "gate": "RUN 8 position gate"})


def predicted_rot(latest):
    c = latest.get("connectors")
    return c.get("predicted_rot") if c else None


def fresh_walks(latest, rot_now):
    """Walks recorded with the SENS_FLOW_ROT now in effect (older ones must be redone)."""
    return {k: latest[k] for k in ("forward", "sideways")
            if latest.get(k) is not None and not latest[k].get("failed")
            and latest[k].get("rot_in_effect") == rot_now}


def tracking(latest):
    pts = []
    f = latest.get("floor")
    if f and not f.get("failed") and f.get("range_m") is not None and f.get("ekf_height_m") is not None:
        pts.append(("floor", max(f["range_m"], f["tape_m"]), f["ekf_height_m"]))
    for k in ("h20", "h40"):
        h = latest.get(k)
        if h and not h.get("failed") and h.get("range_m") is not None:
            pts.append((TITLES[k].replace("Rangefinder at ", ""), h["range_m"], h["ekf_height_m"]))
    if len(pts) < 2 or not any(p[0] != "floor" for p in pts):
        return None, []
    return height_tracking(pts)


def status_of(key, latest, params):
    """(state, text): state is OK, FAIL, REDO, --, or opt."""
    r = latest.get(key)
    rot_now = params["SENS_FLOW_ROT"]
    if r is not None and r.get("failed") and key not in ("forward", "sideways"):
        return "FAIL", r["text"]
    if key in ("sensors", "rc"):
        if not r:
            return "--", "not done"
        return ("OK" if r["ok"] else "FAIL"), r["text"]
    if key == "connectors":
        if not r:
            return "--", "not done"
        if r["predicted_rot"] is None:
            return "opt", "unsure (both walks will be needed)"
        return "OK", f"{r['word']} -> SENS_FLOW_ROT {r['predicted_rot']}"
    if key == "floor":
        if not r:
            return "--", "not done"
        target = floor_target(r["tape_m"])
        ok = params["EKF2_MIN_RNG"] is not None and abs(params["EKF2_MIN_RNG"] - target) <= MIN_RNG_TOL + 1e-9
        txt = (f"lens {inch(r['tape_m'])}, sensor {inch(r['range_m'])}; "
               f"EKF2_MIN_RNG {params['EKF2_MIN_RNG']} m ({inch(params['EKF2_MIN_RNG'])})")
        return ("OK", txt) if ok else ("FAIL", txt + f" (should be {target} m: use A)")
    if key in ("h20", "h40"):
        if not r:
            return "--", "not done"
        txt = f"sensor {inch(r['range_m'])} vs tape {inch(r['tape_m'])}"
        return ("OK" if r["ok"] else "FAIL"), txt
    if key in ("forward", "sideways"):
        optional = key == "sideways" and predicted_rot(latest) is not None
        if not r:
            return ("opt" if optional else "--"), ("optional (not needed when check 2 is answered)"
                                                   if optional else "not done")
        if r.get("failed"):
            return "FAIL", r["text"]
        if r.get("rot_in_effect") != rot_now:
            return "REDO", f"recorded with SENS_FLOW_ROT {r.get('rot_in_effect')}; now {rot_now}"
        prob = walk_problem(r)
        if prob:
            return "FAIL", prob
        ok = abs(r["error_deg"]) <= ROT_TOL_DEG
        return ("OK" if ok else "FAIL"), f"direction error {r['error_deg']:+.0f} deg"
    raise KeyError(key)


def derived(latest, params):
    """The checks computed from the others."""
    t_ok, pairs = tracking(latest)
    if t_ok is None:
        track = ("--", "needs check 3 and at least one of 4/5")
    elif t_ok:
        track = ("OK", "PX4 height moves with the rangefinder")
    else:
        worst = max(m for _, _, m in pairs)
        track = ("FAIL", f"PX4 height drifts {inch(worst, 0)} from the rangefinder: quit, power-cycle, redo")
    rot_now = params["SENS_FLOW_ROT"]
    enum, why = decide_rotation(fresh_walks(latest, rot_now), rot_now, predicted_rot(latest))
    if enum is None:
        direction = ("--" if why == "no usable walk yet" else "FAIL", why)
    elif enum == rot_now:
        direction = ("OK", f"confirmed {why}")
    else:
        direction = ("FAIL", f"the walks say {why}: use A to write it, then redo the forward walk")
    f = latest.get("floor")
    if not f or f.get("failed") or f.get("gate_ok") is None:
        gate = ("--", "measured in check 3")
    elif f["gate_ok"]:
        gate = ("OK", "PX4 reports position + height above ground on the floor (RUN 8 would be allowed)")
    else:
        gate = ("FAIL", "PX4 does not report " + " and ".join(f["gate_missing"]) +
                " on the floor: RUN 8 would be refused")
    return {"tracking": track, "direction": direction, "gate": gate}


def readiness(latest, params):
    """READY only when every row passes (optional rows may be 'opt', never FAIL)."""
    missing = []
    for _, key, _ in STEPS:
        s = status_of(key, latest, params)[0]
        if key == "connectors":
            ok = s == "OK" or (s == "opt" and status_of("sideways", latest, params)[0] == "OK")
        elif key == "sideways":
            # optional once check 2 is answered: a handling slip (turned, too short) does not
            # block READY, but evidence that the flow dropped out always does
            r = latest.get("sideways")
            ok = s in ("OK", "opt") or (predicted_rot(latest) is not None and s == "FAIL"
                                        and not walk_flow_problem(r))
        else:
            ok = s == "OK"
        if not ok:
            missing.append(TITLES[key])
    d = derived(latest, params)
    missing += [TITLES[k] for k in ("tracking", "direction", "gate") if d[k][0] != "OK"]
    return not missing, missing


def proposals(latest, params):
    """The parameter changes the latest results support: [(name, value, type, why, optional)]."""
    out = []
    rot_now = params["SENS_FLOW_ROT"]
    enum, why = decide_rotation(fresh_walks(latest, rot_now), rot_now, predicted_rot(latest))
    if enum is not None and enum != rot_now:
        out.append(("SENS_FLOW_ROT", enum, "INT32", f"the walks measure {why}", False))
    f = latest.get("floor")
    if f and not f.get("failed"):
        target = floor_target(f["tape_m"])
        if params["EKF2_MIN_RNG"] is None or abs(params["EKF2_MIN_RNG"] - target) > MIN_RNG_TOL + 1e-9:
            out.append(("EKF2_MIN_RNG", target, "FLOAT", f"the lens sits {inch(f['tape_m'])} above the floor", False))
    for a in "XYZ":
        o, r = params.get(f"EKF2_OF_POS_{a}"), params.get(f"EKF2_RNG_POS_{a}")
        if o is not None and r is not None and abs(o - r) > 0.01:
            out.append((f"EKF2_OF_POS_{a}", round(r, 3), "FLOAT", "optional: same ARK board as the rangefinder", True))
    return out


def next_step(latest, params):
    if any(not opt for *_, opt in proposals(latest, params)):
        return "a"      # a pending change is what fixes the failing row
    for num, key, _ in STEPS:
        s = status_of(key, latest, params)[0]
        if key == "connectors":
            if s == "--":
                return num
            continue
        if s in ("--", "FAIL", "REDO"):
            if key == "sideways" and predicted_rot(latest) is not None and s == "--":
                continue
            return num
    rot_now = params["SENS_FLOW_ROT"]
    enum, why = decide_rotation(fresh_walks(latest, rot_now), rot_now, predicted_rot(latest))
    if enum is None and "connector answer" in why:
        return "2"      # the walks and the connector answer disagree: re-check by eye first
    return "q"


# ----------------------------------------------------------------------------
# Terminal helpers
# ----------------------------------------------------------------------------
def say(msg=""):
    try:
        print(msg, flush=True)
    except OSError:  # the terminal window was closed
        pass


def clear():
    say("\033[2J\033[H")


def bell():
    try:
        print("\a", end="", flush=True)
    except OSError:
        pass


def banner(*lines):
    """A cue you cannot miss with your hands full: big text, plus a beep if audio is on."""
    bell()
    w = 70
    say("")
    say("#" * w)
    for line in lines:
        say("####  " + line.ljust(w - 10) + "####")
    say("#" * w)
    say("")


def ask_yes_no(prompt, default=False):
    d = "Y/n" if default else "y/N"
    while True:
        a = input(f"{prompt} [{d}] ").strip().lower()
        if not a:
            return default
        if a in ("y", "yes"):
            return True
        if a in ("n", "no"):
            return False


def ask_number(prompt, default=None, lo=None, hi=None):
    while True:
        s = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
        if not s and default is not None:
            return float(default)
        try:
            v = float(s)
        except ValueError:
            say("  Please type a number.")
            continue
        if not math.isfinite(v):
            say("  Please type a number.")
            continue
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            say(f"  Please type a value between {lo} and {hi}.")
            continue
        return v


def drain_stdin():
    """Drop key presses typed ahead (e.g. a double-tapped Enter) so they can't cancel the next wait."""
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


def enter_pressed():
    """True if the operator pressed Enter (used to cancel a wait)."""
    try:
        if select.select([sys.stdin], [], [], 0)[0]:
            sys.stdin.readline()
            return True
    except (OSError, ValueError):
        pass
    return False


def fail(msg):
    """A check that ran but did not succeed: shown as FAIL, and it replaces the old result."""
    say(f"  {msg}")
    return {"failed": True, "text": msg}


# ----------------------------------------------------------------------------
# Pixhawk link
# ----------------------------------------------------------------------------
class Armed(Exception):
    def __init__(self, detail=None):
        super().__init__("armed")
        self.detail = detail or {}


class Cancelled(Exception):
    pass


def interlock(dev):
    """Never share the Pixhawk port with the live C2 server: a second reader splits its bytes."""
    if subprocess.run(["systemctl", "is-active", "--quiet", "venator-c2"]).returncode == 0:
        sys.exit("venator-c2 is running. Stop it first:\n\n    sudo systemctl stop venator-c2\n")
    real = os.path.realpath(dev)
    unreadable = 0
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) == os.getpid():
            continue
        try:
            if any(os.path.realpath(f"/proc/{pid}/fd/{fd}") == real
                   for fd in os.listdir(f"/proc/{pid}/fd")):
                sys.exit(f"{real} is in use by process {pid}. Close it first.")
        except PermissionError:
            unreadable += 1
        except OSError:
            continue
    return unreadable


class Link:
    # LPOS, ATTITUDE, EST_STATUS, FLOW_RAD, DIST, RC_CHANNELS
    STREAMS = {32: 10, 30: 10, 230: 5, 106: 10, 132: 10, 65: 5}
    kill_ch = None   # RC_MAP_KILL_SW, set once the parameters are read
    mode_ch = None   # RC_MAP_FLTMODE
    kill_cal = None  # (min, trim, max, rev, threshold) of the kill channel, PX4's own values

    def __init__(self, dev):
        from pymavlink import mavutil
        self.M = mavutil.mavlink
        self.m = mavutil.mavlink_connection(dev, baud=115200)
        self.m.mav.heartbeat_send(self.M.MAV_TYPE_GCS, self.M.MAV_AUTOPILOT_INVALID, 0, 0, 0)
        self.t0 = time.monotonic()
        self.rec = {"pos": [], "yaw": [], "flags": [], "flowq": [], "range": [], "rc": []}
        self._last_print = 0.0
        self.ap_comp = None
        self.armed = None
        self.last_ap_hb = None
        end = time.monotonic() + 20      # a Pixhawk plugged in just now needs a few seconds to boot
        while time.monotonic() < end and self.ap_comp is None:
            hb = self.m.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
            if hb is not None and hb.autopilot != self.M.MAV_AUTOPILOT_INVALID and hb.type != self.M.MAV_TYPE_GCS:
                self.m.target_system = hb.get_srcSystem()
                self.m.target_component = self.ap_comp = hb.get_srcComponent()
                self.armed = bool(hb.base_mode & self.M.MAV_MODE_FLAG_SAFETY_ARMED)
                self.last_ap_hb = self.now()
        if self.ap_comp is None:
            sys.exit("No heartbeat from the autopilot (USB cable? powered?).")

    def now(self):
        return time.monotonic() - self.t0

    def set_rates(self, restore=False):
        for mid, hz in self.STREAMS.items():
            self.m.mav.command_long_send(self.m.target_system, self.m.target_component,
                                         self.M.MAV_CMD_SET_MESSAGE_INTERVAL, 0, mid,
                                         0 if restore else int(1e6 / hz), 0, 0, 0, 0, 0)
            time.sleep(0.05)

    def close(self):
        try:
            self.set_rates(restore=True)
        finally:
            self.m.close()

    def flush(self, settle=0.6):
        """Drop whatever queued while we waited on the keyboard, then read fresh data."""
        try:
            self.m.port.reset_input_buffer()
        except Exception:
            pass
        self.run_for(settle)

    def _autopilot_hb(self, msg):
        return (msg.get_type() == "HEARTBEAT" and msg.get_srcSystem() == self.m.target_system
                and msg.get_srcComponent() == self.ap_comp and msg.autopilot != self.M.MAV_AUTOPILOT_INVALID)

    def _take_hb(self, msg):
        self.armed = bool(msg.base_mode & self.M.MAV_MODE_FLAG_SAFETY_ARMED)
        self.last_ap_hb = self.now()
        if self.armed:
            raise Armed({"t": round(self.now(), 1), "base_mode": msg.base_mode,
                         "custom_mode": msg.custom_mode, "system_status": msg.system_status,
                         "rc_last": self.rec["rc"][-1] if self.rec["rc"] else None})

    def pump(self, timeout=0.2):
        """Read one message, store it, and stop the program if the autopilot reports ARMED."""
        msg = self.m.recv_match(blocking=True, timeout=timeout)
        if msg is None:
            return None
        k, t = msg.get_type(), self.now()
        if k == "LOCAL_POSITION_NED":
            self.rec["pos"].append((t, msg.x, msg.y, msg.z, math.hypot(msg.vx, msg.vy)))
        elif k == "ATTITUDE":
            self.rec["yaw"].append((t, msg.yaw))
        elif k == "ESTIMATOR_STATUS":
            self.rec["flags"].append((t, msg.flags))
        elif k == "OPTICAL_FLOW_RAD":
            self.rec["flowq"].append((t, msg.quality))
        elif k == "DISTANCE_SENSOR":
            self.rec["range"].append((t, msg.current_distance / 100.0))
        elif k == "RC_CHANNELS":
            self.rec["rc"].append((t, msg.chancount, msg.rssi,
                                   [getattr(msg, f"chan{i}_raw") for i in range(1, 19)]))
        elif self._autopilot_hb(msg):
            self._take_hb(msg)
        return msg

    def rc_pwm(self, ch, window=1.0):
        r = self.recent("rc", window)
        if not r or not ch or not (1 <= ch <= 18):
            return None
        v = r[-1][3][ch - 1]
        return None if v in (0, 65535) else v

    def kill_engaged(self):
        """PX4's own view of the kill switch from the live channel value: True, False or None."""
        if not self.kill_ch or not self.kill_cal:
            return None
        return switch_on(self.rc_pwm(self.kill_ch), *self.kill_cal)

    def require_disarmed(self, timeout=5.0):
        """Fail closed: wait for a heartbeat from the autopilot that is newer than this call."""
        try:
            self.m.port.reset_input_buffer()
        except Exception:
            pass
        start = self.now()
        while self.now() - start < timeout:
            self.pump(0.3)
            if self.last_ap_hb is not None and self.last_ap_hb > start:
                return True  # _take_hb raised Armed if it was armed
        raise RuntimeError("no heartbeat from the autopilot for 5 s: refusing to continue")

    def run_for(self, seconds, live=False):
        end = self.now() + seconds
        while self.now() < end:
            self.pump(0.2)
            self._maybe_print(live)

    # recent-sample helpers
    def recent(self, key, window):
        t = self.now()
        return [s for s in self.rec[key] if s[0] >= t - window]

    def still(self, thr, window=0.6):
        p = self.recent("pos", window)
        return len(p) >= 3 and all(s[4] < thr for s in p)

    def xy_now(self, window=0.4):
        p = self.recent("pos", window)
        if not p:
            return None
        return st.median(s[1] for s in p), st.median(s[2] for s in p)

    def range_now(self, window=0.6):
        r = self.recent("range", window)
        return st.median(s[1] for s in r) if r else None

    def range_stable(self, window=1.5, tol=RANGE_STABLE_TOL):
        r = [s[1] for s in self.recent("range", window)]
        return len(r) >= 6 and (max(r) - min(r)) <= 2 * tol

    def status_line(self):
        r = self.range_now()
        p = self.recent("pos", 0.6)
        q = self.recent("flowq", 0.6)
        y = self.recent("yaw", 0.6)
        f = self.recent("flags", 1.5)
        k = self.kill_engaged()
        return ("    range " + inch(r) +
                " | PX4 height " + (inch(-p[-1][3]) if p else "--") +
                " | flow q " + (f"{q[-1][1]}" if q else "--") +
                " | heading " + (f"{math.degrees(y[-1][1]):.0f}" if y else "--") +
                " | speed " + (f"{p[-1][4]:.2f}" if p else "--") +
                (" | NO-FLOW" if f and f[-1][1] & FLAG_CONST else "") +
                (" | no-AGL" if f and not f[-1][1] & FLAG_AGL else "") +
                (" | KILL ON" if k else " | KILL OFF!" if k is False else ""))

    def _maybe_print(self, live):
        if live and self.now() - self._last_print >= 1.0:
            self._last_print = self.now()
            say(self.status_line())

    def wait_until(self, cond, hold_s, max_s, live=True):
        """Pump until cond() has held for hold_s. Returns (t_start, t_end), or None on timeout.
        Pressing Enter cancels (raises Cancelled)."""
        start, since = self.now(), None
        while self.now() - start < max_s:
            self.pump(0.2)
            self._maybe_print(live)
            if enter_pressed():
                raise Cancelled()
            t = self.now()
            if cond():
                since = t if since is None else since
                if t - since >= hold_s:
                    return (since, t)
            else:
                since = None
        return None

    def countdown(self, seconds, what):
        self.flush()
        for i in range(seconds, 0, -1):
            say(f"  {what} in {i} ...")
            self.run_for(1.0)
        drain_stdin()

    # parameters
    def _decode(self, p):
        ints = (self.M.MAV_PARAM_TYPE_INT8, self.M.MAV_PARAM_TYPE_UINT8, self.M.MAV_PARAM_TYPE_INT16,
                self.M.MAV_PARAM_TYPE_UINT16, self.M.MAV_PARAM_TYPE_INT32, self.M.MAV_PARAM_TYPE_UINT32)
        if p.param_type in ints:  # PX4 sends integers bytewise inside the float
            return struct.unpack("<i", struct.pack("<f", p.param_value))[0], "INT32"
        return round(float(p.param_value), 6), "FLOAT"

    def _wait_param(self, name, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            msg = self.m.recv_match(type=["PARAM_VALUE", "HEARTBEAT"], blocking=True, timeout=0.5)
            if msg is None:
                continue
            if msg.get_type() == "HEARTBEAT":
                if self._autopilot_hb(msg):
                    self._take_hb(msg)
                continue
            if msg.param_id.strip("\x00") == name:
                return self._decode(msg)
        return None

    def read_param(self, name, tries=3):
        for _ in range(tries):
            self.m.mav.param_request_read_send(self.m.target_system, self.m.target_component,
                                               name.encode(), -1)
            got = self._wait_param(name, 2.0)
            if got is not None:
                return got
        return None, None

    def write_param(self, name, value, ptype):
        """Write one parameter with PX4's encoding, then read it back. Returns the read-back value."""
        if ptype == "INT32":
            wire = struct.unpack("<f", struct.pack("<i", int(value)))[0]
            mtype = self.M.MAV_PARAM_TYPE_INT32
        else:
            wire = float(value)
            mtype = self.M.MAV_PARAM_TYPE_REAL32
        self.m.mav.param_set_send(self.m.target_system, self.m.target_component,
                                  name.encode(), wire, mtype)
        got = self._wait_param(name, 3.0)
        if got is None:
            got = self.read_param(name)
        return got[0]


# ----------------------------------------------------------------------------
# The checks: each one is a single attempt. A result replaces the old one;
# a failure returns fail(...) so it replaces it too. Only a cancel keeps it.
# ----------------------------------------------------------------------------
HANDLING = ("floor", "h20", "h40", "forward", "sideways")


def require_kill(link):
    """Hand-held checks only start when PX4 itself reads the kill switch as engaged."""
    link.flush()
    k = link.kill_engaged()
    if k is True:
        return None
    if k is False:
        return fail("PX4 reads the KILL SWITCH as OFF. Switch it ON (engaged) before touching the drone.")
    return fail("Can't read the kill switch from the RC (is the RC transmitter on?). Not starting.")


def check_sensors(link):
    say("  Leave the drone sitting still on the floor. Measuring for 5 s ...")
    link.flush()
    link.run_for(5.0, live=True)
    rng, flw, pos = link.recent("range", 4.0), link.recent("flowq", 4.0), link.recent("pos", 4.0)
    q = int(st.median(v for _, v in flw)) if flw else None
    r = {"range_hz": round(len(rng) / 4.0, 1), "flow_hz": round(len(flw) / 4.0, 1),
         "lpos_hz": round(len(pos) / 4.0, 1), "flow_q": q,
         "range_m": round(st.median(v for _, v in rng), 3) if rng else None}
    problems = []
    if not rng:
        problems.append("NO rangefinder data: quit, power-cycle (battery out 10 s), run again")
    if not flw:
        problems.append("NO optical-flow data: check the ARK's CAN cable and LED, power-cycle")
    if not pos:
        problems.append("NO position from PX4")
    r["ok"] = not problems
    r["text"] = ("; ".join(problems) if problems else
                 f"rangefinder {r['range_hz']}/s, flow {r['flow_hz']}/s, quality {q}"
                 + ("  (low: add light or texture)" if q is not None and q < 100 else ""))
    return r


def check_connectors(link, params):
    say("  Keep the drone upright and stand BEHIND it, nose pointing away from you.")
    say("  Bend down and look at the ARK Flow board underneath (don't turn the drone over).")
    say("  Its two CAN connectors are on one edge. Which way do they point?")
    while True:
        a = input("  [b] toward the tail   [f] toward the nose   [l] to your left   [r] to your right"
                  "   [u] not sure : ").strip().lower()
        if a in ("b", "f", "l", "r", "u"):
            break
    if a == "u":
        return {"answer": "u", "predicted_rot": None, "word": "unsure"}
    rot, word = CONNECTORS[a]
    return {"answer": a, "predicted_rot": rot, "word": word}


def check_floor(link):
    say("  Put the drone on the floor where it will take off. Hands off.")
    input("  Press Enter when it is sitting still (Enter again later cancels) ...")
    link.flush()
    drain_stdin()
    hold = link.wait_until(lambda: link.still(STILL_FLOOR), hold_s=3.0, max_s=30.0)
    if not hold:
        return fail("It never sat still for 3 s.")
    a, b = hold
    rng = [r for t, r in link.rec["range"] if a <= t <= b]
    hz = [-p[3] for p in link.rec["pos"] if a <= p[0] <= b]
    fl = [f for t, f in link.rec["flags"] if a <= t <= b]
    floor_r = st.median(rng) if rng else None
    missing = []
    if fl and not all(f & FLAG_HORIZ for f in fl):
        missing.append("a position")
    if fl and not all(f & FLAG_AGL for f in fl):
        missing.append("height above ground")
    gate_ok = bool(fl) and not missing
    say("  Rangefinder on the floor: " + (inch(floor_r) if floor_r is not None else "no reading"))
    say("  RUN 8 position gate on the floor: " + ("PASS" if gate_ok else
                                                 "FAIL (PX4 reports no " + " and no ".join(missing or ["status"]) + ")"))
    say("  Now measure from the ARK's lens (the small window on its underside) straight down to the floor.")
    while True:
        tape = ask_number("  Lens-to-floor distance in INCHES (e.g. 4 or 3.5)", lo=0.5, hi=16) * IN
        near = floor_r is not None and floor_r < RANGE_MIN_VALID   # the sensor under-reads this close
        far = floor_r is not None and abs(floor_r - tape) > (3 * IN if near else 0.03)
        if tape > FLOOR_MAX_PLAUSIBLE_IN * IN or far:
            if not ask_yes_no(f"  {inch(tape)} (the rangefinder reads {inch(floor_r)}). "
                              "Is that right, in INCHES (not cm)?"):
                continue
        break
    return {"range_m": floor_r, "ekf_height_m": st.median(hz) if hz else None, "tape_m": tape,
            "gate_ok": gate_ok if fl else None, "gate_missing": missing}


def check_height(link, target_in):
    say(f"  Lift the drone level and hold it so the LENS is at the {target_in} in mark on the wall tape.")
    say("  Hold as still as you can; it waits for the reading to settle. (Enter cancels.)")
    input("  Press Enter, then lift ...")
    link.countdown(3, "Measuring")
    hold = link.wait_until(lambda: link.range_stable() and link.still(STILL_HAND), hold_s=2.0, max_s=40.0)
    if not hold:
        return fail("The reading never settled.")
    banner("GOT IT  -  you can lower the drone")
    a, b = hold
    rng = [r for t, r in link.rec["range"] if a <= t <= b]
    hz = [-p[3] for p in link.rec["pos"] if a <= p[0] <= b]
    r_med = st.median(rng)
    say(f"  Rangefinder {inch(r_med)} (PX4 height {inch(st.median(hz))}).")
    while True:
        tape = ask_number("  Where was the lens on the tape, in INCHES", default=target_in, lo=2, hi=120) * IN
        if abs(tape / IN - target_in) > HEIGHT_TARGET_TOL_IN:
            if not ask_yes_no(f"  This check is for the {target_in} in mark. Was it really at {inch(tape)}?"):
                continue
        break
    err = r_med - tape
    return {"tape_m": tape, "range_m": round(r_med, 3), "ekf_height_m": round(st.median(hz), 3),
            "error_m": round(err, 3), "ok": abs(err) <= max(HEIGHT_TOL_M, HEIGHT_TOL_FRAC * tape)}


def check_walk(link, kind, rot_now):
    offset = 0.0 if kind == "forward" else 90.0
    if kind == "forward":
        say("  Over mark A, with the drone's NOSE pointing at mark B.")
    else:
        say("  Over mark A, with the drone's RIGHT SIDE facing mark B (nose 90 degrees to the left of A->B).")
    say(f"  (Marks A and B are {WALK_TAPE_IN} in = 3 ft apart on the floor.)")
    say("  1. Lift it level to about chest height (3 ft) and hold still.")
    say("  2. When WALK NOW appears, walk to mark B in about 3 s. Don't turn the drone.")
    say("  3. Stop over B and hold still until STOPPED appears.     (Enter cancels.)")
    input("  Press Enter when you are ready to lift ...")
    link.countdown(3, "Lift and hold still")
    hold = link.wait_until(lambda: link.still(STILL_HAND) and (link.range_now() or 0) > 0.4,
                           hold_s=3.0, max_s=40.0)
    if not hold:
        return fail("It never held still at height for 3 s.")
    x0 = _median_xy(link.rec["pos"], *hold)

    def dist():
        p = link.xy_now()
        return math.hypot(p[0] - x0[0], p[1] - x0[1]) if p else 0.0

    banner("WALK NOW  ->  to mark B, ~3 s, level, same heading")
    if not link.wait_until(lambda: dist() > WALK_START_M, hold_s=0.2, max_s=30.0):
        return fail(f"PX4's position never moved {inch(WALK_START_M, 0)}: PX4 is probably not using the flow "
                    "(watch NO-FLOW / no-AGL in the live readings, V).")
    stop = link.wait_until(lambda: link.still(STILL_HAND) and (link.range_now() or 0) > 0.3 and dist() > WALK_MIN_M,
                           hold_s=2.0, max_s=40.0)
    if not stop:
        return fail(f"It never held still at the end (or PX4 saw less than {inch(WALK_MIN_M, 0)} of movement).")
    banner("STOPPED  -  lower the drone gently to the floor")
    w = analyze_walk(link.rec, before=hold, after=stop, expect_offset_deg=offset)
    if w is None:
        return fail("No position data for the walk.")
    w.update({"kind": kind, "rot_in_effect": rot_now})
    return w


def check_rc(link, params):
    """The RC backup: PX4 must see the kill switch go OFF and back to engaged, and the mode switch move."""
    kch, mch = params.get("RC_MAP_KILL_SW"), params.get("RC_MAP_FLTMODE")
    if kch is None or mch is None:
        return fail("could not read RC_MAP_KILL_SW / RC_MAP_FLTMODE (press 8 to retry)")
    if not kch or not mch:
        return fail("kill or mode switch not mapped (RC_MAP_KILL_SW / RC_MAP_FLTMODE = 0)")
    if kch == mch:
        return fail(f"kill switch and mode switch share channel {kch}")
    say("  RC transmitter ON. Keep BOTH sticks centred and don't touch them during this check.")
    say(f"  1. Flip the KILL switch OFF, then back ON.                       (channel {kch})")
    say(f"  2. Move the MODE switch through its positions, back to POSITION.  (channel {mch})")
    say("  It finishes by itself once it has seen both. (Enter cancels.)")
    input("  Press Enter to start watching ...")
    link.flush()
    drain_stdin()
    first = len(link.rec["rc"])
    state = {"kill_off_seen": False}

    def seen(ch):
        vals = [s[3][ch - 1] for s in link.rec["rc"][first:] if s[3][ch - 1] not in (0, 65535)]
        return (min(vals), max(vals), vals[0], vals[-1]) if vals else None

    def done():
        k_on = link.kill_engaged()
        if k_on is False:
            state["kill_off_seen"] = True
        m = seen(mch)
        return bool(state["kill_off_seen"] and k_on is True and m and m[1] - m[0] > 300 and abs(m[3] - m[2]) < 150)

    hold = link.wait_until(done, hold_s=1.0, max_s=60.0)
    if not link.recent("rc", 2.0):
        return fail("no RC_CHANNELS from PX4: is the RC receiver connected and bound?")
    k, m = seen(kch), seen(mch)
    if not hold:
        why = []
        if not state["kill_off_seen"]:
            why.append("PX4 never saw the kill switch OFF")
        elif link.kill_engaged() is not True:
            why.append("the kill switch is not back ON (engaged)")
        if not m or m[1] - m[0] <= 300:
            why.append(f"mode switch (ch {mch}) never moved")
        elif abs(m[3] - m[2]) >= 150:
            why.append("mode switch not back where it started")
        return fail("; ".join(why) or "timed out")
    banner("RC OK - kill switch ON, mode switch back")
    return {"ok": True, "kill": k, "mode": m,
            "text": f"kill went OFF and back ON (PX4's view), mode ch{mch} {m[0]}-{m[1]} us and back"}


# ----------------------------------------------------------------------------
# The menu
# ----------------------------------------------------------------------------
MARK = {"OK": "  OK ", "FAIL": " FAIL", "REDO": " REDO", "--": "  -- ", "opt": "  opt"}


def draw_menu(latest, params, kill_state=None):
    clear()
    ok, missing = readiness(latest, params)
    d = derived(latest, params)
    kill_txt = {True: "KILL SWITCH: ENGAGED", False: "KILL SWITCH: OFF - switch it ON!",
                None: "KILL SWITCH: unknown (RC on?)"}[kill_state]
    say("=" * 78)
    say(f" VENATOR ARK Flow calibration            {kill_txt}")
    say("=" * 78)
    say(f" Status: {'READY - all checks pass' if ok else 'NOT READY'}"
        f"      In effect: SENS_FLOW_ROT {params['SENS_FLOW_ROT']} | "
        f"EKF2_MIN_RNG {params['EKF2_MIN_RNG']} m ({inch(params['EKF2_MIN_RNG'])})")
    say("-" * 78)
    for num, key, title in STEPS:
        s, txt = status_of(key, latest, params)
        say(f"  {num}  {title:<26}[{MARK[s]}]  {txt}")
    for k in ("gate", "tracking", "direction"):
        say(f"     {TITLES[k]:<26}[{MARK[d[k][0]]}]  {d[k][1]}")
    say("-" * 78)
    props = proposals(latest, params)
    say("  A  Apply changes" + (": " + ", ".join(f"{n}={v}" + (" (optional)" if o else "")
                                                for n, v, _, _, o in props) if props else ": none needed now"))
    say("  V  Live readings      Q  Quit and save the report")
    say("-" * 78)
    nxt = "q" if ok else next_step(latest, params)
    say(f"  Next: {nxt.upper()}  (press Enter for it, or type any number to do or redo that check)")
    return nxt


def run_check(link, key, latest, params, history):
    """One check with retries. Any finished attempt (pass or fail) replaces the old result."""
    while True:
        clear()
        say("=" * 78)
        say(f"  CHECK: {TITLES[key]}")
        say("=" * 78)
        try:
            r = require_kill(link) if key in HANDLING else None
            if r is None:
                if key == "sensors":
                    r = check_sensors(link)
                elif key == "connectors":
                    r = check_connectors(link, params)
                elif key == "floor":
                    r = check_floor(link)
                elif key in ("h20", "h40"):
                    r = check_height(link, HEIGHTS_IN[0] if key == "h20" else HEIGHTS_IN[1])
                elif key == "rc":
                    r = check_rc(link, params)
                else:
                    r = check_walk(link, key, params["SENS_FLOW_ROT"])
            cancelled = False
        except Cancelled:
            say("  Cancelled: the previous result is kept.")
            r, cancelled = None, True
        history.append({"check": key, "t": round(link.now(), 1), "result": r, "cancelled": cancelled})
        if r is not None:
            latest[key] = r
        s, txt = status_of(key, latest, params) if latest.get(key) is not None else ("--", "not done")
        say("")
        say(f"  RESULT: {s} - {txt}")
        a = input("  Press Enter for the menu, or r + Enter to redo this check: ").strip().lower()
        if a != "r":
            return


def apply_changes(link, latest, params, writes):
    clear()
    say("=" * 78)
    say("  APPLY CHANGES")
    say("=" * 78)
    props = proposals(latest, params)
    if not props:
        input("  Nothing to change right now. Press Enter for the menu.")
        return
    for name, value, ptype, why, optional in props:
        say("")
        unit = "" if ptype == "INT32" else f" m ({inch(value)})"
        say(f"  {name}: now {params[name]} -> {value}{unit}" + ("   (optional)" if optional else ""))
        say(f"    why: {why}")
        a = input(f"  Type YES to write {name} = {value}, or press Enter to skip: ").strip()
        if a != "YES":
            say("    skipped.")
            continue
        link.require_disarmed()  # fresh heartbeat from the autopilot, or Armed/RuntimeError
        rec = {"param": name, "from": params[name], "value": value, "written": True}
        writes.append(rec)       # recorded before anything is sent
        got = link.write_param(name, value, ptype)
        ok = got is not None and (got == value if ptype == "INT32" else abs(got - value) < 1e-3)
        rec.update({"read_back": got, "ok": ok})
        if got is not None:
            params[name] = got
        say(f"    written; the Pixhawk reads back {got} -> " + ("OK" if ok else "MISMATCH"))
        if name == "SENS_FLOW_ROT" and ok:
            say("    The walks were recorded with the old value: redo the forward walk (6).")
        if name == "EKF2_MIN_RNG" and ok:
            say("    If 'PX4 height follows' failed, quit, power-cycle, and redo checks 3-5 to confirm.")
    say("  Letting PX4 save the parameters ...")
    link.run_for(3.0)
    input("  Press Enter for the menu.")


def live_view(link):
    clear()
    say("  LIVE READINGS (press Enter to return to the menu)")
    link.flush()
    while True:
        link.run_for(1.0)
        say(link.status_line())
        if enter_pressed():
            return


def _graceful_stop(signum, frame):
    raise KeyboardInterrupt  # closing the window or a kill: same clean stop as Ctrl+C


def wait_for_pixhawk(port=None, max_s=300):
    """Return the Pixhawk's serial device, waiting (with a clear message) until it is plugged in."""
    from preflight_audit import find_fc
    dev = port or find_fc()
    if os.path.exists(dev):
        return dev
    say("")
    say("  The Pixhawk is NOT connected to the Jetson: there is no /dev/ttyACM* device.")
    say("  Check that the Pixhawk's USB cable is plugged in at BOTH ends (the Jetson's USB hub")
    say("  and the Pixhawk itself). Waiting for it ...   (Ctrl+C to stop)")
    start = time.monotonic()
    try:
        while time.monotonic() - start < max_s:
            time.sleep(1)
            if os.path.exists(port or find_fc()):
                say("  Pixhawk found. Letting it finish booting ...")
                time.sleep(3)
                dev = port or find_fc()
                if os.path.exists(dev):
                    return dev
    except KeyboardInterrupt:
        sys.exit("  Stopped. Plug in the Pixhawk's USB, then start the calibration again.")
    sys.exit("  Still no Pixhawk after 5 minutes. Plug in its USB cable, then start the calibration again.")


def run(args):
    if not sys.stdin.isatty():
        sys.exit("Run this in a terminal: it asks you questions as you go.")
    import signal
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _graceful_stop)
    dev = wait_for_pixhawk(args.port)
    unreadable = interlock(dev)
    say("VENATOR ARK Flow calibration: connecting ...")
    report = {"started_unix": int(time.time()), "device": dev}
    latest, history, writes = {}, [], []
    report.update({"latest": latest, "history": history, "writes": writes})
    params = {}
    report["params_before"] = params        # filled as it is read, so a stop keeps what was read
    link = None
    try:
        link = Link(dev)
        link.require_disarmed()
        say(f"  Autopilot found (system {link.m.target_system}, component {link.ap_comp}); it reports DISARMED.")
        if unreadable:
            say(f"  (note: {unreadable} root-owned processes could not be checked for the port)")
        names = ["SENS_FLOW_ROT", "EKF2_MIN_RNG"] + [f"EKF2_OF_POS_{a}" for a in "XYZ"] + \
                [f"EKF2_RNG_POS_{a}" for a in "XYZ"] + ["EKF2_HGT_REF", "EKF2_RNG_CTRL", "UAVCAN_RNG_MIN",
                                                        "RC_MAP_KILL_SW", "RC_MAP_FLTMODE", "RC_KILLSWITCH_TH"]
        for n in names:
            params[n] = link.read_param(n)[0]
        kch = params.get("RC_MAP_KILL_SW")
        if kch:
            for s in ("MIN", "TRIM", "MAX", "REV"):
                params[f"RC{kch}_{s}"] = link.read_param(f"RC{kch}_{s}")[0]
            link.kill_cal = (params[f"RC{kch}_MIN"], params[f"RC{kch}_TRIM"], params[f"RC{kch}_MAX"],
                             params[f"RC{kch}_REV"], params.get("RC_KILLSWITCH_TH"))
        report["params_before"] = dict(params)
        link.kill_ch, link.mode_ch = kch, params.get("RC_MAP_FLTMODE")
        if params["SENS_FLOW_ROT"] not in ROT_DEG or params["EKF2_MIN_RNG"] is None:
            raise RuntimeError(f"could not read SENS_FLOW_ROT/EKF2_MIN_RNG "
                               f"({params['SENS_FLOW_ROT']}, {params['EKF2_MIN_RNG']})")
        if params.get("EKF2_HGT_REF") == 2:
            say("  WARNING: EKF2_HGT_REF is 2 (range sensor). In PX4 1.17 that switches off the height-above-")
            say("  ground estimate the indoor gate needs; set it to 0 (barometer) and reboot.")
        link.set_rates()
        link.run_for(1.5)
        if link.kill_engaged() is not True:
            say("  PX4 reads the kill switch as " + ("OFF" if link.kill_engaged() is False else "unknown") +
                ". The props are fitted: switch the kill ON before handling the drone.")
        keys = {num: key for num, key, _ in STEPS}
        while True:
            link.flush(settle=0.4)
            nxt = draw_menu(latest, params, link.kill_engaged())
            choice = input("  Choose: ").strip().lower() or nxt
            if choice in keys:
                run_check(link, keys[choice], latest, params, history)
            elif choice == "a":
                apply_changes(link, latest, params, writes)
            elif choice == "v":
                live_view(link)
            elif choice == "q":
                break
    except Armed as exc:
        say("")
        say("  STOPPED: the autopilot reports ARMED. Hands off; kill switch ON. Only the stream-rate restore is sent.")
        report["aborted"] = "armed"
        report["aborted_detail"] = exc.detail
    except KeyboardInterrupt:
        say("")
        say("  Stopped by you.")
        report["aborted"] = "stopped by operator"
    except SystemExit as exc:
        report["aborted"] = str(exc.code)
        raise
    except Exception as exc:  # e.g. the USB link dropped
        say("")
        say(f"  STOPPED on an error: {exc!r}. Only the stream-rate restore is sent. Kill switch stays ON.")
        report["aborted"] = repr(exc)
    finally:
        import signal as _s
        for sig in (_s.SIGINT, _s.SIGTERM, _s.SIGHUP):
            _s.signal(sig, _s.SIG_IGN)
        if link is not None:
            try:
                link.close()
            except Exception:
                pass
        try:
            ok, missing = (readiness(latest, params)
                           if params.get("SENS_FLOW_ROT") in ROT_DEG and params.get("EKF2_MIN_RNG") is not None
                           else (False, ["not started"]))
        except Exception as exc:   # never lose the report over the summary
            ok, missing = False, [f"summary failed: {exc!r}"]
        report.update({"params_in_effect": dict(params), "ready": ok, "not_ok": missing,
                       "samples": link.rec if link is not None else {}})
        say("")
        say("  RESULT: " + ("ARK CALIBRATION OK - all checks pass." if ok else
                            "NOT READY - still to pass: " + ", ".join(missing)))
        for w in writes:
            say(f"  written this run: {w['param']} {w['from']} -> {w.get('read_back')}"
                + ("" if w.get("ok") else "  (MISMATCH)"))
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / time.strftime("ark-calibration-%Y%m%d-%H%M%S.json")
        with open(path, "w") as fh:
            json.dump(report, fh, indent=1)
        say(f"  Report saved: {path}")
        if ok:
            say("  Next: put the drone on its launch spot, power-cycle (battery out 10 s), then the flight steps.")
    return report


def analyze_offline(args):
    rec = load_samples(args.analyze)
    w = analyze_walk(rec, tuple(args.before), tuple(args.after), 90.0 if args.sideways else 0.0)
    if w is None:
        sys.exit("No samples in those windows.")
    print(json.dumps(w, indent=1))
    enum, psi, resid = needed_rotation(args.rot, w["error_deg"])
    print(f"usable: {walk_usable(w)}; with SENS_FLOW_ROT={args.rot} the sensor's yaw measures {psi} deg "
          f"-> SENS_FLOW_ROT {enum} ({ROT_DEG[enum]} deg, residual {resid:+.1f} deg)")


def self_test():
    """Offline checks, including one through a model of PX4's own rotation, not just our inverse."""
    ok = True
    # 1. PX4 chain: board yawed psi reports a body motion in board coordinates; PX4 applies
    #    rotate_3f(SENS_FLOW_ROT). needed_rotation must recover psi, for every case and both walks.
    for s in range(8):
        for p in range(8):
            for walk_deg in (0.0, 90.0):
                bx, by = math.cos(math.radians(walk_deg)), math.sin(math.radians(walk_deg))
                a = -math.radians(ROT_DEG[p])
                vx, vy = bx * math.cos(a) - by * math.sin(a), bx * math.sin(a) + by * math.cos(a)
                mx, my = px4_rotate_yaw(s, vx, vy)
                err = wrap180(math.degrees(math.atan2(my, mx)) - walk_deg)
                enum, _, resid = needed_rotation(s, err)
                ok &= enum == p and abs(resid) < 1e-6
    ok &= [CONNECTORS[k][0] for k in "blfr"] == [0, 2, 4, 6]
    # 2. PX4's kill-switch rule with this aircraft's RC5 calibration (live shell 2026-11-20).
    cal = (1011.0, 1499.0, 1988.0, 1.0, 0.75)
    ok &= switch_on(1988, *cal) is True and switch_on(1011, *cal) is False and switch_on(1500, *cal) is False
    ok &= switch_on(1011, 1011.0, 1499.0, 1988.0, 1.0, -0.25) is True       # inverted threshold
    # 3. A synthetic forward walk: heading -104, sensor at 270, recorded with setting 0.
    #    Still 0-3 s, walking 3-8 s at 0.4 m/s (1 m), still 8-11 s, like the bench data.
    h = math.radians(-104.0)

    def walk_rec(bearing_rad, flags_moving=FLAG_HORIZ | FLAG_AGL):
        pos = []
        for t in range(0, 110):
            f = min(max((t / 10 - 3.0) / 5.0, 0.0), 1.0)
            v = 0.4 if 3.0 < t / 10 < 8.0 else 0.0
            pos.append((t / 10, f * math.cos(bearing_rad), f * math.sin(bearing_rad), -1.2, v))
        flags = [(t / 10, (FLAG_HORIZ | FLAG_AGL | FLAG_CONST) if not 3.0 < t / 10 < 8.0 else flags_moving)
                 for t in range(0, 110)]          # PX4 sets the const-pos bit while held still
        return {"pos": pos, "yaw": [(t / 10, h) for t in range(0, 110)], "flags": flags}

    rec = walk_rec(math.radians(-104.0 + wrap180(0 - 270)))
    w0 = dict(analyze_walk(rec, (0, 3), (8, 11), 0.0), kind="forward", rot_in_effect=0)
    ok &= walk_usable(w0) and w0["flow_fused"] is True and needed_rotation(0, w0["error_deg"])[0] == 6
    ok &= not walk_usable(analyze_walk(walk_rec(math.radians(-14.0), FLAG_CONST), (0, 3), (8, 11), 0.0))
    ok &= not walk_usable(analyze_walk(walk_rec(math.radians(-14.0), FLAG_HORIZ), (0, 3), (8, 11), 0.0))  # no AGL
    # 4. The menu logic, end to end on a synthetic session.
    params = {"SENS_FLOW_ROT": 0, "EKF2_MIN_RNG": 0.4, "EKF2_OF_POS_X": 0.0, "EKF2_OF_POS_Y": 0.0,
              "EKF2_OF_POS_Z": 0.158, "EKF2_RNG_POS_X": 0.0, "EKF2_RNG_POS_Y": 0.0, "EKF2_RNG_POS_Z": 0.158}
    latest = {"sensors": {"ok": True, "text": "ok"}, "connectors": {"predicted_rot": 6, "word": "right"},
              "rc": {"ok": True, "text": "ok"},
              "floor": {"range_m": 0.05, "ekf_height_m": 0.0, "tape_m": 0.10, "gate_ok": True, "gate_missing": []},
              "h20": {"tape_m": 0.508, "range_m": 0.51, "ekf_height_m": 0.41, "error_m": 0.0, "ok": True},
              "h40": {"tape_m": 1.016, "range_m": 1.0, "ekf_height_m": 0.9, "error_m": 0.0, "ok": True},
              "forward": w0}
    ok &= {n: v for n, v, *_ in proposals(latest, params)} == {"SENS_FLOW_ROT": 6, "EKF2_MIN_RNG": 0.1}
    ok &= not readiness(latest, params)[0] and next_step(latest, params) == "a"      # A first
    params.update({"SENS_FLOW_ROT": 6, "EKF2_MIN_RNG": 0.1})            # after A
    ok &= status_of("forward", latest, params)[0] == "REDO" and next_step(latest, params) == "6"
    good = walk_rec(h)
    latest["forward"] = dict(analyze_walk(good, (0, 3), (8, 11), 0.0), kind="forward", rot_in_effect=6)
    ok &= readiness(latest, params)[0] and next_step(latest, params) == "q"
    # a failed redo replaces the good walk: no longer READY (review RPI-2)
    keep = latest["forward"]
    latest["forward"] = {"failed": True, "text": "PX4's position never moved 10 in"}
    ok &= not readiness(latest, params)[0] and status_of("forward", latest, params)[0] == "FAIL"
    latest["forward"] = keep
    # a fresh walk FAIL with a good sideways walk is NOT READY (review RPI-1)
    latest["sideways"] = dict(analyze_walk(walk_rec(h + math.pi / 2), (0, 3), (8, 11), 90.0),
                              kind="sideways", rot_in_effect=6)
    latest["forward"] = dict(keep, flow_fused=False)
    ok &= not readiness(latest, params)[0]
    latest["forward"] = keep
    ok &= readiness(latest, params)[0]                                  # both walks good
    # an optional sideways walk that only turned too much does not block; a flow dropout does
    latest["sideways"] = dict(latest["sideways"], heading_spread_deg=26.0)
    ok &= readiness(latest, params)[0]
    latest["sideways"] = dict(latest["sideways"], heading_spread_deg=3.0, flow_fused=False)
    ok &= not readiness(latest, params)[0]
    latest["sideways"] = None
    # the RUN 8 gate failing on the floor is NOT READY (today's bug)
    latest["floor"] = dict(latest["floor"], gate_ok=False, gate_missing=["height above ground"])
    ok &= not readiness(latest, params)[0] and derived(latest, params)["gate"][0] == "FAIL"
    latest["floor"] = dict(latest["floor"], gate_ok=True, gate_missing=[])
    # the RC check missing or failed is NOT READY
    latest["rc"] = {"failed": True, "text": "PX4 never saw the kill switch OFF"}
    ok &= not readiness(latest, params)[0] and next_step(latest, params) == "8"
    latest["rc"] = {"ok": True, "text": "ok"}
    # one rounding rule for EKF2_MIN_RNG (review RPI-4): no FAIL-without-proposal, no OK-with-proposal
    for p_mr in [x / 100 for x in range(1, 51)]:
        for t_in in [x / 10 for x in range(5, 161)]:
            pr = {"SENS_FLOW_ROT": 6, "EKF2_MIN_RNG": p_mr}
            lt = {"floor": {"range_m": 0.05, "ekf_height_m": 0.0, "tape_m": t_in * IN}}
            row_fail = status_of("floor", lt, pr)[0] == "FAIL"
            has_prop = any(n == "EKF2_MIN_RNG" for n, *_ in proposals(lt, pr))
            ok &= row_fail == has_prop
    # PX4 height not following the rangefinder is NOT READY
    latest["h20"]["ekf_height_m"] = -0.76
    ok &= derived(latest, params)["tracking"][0] == "FAIL" and not readiness(latest, params)[0]
    print("self-test", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Guided ARK Flow calibration for VENATOR (menu, every check redoable).")
    ap.add_argument("--port", help="Pixhawk serial device (default: auto)")
    ap.add_argument("--analyze", metavar="FILE", help="analyse a saved recording instead (offline)")
    ap.add_argument("--before", nargs=2, type=float, metavar=("A", "B"), help="still window before the walk (s)")
    ap.add_argument("--after", nargs=2, type=float, metavar=("C", "D"), help="still window after the walk (s)")
    ap.add_argument("--sideways", action="store_true", help="the walk was toward the right side")
    ap.add_argument("--rot", type=int, default=0, choices=range(8), help="SENS_FLOW_ROT during the recording")
    ap.add_argument("--self-test", action="store_true", help="check the maths and menu logic offline")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(0 if self_test() else 1)
    if args.analyze:
        if not (args.before and args.after):
            ap.error("--analyze needs --before A B and --after C D")
        analyze_offline(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
