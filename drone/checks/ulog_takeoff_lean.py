#!/usr/bin/env python3
"""Measure the takeoff lean in PX4 flight logs, and what causes it.

    ./venv/bin/python drone/checks/ulog_takeoff_lean.py ~/.local/state/venator/ulogs/*.ulg
        [--json out.json]

Per log: arming, liftoff and landing times; the largest tilt in the first seconds
after liftoff and which way it leans; the steady-hover attitude (a level-horizon
error shows up here); the rate controller's integrators and torque setpoint (the
steady torque the frame needs); per-motor outputs and the centre of gravity they
imply from the CA_ROTOR geometry; drift in the body frame; and whether the operator
moved the sticks or changed mode. Read-only: it only reads the files.

Sign conventions (PX4 FRD body frame): roll + = right side down (leans RIGHT),
pitch + = nose up (leans BACK). CG x + = forward, y + = right.
"""
import argparse
import json
import math
import sys

import numpy as np
from pyulog import ULog

TOPICS = ["vehicle_attitude", "vehicle_attitude_setpoint", "rate_ctrl_status", "actuator_motors",
          "vehicle_land_detected", "vehicle_local_position", "vehicle_status",
          "manual_control_setpoint", "battery_status", "vehicle_torque_setpoint",
          "vehicle_thrust_setpoint", "vehicle_angular_velocity", "vehicle_local_position_setpoint"]
PARAMS = ["CA_ROTOR_COUNT", "SENS_BOARD_ROT", "SENS_BOARD_X_OFF", "SENS_BOARD_Y_OFF", "SENS_BOARD_Z_OFF",
          "MC_ROLL_P", "MC_PITCH_P", "MC_ROLLRATE_P", "MC_ROLLRATE_I", "MC_ROLLRATE_D", "MC_ROLLRATE_K",
          "MC_PITCHRATE_P", "MC_PITCHRATE_I", "MC_PITCHRATE_D", "MC_PITCHRATE_K", "MC_RR_INT_LIM",
          "MC_PR_INT_LIM", "MPC_TKO_RAMP_T", "MPC_TKO_SPEED", "MPC_THR_HOVER", "MPC_USE_HTE",
          "MIS_TAKEOFF_ALT", "THR_MDL_FAC", "COM_POS_FS_EPH", "EKF2_HGT_REF", "EKF2_MIN_RNG",
          "SENS_FLOW_ROT", "MPC_XY_P", "MPC_XY_VEL_P_ACC", "MPC_XY_VEL_I_ACC", "MPC_Z_VEL_P_ACC",
          "MPC_LAND_SPEED", "COM_DISARM_LAND", "CAL_ACC0_ID", "CAL_GYRO0_ID"]
NAV = {0: "MANUAL", 1: "ALTCTL", 2: "POSCTL", 4: "HOLD", 12: "DESCEND", 14: "OFFBOARD", 15: "STAB",
       17: "TAKEOFF", 18: "LAND"}


def euler(q):
    w, x, y, z = q
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return roll, pitch, yaw


def topic(ulog, name, inst=0):
    for d in ulog.data_list:
        if d.name == name and d.multi_id == inst:
            return d.data
    return None


def at(t, ts, vals):
    """Nearest-previous sample of vals at time t."""
    i = np.searchsorted(ts, t, side="right") - 1
    return vals[max(0, min(i, len(vals) - 1))]


def lean_words(roll_deg, pitch_deg):
    bits = []
    if abs(roll_deg) >= 0.5:
        bits.append(f"{abs(roll_deg):.1f} deg {'RIGHT' if roll_deg > 0 else 'LEFT'}")
    if abs(pitch_deg) >= 0.5:
        bits.append(f"{abs(pitch_deg):.1f} deg {'BACK (nose up)' if pitch_deg > 0 else 'FORWARD (nose down)'}")
    return ", ".join(bits) or "level (< 0.5 deg)"


