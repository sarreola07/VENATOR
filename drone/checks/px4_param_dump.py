#!/usr/bin/env python3
"""Save every PX4 parameter to a QGroundControl-compatible .params file. Read-only.

    ./venv/bin/python drone/checks/px4_param_dump.py [--out FILE]

Uses PARAM_REQUEST_LIST, then PARAM_REQUEST_READ by index for anything that went
missing. It never sets anything. Refuses while venator-c2 (or anything else) holds
the Pixhawk port. To restore in QGroundControl: Vehicle Setup > Parameters > Tools >
Load from file, then reboot the vehicle.
"""
import argparse
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = os.path.expanduser("~/.local/state/venator/px4-params.params")
INT32, REAL32 = 6, 9
KEY = ("COM_POS_FS_EPH", "EKF2_HGT_REF", "EKF2_GPS_CTRL", "MAN_ARM_GESTURE", "SENS_FLOW_ROT",
       "EKF2_MIN_RNG", "EKF2_OF_POS_Z", "EKF2_RNG_POS_Z", "MIS_TAKEOFF_ALT", "COM_RC_IN_MODE",
       "NAV_RCL_ACT", "NAV_DLL_ACT", "COM_RC_OVERRIDE", "RC_MAP_KILL_SW", "SYS_AUTOSTART")


def name_of(pid):
    if isinstance(pid, bytes):
        pid = pid.decode("ascii", "replace")
    return pid.split("\x00", 1)[0].strip()


def value_of(v, ptype):
    """PX4 sends INT32 bytewise inside the float field."""
    if ptype == INT32:
        return struct.unpack("<i", struct.pack("<f", v))[0]
    return float(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    from preflight_audit import find_fc        # noqa: E402
    from px4_shell_probe import interlock      # noqa: E402
    from pymavlink import mavutil              # noqa: E402
    M = mavutil.mavlink
    dev = find_fc()
    interlock(dev)
    m = mavutil.mavlink_connection(dev, baud=115200)
    try:
        m.mav.heartbeat_send(M.MAV_TYPE_GCS, M.MAV_AUTOPILOT_INVALID, 0, 0, 0)
        # Talk to the autopilot itself (component 1), never to component 0: a
        # broadcast request is also answered by other components on the link (the
        # DroneCAN bridge sent 57 of its own), and their PARAM_VALUEs interleave.
        hb, end = None, time.monotonic() + 10
        while time.monotonic() < end:
            hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
            if hb is not None and hb.autopilot == M.MAV_AUTOPILOT_PX4 \
                    and hb.get_srcComponent() == M.MAV_COMP_ID_AUTOPILOT1:
                break
            hb = None
        if hb is None:
            sys.exit("REFUSED: no heartbeat from the PX4 autopilot.")
        ts, tc = hb.get_srcSystem(), M.MAV_COMP_ID_AUTOPILOT1

        def from_px4(msg):
            return msg.get_srcSystem() == ts and msg.get_srcComponent() == tc

        version = "unknown"
        m.mav.command_long_send(ts, tc, M.MAV_CMD_REQUEST_MESSAGE, 0,
                                M.MAVLINK_MSG_ID_AUTOPILOT_VERSION, 0, 0, 0, 0, 0, 0)
        av = m.recv_match(type="AUTOPILOT_VERSION", blocking=True, timeout=3)
        if av is not None:
            fw = av.flight_sw_version
            version = f"{fw >> 24 & 0xFF}.{fw >> 16 & 0xFF}.{fw >> 8 & 0xFF}"
            git = bytes(av.flight_custom_version).hex()[:16]
            version += f" (git {git})"

        params, total = {}, None
        m.mav.param_request_list_send(ts, tc)
        quiet_since = time.monotonic()
        while time.monotonic() - quiet_since < 3.0:
            pv = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.5)
            if pv is None or not from_px4(pv):
                continue
            quiet_since = time.monotonic()
            total = pv.param_count
            if pv.param_index != 0xFFFF:
                params[pv.param_index] = (name_of(pv.param_id), value_of(pv.param_value, pv.param_type),
                                          pv.param_type)
            if total and len(params) >= total:
                break
        if not total:
            sys.exit("FAILED: PX4 sent no parameters.")
        for _ in range(5):                      # fill any gaps, one by index
            missing = [i for i in range(total) if i not in params]
            if not missing:
                break
            print(f"  re-reading {len(missing)} missing parameter(s)...")
            for i in missing:
                m.mav.param_request_read_send(ts, tc, b"", i)
                end = time.monotonic() + 1.0
                while time.monotonic() < end:
                    pv = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.3)
                    if pv is not None and from_px4(pv) and pv.param_index == i:
                        params[i] = (name_of(pv.param_id), value_of(pv.param_value, pv.param_type),
                                     pv.param_type)
                        break
        missing = [i for i in range(total) if i not in params]

        rows = sorted(params.values())
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w") as f:
            f.write(f"# Onboard parameters for Vehicle {ts}\n#\n# Stack: PX4 Pro\n# Vehicle: Multi-Rotor\n"
                    f"# Version: {version}\n# Saved: {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"(Jetson clock; it can be wrong after a power-cycle)\n#\n"
                    "# Vehicle-Id\tComponent-Id\tName\tValue\tType\n")
            for name, val, ptype in rows:
                f.write(f"{ts}\t{tc}\t{name}\t{val if ptype == INT32 else repr(val)}\t{ptype}\n")
        with open(os.path.splitext(a.out)[0] + ".json", "w") as f:
            json.dump({"version": version, "count": len(rows), "missing_indices": missing,
                       "params": {n: v for n, v, _ in rows}}, f, indent=1, sort_keys=True)
        print(f"Saved {len(rows)} of {total} parameters (PX4 {version}) -> {a.out}")
        if missing:
            print(f"WARNING: {len(missing)} parameter(s) never arrived: indices {missing[:10]}")
        got = {n: v for n, v, _ in rows}
        print("Key values: " + ", ".join(f"{k}={got[k]:g}" if isinstance(got.get(k), float)
                                         else f"{k}={got.get(k)}" for k in KEY))
        return 0 if not missing else 1
    finally:
        m.close()


if __name__ == "__main__":
    sys.exit(main())