def analyse(path):
    ulog = ULog(path, TOPICS)
    p = ulog.initial_parameters
    out = {"file": path, "params": {k: p.get(k) for k in PARAMS if k in p}}
    t0 = ulog.start_timestamp

    st = topic(ulog, "vehicle_status")
    ld = topic(ulog, "vehicle_land_detected")
    att = topic(ulog, "vehicle_attitude")
    if st is None or ld is None or att is None:
        out["error"] = "missing vehicle_status / land_detected / attitude"
        return out
    s = lambda us: (np.asarray(us, dtype=np.int64) - t0) / 1e6  # noqa: E731

    ts_st = s(st["timestamp"])
    armed = st["arming_state"] == 2
    arm_t = float(ts_st[np.argmax(armed)]) if armed.any() else None
    disarm_t = None
    if arm_t is not None:
        after = np.where((ts_st > arm_t) & ~armed)[0]
        disarm_t = float(ts_st[after[0]]) if len(after) else None
    navs, last = [], None
    for t, n in zip(ts_st, st["nav_state"]):
        if n != last:
            navs.append((round(float(t), 2), NAV.get(int(n), int(n))))
            last = n
    out["nav_timeline"] = navs
    out["armed_s"], out["disarmed_s"] = arm_t, disarm_t

    ts_ld = s(ld["timestamp"])
    landed = ld["landed"].astype(bool)
    lift = np.where(landed[:-1] & ~landed[1:])[0]
    lift_t = float(ts_ld[lift[0] + 1]) if len(lift) else None
    touch = np.where(~landed[:-1] & landed[1:])[0]
    touch_t = float(ts_ld[touch[touch > (lift[0] if len(lift) else -1)][0] + 1]) if len(touch) and len(lift) and (touch > lift[0]).any() else None
    out["liftoff_s"], out["touchdown_s"] = lift_t, touch_t

    ts_att = s(att["timestamp"])
    q = np.stack([att["q[0]"], att["q[1]"], att["q[2]"], att["q[3]"]], axis=1)
    e = np.array([euler(r) for r in q])
    roll, pitch, yaw = np.degrees(e[:, 0]), np.degrees(e[:, 1]), e[:, 2]

    # worst tilt over the whole armed period: a tip-over shows up here
    if arm_t is not None:
        aw = (ts_att >= arm_t) & (ts_att <= (disarm_t or ts_att[-1]))
        if aw.any():
            tilt_all = np.hypot(roll[aw], pitch[aw])
            k = int(np.argmax(tilt_all))
            out["worst_tilt_while_armed"] = {"deg": round(float(tilt_all[k]), 1),
                                             "at_s": round(float(ts_att[aw][k]), 2),
                                             "direction": lean_words(float(roll[aw][k]), float(pitch[aw][k])),
                                             "tipped_over": bool(tilt_all[k] > 35)}
    if lift_t is None:
        out["note"] = "never left the ground (land detector stayed landed)"
        return out

    # 1) the takeoff lean: largest tilt from 1 s before liftoff to 3 s after
    w = (ts_att >= lift_t - 1.0) & (ts_att <= lift_t + 3.0)
    if w.any():
        tilt = np.hypot(roll[w], pitch[w])
        i = int(np.argmax(tilt))
        r_, p_ = float(roll[w][i]), float(pitch[w][i])
        out["takeoff_max_tilt"] = {"deg": round(float(tilt[i]), 2), "roll": round(r_, 2), "pitch": round(p_, 2),
                                   "at_s_after_liftoff": round(float(ts_att[w][i] - lift_t), 2),
                                   "direction": lean_words(r_, p_)}
    # attitude on the ground just before liftoff (floor slope / frame sitting)
    g = (ts_att >= lift_t - 3.0) & (ts_att <= lift_t - 1.5)
    if g.any():
        out["ground_attitude"] = {"roll": round(float(roll[g].mean()), 2), "pitch": round(float(pitch[g].mean()), 2)}

    # attitude setpoint vs actual over the takeoff window
    asp = topic(ulog, "vehicle_attitude_setpoint")
    if asp is not None:
        ts_sp = s(asp["timestamp"])
        qd = np.stack([asp["q_d[0]"], asp["q_d[1]"], asp["q_d[2]"], asp["q_d[3]"]], axis=1)
        ed = np.degrees(np.array([euler(r) for r in qd])[:, :2])
        if w.any():
            rs = np.array([at(t, ts_sp, ed[:, 0]) for t in ts_att[w]])
            ps = np.array([at(t, ts_sp, ed[:, 1]) for t in ts_att[w]])
            # Was the lean ORDERED (PX4 steering somewhere) or FOUGHT (the frame
            # tilting against a level command: thrust, balance, tether, a leg)?
            cmd = np.hypot(rs, ps)
            k2 = int(np.argmax(cmd))
            out["takeoff_max_commanded_tilt"] = {
                "deg": round(float(cmd[k2]), 2), "at_s_after_liftoff": round(float(ts_att[w][k2] - lift_t), 2),
                "direction": lean_words(float(rs[k2]), float(ps[k2]))}
            err = np.hypot(roll[w] - rs, pitch[w] - ps)
            j = int(np.argmax(err))
            out["takeoff_max_attitude_error"] = {
                "deg": round(float(err[j]), 2), "at_s_after_liftoff": round(float(ts_att[w][j] - lift_t), 2),
                "actual": lean_words(float(roll[w][j]), float(pitch[w][j])),
                "setpoint": lean_words(float(rs[j]), float(ps[j]))}

    # 2) steady hover window: 4 s after liftoff to 1.5 s before touchdown, low speed
    end = (touch_t if touch_t else ts_att[-1]) - 1.5
    lp = topic(ulog, "vehicle_local_position")
    if lp is not None:
        ts_lp0 = s(lp["timestamp"])
        air = (ts_lp0 >= lift_t) & (ts_lp0 <= (touch_t or ts_lp0[-1]))
        if air.any():
            # A tether that runs out caps the climb: height stalls below the target.
            out["max_height_m"] = round(float((-lp["z"][air]).max()), 2)
            if "dist_bottom" in lp:
                out["max_dist_bottom_m"] = round(float(lp["dist_bottom"][air].max()), 2)
            out["max_horizontal_speed_mps"] = round(float(np.hypot(lp["vx"][air], lp["vy"][air]).max()), 2)
    hover = None
    if lp is not None and end - (lift_t + 4.0) > 2.0:
        ts_lp = s(lp["timestamp"])
        hv = (ts_lp >= lift_t + 4.0) & (ts_lp <= end) & (np.hypot(lp["vx"], lp["vy"]) < 0.3) & (np.abs(lp["vz"]) < 0.2)
        # airborne and upright: a drone lying tipped on the floor is also "still"
        if "dist_bottom" in lp:
            hv &= lp["dist_bottom"] > 0.5
        up = np.array([abs(at(t, ts_att, roll)) < 30 and abs(at(t, ts_att, pitch)) < 30 for t in ts_lp])
        hv &= up
        if hv.sum() > 20:
            hover = (float(ts_lp[hv][0]), float(ts_lp[hv][-1]), hv, ts_lp)
    if hover:
        h0, h1, hv, ts_lp = hover
        ha = (ts_att >= h0) & (ts_att <= h1)
        out["hover_window_s"] = [round(h0 - lift_t, 1), round(h1 - lift_t, 1)]
        out["hover_attitude"] = {"roll": round(float(roll[ha].mean()), 2), "pitch": round(float(pitch[ha].mean()), 2),
                                 "roll_std": round(float(roll[ha].std()), 2), "pitch_std": round(float(pitch[ha].std()), 2),
                                 "direction": lean_words(float(roll[ha].mean()), float(pitch[ha].mean()))}
        out["hover_height_m"] = round(float(-lp["z"][hv].mean()), 2)
        if "dist_bottom" in lp:
            out["hover_dist_bottom_m"] = round(float(lp["dist_bottom"][hv].mean()), 2)

    # rate integrators and torque: at liftoff, and steady hover
    rc = topic(ulog, "rate_ctrl_status")
    if rc is not None:
        ts_rc = s(rc["timestamp"])
        def integ(t):
            return {k: round(float(at(t, ts_rc, rc[f"{k}speed_integ"])), 4) for k in ("roll", "pitch", "yaw")}
        out["integrator_at_liftoff"] = integ(lift_t)
        out["integrator_1s_after"] = integ(lift_t + 1.0)
        out["integrator_3s_after"] = integ(lift_t + 3.0)
        if hover:
            hr = (ts_rc >= hover[0]) & (ts_rc <= hover[1])
            out["integrator_hover"] = {k: round(float(rc[f"{k}speed_integ"][hr].mean()), 4) for k in ("roll", "pitch", "yaw")}
    tq = topic(ulog, "vehicle_torque_setpoint")
    if tq is not None and hover:
        ts_tq = s(tq["timestamp"])
        ht = (ts_tq >= hover[0]) & (ts_tq <= hover[1])
        out["torque_setpoint_hover"] = {a: round(float(tq[f"xyz[{i}]"][ht].mean()), 4) for i, a in enumerate("xyz")}

    # 3) motors: mean output in hover, and the CG they imply from the CA geometry
    am = topic(ulog, "actuator_motors")
    n = int(p.get("CA_ROTOR_COUNT", 4) or 4)
    if am is not None and hover:
        ts_am = s(am["timestamp"])
        hm = (ts_am >= hover[0]) & (ts_am <= hover[1])
        u = np.array([float(am[f"control[{i}]"][hm].mean()) for i in range(n)])
        px = np.array([float(p.get(f"CA_ROTOR{i}_PX", 0.0)) for i in range(n)])
        py = np.array([float(p.get(f"CA_ROTOR{i}_PY", 0.0)) for i in range(n)])
        km = np.array([float(p.get(f"CA_ROTOR{i}_KM", 0.0)) for i in range(n)])
        out["motors_hover"] = [{"motor": i + 1, "output": round(float(u[i]), 4), "px": px[i], "py": py[i],
                                "spin": "CCW" if km[i] > 0 else "CW"} for i in range(n)]  # PX4: KM > 0 = CCW
        sat = bool((u > 0.95).any() or (u < 0.05).any())
        if u.sum() > 0 and not sat:
            # thrust taken as proportional to the normalised output. CA_ROTOR positions are
            # in CA units (here +-1 = one arm offset); an X500 V2 arm offset is ~177 mm.
            cg_x, cg_y = float((u * px).sum() / u.sum()), float((u * py).sum() / u.sum())
            arm = float(np.abs(px).max()) or 1.0
            out["cg_from_motors"] = {"x_forward_frac": round(cg_x / arm, 3), "y_right_frac": round(cg_y / arm, 3),
                                     "x_forward_mm_x500": round(cg_x / arm * 177, 1),
                                     "y_right_mm_x500": round(cg_y / arm * 177, 1)}
        elif sat:
            out["cg_from_motors"] = "not estimated: a motor was saturated"
        out["motor_spread"] = round(float(u.max() - u.min()), 4)

    # 4) drift in the body frame over the first 3 s after liftoff
    if lp is not None:
        ts_lp = s(lp["timestamp"])
        x0, y0 = at(lift_t, ts_lp, lp["x"]), at(lift_t, ts_lp, lp["y"])
        x3, y3 = at(lift_t + 3.0, ts_lp, lp["x"]), at(lift_t + 3.0, ts_lp, lp["y"])
        h = float(at(lift_t, ts_att, yaw))
        dn, de = float(x3 - x0), float(y3 - y0)
        fwd, right = dn * math.cos(h) + de * math.sin(h), -dn * math.sin(h) + de * math.cos(h)
        out["drift_first_3s_m"] = {"forward": round(fwd, 2), "right": round(right, 2)}
        # Without GPS, AUTO.TAKEOFF steers to local (0,0): where the Pixhawk powered up.
        # A drone that lifts off away from that spot slides toward it while climbing.
        out["liftoff_spot_from_power_on_spot_m"] = round(float(math.hypot(x0, y0)), 2)
        if math.hypot(x0, y0) > 0.05:
            # which way the power-on spot (local 0,0) lies, seen from the drone at liftoff
            dn0, de0 = -float(x0), -float(y0)        # liftoff spot -> local (0,0), NED
            out["power_on_spot_direction_m"] = {
                "forward": round(dn0 * math.cos(h) + de0 * math.sin(h), 2),
                "right": round(-dn0 * math.sin(h) + de0 * math.cos(h), 2)}
        sp = topic(ulog, "vehicle_local_position_setpoint")
        if sp is not None:
            ts_sp2 = s(sp["timestamp"])
            sx, sy = float(at(lift_t + 1.0, ts_sp2, sp["x"])), float(at(lift_t + 1.0, ts_sp2, sp["y"]))
            if math.isfinite(sx) and math.isfinite(sy):
                dn2, de2 = sx - float(x0), sy - float(y0)
                out["px4_target_vs_liftoff_spot_m"] = {
                    "forward": round(dn2 * math.cos(h) + de2 * math.sin(h), 2),
                    "right": round(-dn2 * math.sin(h) + de2 * math.cos(h), 2),
                    "distance": round(math.hypot(dn2, de2), 2)}
        if touch_t:
            xt, yt = at(touch_t, ts_lp, lp["x"]), at(touch_t, ts_lp, lp["y"])
            out["start_to_touchdown_m"] = round(float(math.hypot(xt - x0, yt - y0)), 2)

    # 5) operator: stick movement while armed
    mc = topic(ulog, "manual_control_setpoint")
    if mc is not None and arm_t is not None:
        ts_mc = s(mc["timestamp"])
        aw = (ts_mc >= arm_t) & (ts_mc <= (disarm_t or ts_mc[-1]))
        if aw.any():
            out["sticks_max_while_armed"] = {k: round(float(np.abs(mc[k][aw]).max()), 2) for k in ("roll", "pitch", "yaw")}
            out["throttle_range_while_armed"] = [round(float(mc["throttle"][aw].min()), 2), round(float(mc["throttle"][aw].max()), 2)]
            if "sticks_moving" in mc:
                mv = mc["sticks_moving"][aw].astype(bool)
                out["sticks_moving_first_s"] = round(float(ts_mc[aw][mv][0] - (lift_t or arm_t)), 2) if mv.any() else None

    bs = topic(ulog, "battery_status")
    if bs is not None and arm_t is not None:
        ts_b = s(bs["timestamp"])
        out["battery_v"] = [round(float(at(arm_t, ts_b, bs["voltage_v"])), 2),
                            round(float(at((touch_t or ts_b[-1]), ts_b, bs["voltage_v"])), 2)]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args()
    results = []
    for path in sorted(a.logs):
        try:
            r = analyse(path)
        except Exception as exc:  # one bad log must not hide the others
            r = {"file": path, "error": f"{type(exc).__name__}: {exc}"}
        results.append(r)
        print(f"\n===== {path.split('/')[-1]}")
        for k, v in r.items():
            if k not in ("file", "params"):
                print(f"  {k}: {v}")
    if results and "params" in results[-1]:
        print("\n===== parameters (newest log)")
        for k, v in results[-1]["params"].items():
            print(f"  {k} = {v}")
    if a.json:
        with open(a.json, "w") as f:
            json.dump(results, f, indent=1, default=float)
        print(f"\nJSON: {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
