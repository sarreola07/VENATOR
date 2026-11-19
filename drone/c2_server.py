#!/usr/bin/env python3
"""
Venator Jetson C2 server — the drone side of the LoRa command link.

Reads C2 protocol messages from the LoRa stick (/dev/ttyUSB0), serves the
mission menu, runs missions on the Pixhawk, and ACKs back to the laptop client.
The laptop never touches the drone directly — it only speaks the protocol.

    # safe: mock flight controller, no hardware touched (default)
    python3 drone/c2_server.py

    # real: connect the Pixhawk and actually run missions, props OFF
    ./venv/bin/python drone/c2_server.py --real --props-off

Safety: defaults to a MOCK flight controller (--real for the Pixhawk). Props are
assumed ON, since in flight testing they stay fitted and the operator can't reach
the Jetson from the field; that means motor tests are refused until props are
declared OFF (menu "Toggle props state", or --props-off). Flight additionally
requires the FC's own checks to pass (GPS fix, pre-arm). Nothing arms on startup.
"""
import argparse
import glob
import json
import socket
import sys
import time
from pathlib import Path


# Runnable from any folder: put the repo root on the import path so the
# sibling packages (radio/, drone/, ground/) import the same modules
# whether this is started by path, by a desktop launcher or by systemd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radio import protocol as p
from radio.serial_link import SerialLink, DEFAULT_SETTLE_S

# Timers use the monotonic clock. The Jetson has no RTC battery, so the wall
# clock steps when NTP arrives after boot; a step forward used to trip LINK
# LOST at once and a step back stalled the pacing for the size of the jump.
_clock = time.monotonic

MAX_ALT_M = 50.0        # reject uploaded waypoints above this relative altitude
LINK_LOSS_S = 4.0       # in flight, no client ping for this long -> failsafe (RTL; hover: LAND)
FLIGHT_MAX_S = 600.0    # hard cap on a monitored flight -> same failsafe
STATUS_INTERVAL_S = 1.0 # how often to push in-flight status to the client
DRAIN_PER_TICK = 8      # messages read from the link per flight tick, at most
DEDUPE_S = 30.0         # a retransmitted command gets its cached replies this long
DEDUPE_REPLIES = 4      # ... and at most this many of them are kept
DONE_REPEAT_S = 15.0    # a flight's DONE rides again on the PONGs of this many seconds
DONE_REPEATS = 3        # ... at most this many times
QUIET_REPORT_S = 30.0   # log once when nothing has come from the ground for this long
STATS_REPORT_S = 60.0   # journal line with link counters while traffic flows

# PX4 ESTIMATOR_STATUS flag bits for a usable position, as drone/checks/check_flow.py
# reads them. Indoors (ARK Flow, --indoor) these replace the GPS gate for the hover.
POS_HORIZ_REL = 8
POS_VERT_AGL = 64
POSITION_FRESH_S = 2.0  # a position older than this is no position

# --- Mission 1: hover & detect ---
# GPS-safe hover altitude. A true 3 ft (0.91 m) hold is unsafe on GPS alone
# (several-metre vertical error); set this to 0.91 once the downward lidar is in.
HOVER_ALT_M = 2.0
HOVER_TIME_S = 60.0     # how long to hover and detect people
CAMERA_UDP_PORT = 5005  # OAK-D publisher (ai_camera.sh) broadcasts person X/Y/Z here

# --- Mission 2: follow-me (OFFBOARD velocity control) ---
FOLLOW_DIST_M = 3.0     # keep this distance from the person
FOLLOW_DIST_DEAD = 0.5  # deadband on distance (m)
FOLLOW_X_DEAD = 0.3     # deadband on horizontal offset (m) before yawing
FOLLOW_FWD_MPS = 0.5    # forward/back speed
FOLLOW_YAW_RPS = 0.35   # yaw rate (rad/s, ~20 deg/s)
CAMERA_LOSS_S = 1.0     # no person for this long -> hover in place (don't drift)

# --- Hover 3 ft (the LoRa remote's flight) ---
# Takeoff to 3 ft, hold, land in place. Every failsafe LANDs instead of RTL:
# hovering over the launch point, PX4's RTL would first climb to RTL_DESCEND_ALT
# / RTL_RETURN_ALT (10 m / 30 m on this vehicle) -- the opposite of what a 3 ft
# test wants. Height is baro-based until the downward lidar is fitted, so expect
# tens of centimetres of drift at this altitude; fly it with the RC kill switch
# in hand.
HOVER3_ALT_M = 0.91     # 3 ft
HOVER3_TIME_S = 10.0    # hold this long, then land
HOVER3_CLIMB_S = 20.0   # not at altitude by then -> land rather than wait

# A flight that was prepared (ACK confirm_required) but not CONFIRMed within
# this long lapses, so a confirm screen walked away from -- or a cancel lost on
# the air -- can never be launched later by a stray CONFIRM.
PENDING_CONFIRM_S = 60.0

# Error text sent over the radio is cut to this. The firmware carries at most 240
# characters a line, a signed reply spends about 40 of them on its signature,
# and a line that runs over is cut off and lost, not shortened.
ERROR_TEXT_MAX = 80


def short_error(exc, limit=ERROR_TEXT_MAX):
    """An error as text that fits in one radio reply."""
    text = str(exc) or type(exc).__name__
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _is_number(v):
    """A real int or float. The camera's packets are JSON, so never trust a type."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def find_fc_device(default="/dev/ttyACM0"):
    """Locate the Pixhawk robustly, so a USB replug (ttyACM0->ttyACM1) can't
    break the link. Prefer the stable by-id symlink (survives renumbering and
    the v2->v3 reflash, since the name still contains PX4/FMU), then any ttyACM."""
    for pat in ("/dev/serial/by-id/*PX4*", "/dev/serial/by-id/*FMU*",
                "/dev/serial/by-id/*Pixhawk*"):
        matches = sorted(glob.glob(pat))
        if matches:
            return matches[0]
    acms = sorted(glob.glob("/dev/ttyACM*"))
    if acms:
        return acms[0]
    # macOS / Windows (a laptop standing in for the Jetson): no by-id, no
    # ttyACM. The 6X enumerates as "PX4 FMU v6X.x" (/dev/cu.usbmodem01 on a Mac).
    try:
        from serial.tools import list_ports
        for pi in list_ports.comports():
            if any(k in (pi.description or "") for k in ("PX4", "FMU", "Pixhawk")):
                return pi.device
    except ImportError:
        pass
    return default


CP210X_VID = 0x10C4     # Heltec V3 onboard USB-serial (Silicon Labs CP2102)


def find_lora_device(default="/dev/ttyUSB0"):
    """Locate the Heltec LoRa stick robustly (it's a CP2102 USB-UART), so a
    replug (ttyUSB0->ttyUSB1) can't kill the service.

    by-id first: it is the most stable name on the Jetson, which is where this
    runs in production. Then a USB-VID scan, which is what finds the stick when
    the server is run on a Windows or macOS box standing in for the Jetson --
    there is no /dev/serial/by-id there, and the bare /dev/ttyUSB0 default below
    is a path those machines can never open."""
    for pat in ("/dev/serial/by-id/*CP2102*", "/dev/serial/by-id/*Silicon_Labs*"):
        matches = sorted(glob.glob(pat))
        if matches:
            return matches[0]
    try:
        from serial.tools import list_ports
        for pi in list_ports.comports():
            if pi.vid == CP210X_VID:
                return pi.device
    except ImportError:
        pass
    usbs = sorted(glob.glob("/dev/ttyUSB*"))
    return usbs[0] if usbs else default

# Reuse the tested mission logic and MAVLink helpers from missions.py.
# missions.py sys.exit()s at import time when pymavlink is missing, which raises
# SystemExit rather than ImportError -- catching only ImportError killed the
# server on any machine without pymavlink, even though the default mock FC needs
# neither pymavlink nor a Pixhawk. That matters for bench work on a laptop
# standing in for the Jetson, so treat both as "no MAVLink here".
try:
    import missions
    from pymavlink import mavutil
except (ImportError, SystemExit):
    missions = None
    mavutil = None


# --------------------------------------------------------------------------
# Flight-controller abstraction — mock (safe) or real (pymavlink via missions).
# --------------------------------------------------------------------------
class MockFC:
    """A fake flight controller so the server runs and is testable with no drone.

    Includes a tiny flight simulator (arm -> climb -> hover -> land/RTL -> disarm)
    so the flight trigger and link-loss failsafe can be exercised without a drone.
    Pass gps=True to simulate a 3D fix (needed to test the flight path).
    """
    name = "mock"

    def __init__(self, gps=False, position=None):
        self._gps = gps
        # Indoor position (ARK Flow). None: follows the GPS flag, as a real
        # vehicle with a fix also has a local position.
        self._position = gps if position is None else position
        self._armed = False
        self._mode = "HOLD"
        self._t_arm = 0.0
        self._t_land = None
        self._has_mission = False

    def status(self):
        return {"armed": self._armed, "gps": "3D fix" if self._gps else "no fix", "batt": 11.4}

    def has_gps_fix(self):
        return self._gps

    def has_position(self):
        return self._position

    def run_mission(self, mid, motors=4):
        time.sleep(0.1)
        return True, "ok (mock)"

    def upload_waypoints(self, wps):
        self._has_mission = len(wps) > 0
        return len(wps), 0, "stored (mock)"

    def has_mission(self):
        return self._has_mission

    # -- flight simulation --
    arm_detail = ""

    def diagnostics(self):
        return ("gps 3D/9sat | batt 11.4V | sensors OK" if self._gps
                else "gps noGPS/0sat | batt 11.4V | sensors OK")

    def arm(self, timeout=8):
        self._armed = True
        self._t_arm = time.time()
        self._t_land = None
        return True

    def disarm(self):
        self._armed = False
        return True

    def set_flight_mode(self, mode):
        self._mode = mode
        if mode in ("LAND", "RTL") and self._t_land is None:
            self._t_land = time.time()
        return True

    def send_velocity(self, vx, vy, vz, yaw_rate):
        self._last_vel = (vx, vy, vz, yaw_rate)   # recorded for tests

    def set_takeoff_alt(self, alt_m):
        self._takeoff_alt = alt_m
        return True

    def flight_state(self):
        now = time.time()
        # AUTO.MISSION completes on its own ~4 s after takeoff (mock). TAKEOFF/HOLD
        # (Mission 1) keeps hovering until the server explicitly commands LAND/RTL.
        if (self._armed and self._t_land is None and self._mode == "MISSION"
                and now - self._t_arm > 4.0):
            self._t_land = now
        # simulate touchdown + auto-disarm ~1.5 s after landing starts
        if self._armed and self._t_land and now - self._t_land > 1.5:
            self._armed = False
        if not self._armed:
            return {"armed": False, "alt": 0.0, "mode": self._mode}
        if self._t_land:
            alt = max(0.0, 1.5 - (now - self._t_land)) * 2.0
        else:
            alt = min(3.0, (now - self._t_arm) * 1.5)  # climb to 3 m
        return {"armed": True, "alt": round(alt, 2), "mode": self._mode}

    def close(self):
        pass


def param_name(pid):
    """A PARAM_VALUE's name as text. pymavlink hands it over as str or bytes,
    depending on the version, padded with NULs to 16 characters."""
    if isinstance(pid, (bytes, bytearray)):
        pid = pid.decode("ascii", "replace")
    return str(pid).split("\x00", 1)[0]


class RealFC:
    """Real flight controller: connects the Pixhawk and runs missions.py logic."""
    name = "real"

    def __init__(self, device, baud, indoor=False):
        self.master = missions.connect(device, baud)
        self.indoor = indoor
        # Cached flight state. _armed starts False but is set True by arm(), so a
        # mission loop can never mistake "no telemetry yet" for "already landed".
        self._armed = False
        self._alt = 0.0
        self._mode = "?"
        # Local position (ARK Flow indoors): height above ground from
        # LOCAL_POSITION_NED and the estimator's own verdict on it.
        self._local_alt = 0.0
        self._local_at = None
        self._pos_flags_ok = False
        self._pos_flags_at = None
        if indoor:
            self._request_position_stream()

    def _request_position_stream(self):
        """Ask PX4 for LOCAL_POSITION_NED and ESTIMATOR_STATUS at 5 Hz, the way
        drone/checks/check_flow.py does. Best effort: a refusal only means the
        default rates, and has_position() then judges by what arrives."""
        for msg_id in (32, 230):            # LOCAL_POSITION_NED, ESTIMATOR_STATUS
            try:
                self.master.mav.command_long_send(
                    self.master.target_system, self.master.target_component,
                    mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                    msg_id, 200000, 0, 0, 0, 0, 0)
            except Exception:
                pass

    def _take_position(self, msg):
        """Fold a LOCAL_POSITION_NED or ESTIMATOR_STATUS into the caches."""
        t = msg.get_type()
        if t == "LOCAL_POSITION_NED":
            self._local_alt = round(-float(msg.z), 2)      # NED: down is positive
            self._local_at = _clock()
        elif t == "ESTIMATOR_STATUS":
            self._pos_flags_ok = bool(msg.flags & POS_HORIZ_REL) and bool(msg.flags & POS_VERT_AGL)
            self._pos_flags_at = _clock()

    def has_position(self):
        """Indoors: PX4 has a usable local position (ARK Flow + range finder).
        Both the estimator's flags and a fresh LOCAL_POSITION_NED are needed:
        flags alone can stay set for a moment after the flow stops."""
        end = _clock() + 2.0
        while _clock() < end:
            m = self.master.recv_match(type=["LOCAL_POSITION_NED", "ESTIMATOR_STATUS"],
                                       blocking=True, timeout=0.5)
            if m is None:
                continue
            self._take_position(m)
            if self._position_fresh():
                return True
        return self._position_fresh()

    def _position_fresh(self):
        now = _clock()
        return (self._pos_flags_ok and self._pos_flags_at is not None
                and self._local_at is not None
                and now - self._pos_flags_at <= POSITION_FRESH_S
                and now - self._local_at <= POSITION_FRESH_S)

    def position_text(self):
        return "indoor: position OK" if self._position_fresh() else "indoor: no position"

    def status(self):
        armed = False
        gps = "no fix"
        batt = 0.0
        hb = self.master.recv_match(type="HEARTBEAT", blocking=True, timeout=2)
        if hb:
            armed = bool(hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        g = self.master.recv_match(type="GPS_RAW_INT", blocking=True, timeout=2)
        if g:
            fixes = {0: "no gps", 1: "no fix", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK"}
            gps = fixes.get(g.fix_type, str(g.fix_type))
        s = self.master.recv_match(type="SYS_STATUS", blocking=True, timeout=2)
        if s:
            batt = round(s.voltage_battery / 1000.0, 2)
        if self.indoor:
            self.has_position()                 # refresh, so the text is current
            gps = self.position_text()
        return {"armed": armed, "gps": gps, "batt": batt, "indoor": self.indoor}

    def has_gps_fix(self):
        g = self.master.recv_match(type="GPS_RAW_INT", blocking=True, timeout=2)
        return bool(g and g.fix_type >= 3)

    def has_mission(self):
        self.master.mav.mission_request_list_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        c = self.master.recv_match(type="MISSION_COUNT", blocking=True, timeout=3)
        return bool(c and c.count > 0)

    # -- flight --
    def arm(self, timeout=8):
        """Arm, capturing PX4's own refusal text so the operator can diagnose a
        failed arm from the laptop alone (no monitor at the drone in the field)."""
        self.arm_detail = ""
        notes = []
        self.master.mav.command_long_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 0, 0, 0, 0, 0, 0)
        end = time.time() + timeout
        while time.time() < end:
            m = self.master.recv_match(
                type=["HEARTBEAT", "COMMAND_ACK", "STATUSTEXT"], blocking=True, timeout=1)
            if m is None:
                continue
            t = m.get_type()
            if t == "STATUSTEXT":
                txt = (m.text or "").strip()
                if txt and txt not in notes:
                    notes.append(txt)
            elif t == "COMMAND_ACK" and m.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
                if m.result != mavutil.mavlink.MAV_RESULT_ACCEPTED:
                    res = mavutil.mavlink.enums["MAV_RESULT"].get(m.result)
                    notes.append(res.name if res else f"result {m.result}")
            elif t == "HEARTBEAT" and (m.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED):
                self._armed = True      # seed the cache before the flight loop runs
                return True
        # keep it short: it has to fit one LoRa packet
        self.arm_detail = " | ".join(notes[-2:])[:120] or "no reason reported by PX4"
        return False

    def diagnostics(self):
        """Compact pre-flight readout for the laptop. Capped at 150 characters so
        the reply still fits one LoRa packet once signed (170 did not)."""
        bits = []
        g = self.master.recv_match(type="GPS_RAW_INT", blocking=True, timeout=3)
        if g:
            fixes = {0: "noGPS", 1: "nofix", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK"}
            bits.append(f"gps {fixes.get(g.fix_type, g.fix_type)}/{g.satellites_visible}sat")
        if self.indoor:
            self.has_position()
            bits.append("pos OK {:.2f}m".format(self._local_alt) if self._position_fresh()
                        else "NO POSITION (flow)")
        s = self.master.recv_match(type="SYS_STATUS", blocking=True, timeout=3)
        if s:
            v = s.voltage_battery / 1000.0
            bits.append(f"batt {'n/a' if s.voltage_battery == 65535 else f'{v:.1f}V'}")
            unhealthy = []
            for bit, e in mavutil.mavlink.enums["MAV_SYS_STATUS_SENSOR"].items():
                if bit and (s.onboard_control_sensors_present & bit) \
                        and (s.onboard_control_sensors_enabled & bit) \
                        and not (s.onboard_control_sensors_health & bit):
                    unhealthy.append(e.name.replace("MAV_SYS_STATUS_SENSOR_", "")
                                     .replace("MAV_SYS_STATUS_", "")[:12])
            bits.append("bad: " + ",".join(unhealthy[:3]) if unhealthy else "sensors OK")
        return " | ".join(bits)[:150] or "no telemetry"

    def disarm(self):
        self.master.mav.command_long_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 0, 0, 0, 0, 0, 0, 0)
        return True

    def set_flight_mode(self, mode):
        # mode is a px4_map key: "MISSION", "RTL", "LAND", "TAKEOFF", "OFFBOARD"
        self.master.set_mode_px4(*mavutil.px4_map[mode])
        return True

    def send_velocity(self, vx, vy, vz, yaw_rate):
        """Body-frame velocity + yaw-rate setpoint (for OFFBOARD following).
        Type mask uses vx,vy,vz and yaw_rate; ignores position, accel, and yaw."""
        self.master.mav.set_position_target_local_ned_send(
            0, self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_NED,
            0b0000011111000111,
            0, 0, 0,            # position (ignored)
            vx, vy, vz,         # velocity (forward, right, down)
            0, 0, 0,            # acceleration (ignored)
            0, yaw_rate)        # yaw (ignored), yaw_rate

    def set_takeoff_alt(self, alt_m, tries=2):
        """Tell PX4 what altitude AUTO.TAKEOFF should climb to, and confirm it.

        PX4 answers a PARAM_SET with the parameter's new value, and only that
        answer counts. Any other PARAM_VALUE, from a parameter list being sent
        to a ground station say, says nothing about this one. Unconfirmed, PX4
        may climb to whatever MIS_TAKEOFF_ALT it has stored (2.5 m by default)
        instead of the height this flight intends."""
        for _ in range(tries):
            self.master.mav.param_set_send(
                self.master.target_system, self.master.target_component,
                b"MIS_TAKEOFF_ALT", float(alt_m),
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
            end = time.time() + 3
            while time.time() < end:
                ack = self.master.recv_match(type="PARAM_VALUE", blocking=True,
                                             timeout=max(0.1, end - time.time()))
                if ack is None:
                    break
                if param_name(ack.param_id) == "MIS_TAKEOFF_ALT":
                    if abs(ack.param_value - float(alt_m)) < 0.01:
                        return True
                    break               # answered with another value: send it again
        return False

    def flight_state(self):
        """Latest armed/alt/mode. NON-blocking: the flight loop must stay
        responsive so abort and link-loss are detected promptly (and so OFFBOARD
        setpoints keep streaming above PX4's 2 Hz minimum)."""
        while True:
            msg = self.master.recv_match(
                type=["HEARTBEAT", "GLOBAL_POSITION_INT", "LOCAL_POSITION_NED",
                      "ESTIMATOR_STATUS"], blocking=False)
            if msg is None:
                break
            t = msg.get_type()
            if t == "HEARTBEAT":
                self._armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                self._mode = mavutil.mode_string_v10(msg)
            elif t == "GLOBAL_POSITION_INT":
                self._alt = round(msg.relative_alt / 1000.0, 2)
            else:
                self._take_position(msg)
        # Indoors the height comes from the local estimate (range finder, since
        # EKF2_HGT_REF=2); GLOBAL_POSITION_INT is empty without a GPS.
        alt = self._local_alt if self.indoor else getattr(self, "_alt", 0.0)
        return {"armed": getattr(self, "_armed", False),
                "alt": alt,
                "mode": getattr(self, "_mode", "?")}

    def run_mission(self, mid, motors=4):
        # Pass a PX4 refusal on, so the operator never sees "done" while nothing
        # spun. The FC's own reason is printed in the server log.
        #
        # Motor tests only. Nothing that flies runs from here: a flight is
        # prepared, launched by CONFIRM, and flown inside MonitoredFlight's
        # failsafes. Menu item 3 used to fly missions.mission_3 straight from a
        # RUN, with no CONFIRM and nothing listening for STOP or link loss.
        if mid in (1, 2):
            test = missions.mission_1 if mid == 1 else missions.mission_2
            if not test(self.master, motors):
                return False, "PX4 refused the motor test (safety? battery? armed?)"
        else:
            return False, f"mission {mid} not runnable remotely"
        return True, "done"

    def upload_waypoints(self, wps):
        """Validate waypoints, build a takeoff→waypoints→RTL mission, upload to PX4.

        Returns (accepted_count, rejected_count, note). Uploading works without a
        GPS fix (PX4 just stores the plan); it only flies once armed with a fix.
        """
        valid, rejected = [], 0
        for wp in wps:
            try:
                lat, lon, alt = float(wp[0]), float(wp[1]), float(wp[2])
            except (TypeError, ValueError, IndexError):
                rejected += 1
                continue
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180) or (lat == 0 and lon == 0):
                rejected += 1
                continue
            if not (0 < alt <= MAX_ALT_M):
                rejected += 1
                continue
            valid.append((lat, lon, alt))

        if not valid:
            return 0, rejected, "no valid waypoints (check lat/lon and 0<alt<=%g m)" % MAX_ALT_M

        items = self._build_mission(valid)
        result = self._upload_mission(items)
        if result == mavutil.mavlink.MAV_MISSION_ACCEPTED:
            return len(valid), rejected, \
                "PX4 accepted mission ({} items: takeoff + {} wp + RTL)".format(len(items), len(valid))
        name = (mavutil.mavlink.enums["MAV_MISSION_RESULT"][result].name
                if result is not None else "no MISSION_ACK (timeout)")
        return 0, len(wps), "PX4 rejected mission: {}".format(name)

    def _build_mission(self, valid):
        """takeoff (to first wp alt) -> NAV_WAYPOINTs -> RTL.

        Positional items use the global relative-alt frame; RTL has no position,
        so it must use MAV_FRAME_MISSION or PX4 rejects the whole mission as
        UNSUPPORTED. Verified on the PREVIOUS aircraft (FMUv2 / PX4 1.13.3) and
        not re-verified on this Pixhawk 6X / PX4 1.17.0 -- the waypoint flight
        has never been run on this airframe, so treat it as a carried-over
        finding rather than a current one.
        """
        REL = mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
        MISSION = mavutil.mavlink.MAV_FRAME_MISSION
        items = []

        def item(seq, cmd, frame=REL, x=0, y=0, z=0.0, p1=0, p2=0, p3=0, p4=0):
            return dict(seq=seq, frame=frame, command=cmd, current=1 if seq == 0 else 0,
                        autocontinue=1, p1=p1, p2=p2, p3=p3, p4=p4, x=x, y=y, z=z)

        seq = 0
        items.append(item(seq, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, z=valid[0][2]))
        for lat, lon, alt in valid:
            seq += 1
            items.append(item(seq, mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                              x=int(lat * 1e7), y=int(lon * 1e7), z=alt, p2=2.0))  # 2 m accept radius
        seq += 1
        items.append(item(seq, mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH, frame=MISSION))
        return items

    def _upload_mission(self, items, timeout=15):
        """Run the MAVLink mission upload handshake. Returns the MISSION_ACK type."""
        m = self.master
        m.mav.mission_count_send(m.target_system, m.target_component,
                                 len(items), mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        start = time.time()
        while time.time() - start < timeout:
            msg = m.recv_match(type=["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"],
                               blocking=True, timeout=2)
            if msg is None:
                continue
            if msg.get_type() == "MISSION_ACK":
                return msg.type
            seq = msg.seq
            if seq >= len(items):
                continue
            it = items[seq]
            m.mav.mission_item_int_send(
                m.target_system, m.target_component,
                it["seq"], it["frame"], it["command"], it["current"], it["autocontinue"],
                it["p1"], it["p2"], it["p3"], it["p4"], it["x"], it["y"], it["z"],
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        return None

    def clear_mission(self):
        """Erase the uploaded mission from the FC. Returns True if acknowledged."""
        m = self.master
        m.mav.mission_clear_all_send(m.target_system, m.target_component,
                                     mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        ack = m.recv_match(type="MISSION_ACK", blocking=True, timeout=5)
        return bool(ack and ack.type == mavutil.mavlink.MAV_MISSION_ACCEPTED)

    def close(self):
        try:
            self.master.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# The C2 server: protocol handling + mission dispatch.
# --------------------------------------------------------------------------
class C2Server:
    def __init__(self, fc, props_off=False, motors=4, log=print, indoor=False):
        self.fc = fc
        self.props_off = props_off
        self.motors = motors
        self.log = log
        # Indoor hover (ARK Flow): only the hover's gate and altitude source
        # change. Every other flight keeps its GPS gate -- their failsafe is RTL,
        # which means nothing without a global position.
        self.indoor = indoor
        # Set by serve(): whether the link signs, and its counters for the
        # diagnostics reply. Plain defaults so the tests' direct calls work.
        self.link_authenticated = None
        self.link_stats = None
        self._wp = []
        # A validated flight waiting for CONFIRM: None / "waypoints" / "mission1" /
        # "mission2" / "hover", and when it was prepared (it lapses, see confirm()).
        self._pending = None
        self._pending_at = 0.0

    def menu(self):
        return [
            {"id": 1, "name": "Sequential motor test", "needs": "props_off"},
            {"id": 2, "name": "All-motor test", "needs": "props_off"},
            {"id": 3, "name": "Fly to waypoints", "needs": "props_on", "gps": True},
            {"id": 4, "name": "Mission 1: hover + detect + land", "needs": "props_on",
             "gps": True, "fly": "mission1"},
            {"id": 5, "name": "Mission 2: follow person", "needs": "props_on",
             "gps": True, "fly": "mission2"},
            # Runtime props toggle so the state is never a hardcoded flag the
            # operator can't reach from the field (LoRa menu = numbers only).
            {"id": 6, "name": "Toggle props state (now {})".format(
                "OFF" if self.props_off else "ON"), "action": "toggle_props"},
            # Field diagnostics: with no monitor at the drone, this is how the
            # operator checks GPS/battery/sensor readiness from the laptop.
            {"id": 7, "name": "Drone status (GPS / battery / sensors)",
             "action": "diagnostics"},
            # The LoRa remote's flight (radio/firmware/Venator_Remote).
            {"id": 8, "name": "Hover 3 ft, then land", "needs": "props_on",
             "gps": True, "fly": "hover"},
        ]

    def _validate(self, mid):
        """Return (accepted, reason) for a RUN request under the safety gates."""
        item = next((i for i in self.menu() if i["id"] == mid), None)
        if item is None:
            return False, "unknown mission"
        if item.get("needs") == "props_off" and not self.props_off:
            return False, "props are ON — motor tests need props OFF"
        if item.get("needs") == "props_on" and self.props_off:
            return False, "props are OFF — flight needs props ON"
        if item.get("gps"):
            ok, reason = self._position_gate(item.get("fly"))
            if not ok:
                return False, reason
        return True, "ok"

    def _position_gate(self, fly):
        """The position a flight needs: a GPS 3D fix, or indoors, for the hover
        only, a usable ARK Flow position."""
        if self.indoor and fly == "hover":
            if not self.fc.has_position():
                return False, "no position: ARK Flow not giving PX4 a position (run drone/checks/check_flow.py)"
            return True, "ok"
        if not self.fc.has_gps_fix():
            return False, "no GPS fix"
        return True, "ok"

    # -- message handling -----------------------------------------------------
    def handle(self, msg):
        """Return a list of immediate reply messages for a non-RUN message."""
        t = msg.get("t")
        seq = msg.get("seq", 0)
        if t == p.HELLO:
            st = dict(self.fc.status())
            if self.indoor:
                st["indoor"] = True
                if hasattr(self.fc, "position_text"):
                    st["gps"] = self.fc.position_text()
                else:
                    st["gps"] = ("indoor: position OK" if self.fc.has_position()
                                 else "indoor: no position")
            if self.link_authenticated is not None:
                st["auth"] = bool(self.link_authenticated)
            return [p.message(p.HELLO_ACK, seq, proto=p.PROTO_VERSION,
                              fc=self.fc.name, props_off=self.props_off, **st)]
        if t == p.GET_MENU:
            # Stream the menu one item per packet — a full menu in a single packet
            # exceeds the LoRa limit (~255 B) and the firmware's 240-byte buffer.
            # Strip server-internal keys ("fly"/"action") to keep each packet
            # small: less airtime per item means less chance of link corruption.
            items = self.menu()
            wire = [{k: v for k, v in it.items() if k not in ("fly", "action")}
                    for it in items]
            return [p.message(p.MENU, seq, item=it, last=(i == len(wire) - 1))
                    for i, it in enumerate(wire)]
        if t == p.PING:
            return [p.message(p.PONG, seq)]
        if t == p.WP_BEGIN:
            self._wp = []
            return [p.message(p.ACK, seq, ready=True)]
        if t == p.WP:
            self._wp.append((msg.get("lat"), msg.get("lon"), msg.get("alt")))
            return [p.message(p.ACK, seq, i=msg.get("i"))]
        if t == p.WP_END:
            up, rej, note = self.fc.upload_waypoints(self._wp)
            return [p.message(p.ACK, seq, uploaded=up, rejected=rej, note=note)]
        if t == p.FLY_REQ:
            ok, reason = self._validate_fly()
            self._prepare("waypoints" if ok else None)
            return [p.message(p.ACK, seq, accepted=ok, confirm_required=ok, reason=reason)]
        if t in (p.STOP, p.ABORT) and self._armed_now():
            # In flight, STOP and ABORT are MonitoredFlight's, so one arriving here
            # means no flight loop is running, yet the aircraft is armed. That is
            # what a restart mid-flight leaves behind: an error took the old
            # server down and systemd started this one. Nothing else here will
            # bring it down, so land in place, which is what STOP means in flight.
            self._prepare(None)
            self.log(f"{t} with no flight running, but the drone is armed -> LAND")
            self.fc.set_flight_mode("LAND")
            return [p.message(p.ACK, seq, accepted=True,
                              reason="no flight running here, but the drone is armed"
                                     " — landing in place")]
        if t == p.ABORT:
            # In flight, ABORT is MonitoredFlight's. Here it is a cancelled
            # confirm screen: drop the prepared flight so nothing can launch it.
            if self._pending is None:
                return []
            self.log(f"{self._pending} cancelled before CONFIRM")
            self._prepare(None)
            return [p.message(p.ACK, seq, accepted=True, reason="cancelled — nothing will launch")]
        return []

    def _prepare(self, kind):
        """Arm the CONFIRM step for `kind` (or clear it with None)."""
        self._pending = kind
        self._pending_at = _clock()

    def _armed_now(self):
        """Whether the flight controller says it is armed. A failed read counts
        as not armed: with the FC unreachable there is nothing to command."""
        try:
            return bool(self.fc.flight_state().get("armed"))
        except Exception:
            return False

    def confirm(self, link, send):
        """CONFIRM received: launch the prepared flight, unless it has lapsed."""
        if self._pending and _clock() - self._pending_at > PENDING_CONFIRM_S:
            self.log(f"{self._pending} lapsed — CONFIRM came {PENDING_CONFIRM_S:g}+ s late")
            self._pending = None
        # The gates were last checked when this flight was *prepared*, up to
        # PENDING_CONFIRM_S ago, so re-check them before anything arms. Props can
        # be toggled inside that window (menu id 6 runs immediately, with no
        # confirm of its own) and a GPS fix can drop; on an unauthenticated link
        # anything in radio range can inject that toggle. Gating on `_pending`
        # being set, rather than on a list of flight names, keeps this closed for
        # any flight kind added later.
        if self._pending:
            ok, reason = self._validate_pending()
            if not ok:
                self.log(f"{self._pending} blocked at CONFIRM: {reason}")
                self._pending = None
                send(p.message(p.ACK, 0, accepted=False, reason=reason))
                return
        kind = self._pending
        flights = {"mission1": self.run_mission1, "mission2": self.run_mission2,
                   "hover": self.run_hover}
        try:
            # run_flight declines unless "waypoints" is pending
            flights.get(kind, self.run_flight)(link, send)
        except Exception as exc:
            self._flight_failed(kind, exc, send)

    def _flight_failed(self, kind, exc, send):
        """A flight raised. The aircraft may be in the air with nothing watching
        it, since the link-loss failsafe lived in the loop that just died. Put it
        in the failsafe that flight's ABORT uses, and say so."""
        self._pending = None
        mode = "LAND" if kind == "hover" else "RTL"
        what = MonitoredFlight._FAILSAFE_TEXT[mode]
        self.log(f"{kind}: error in flight: {exc!r} -> {mode}")
        try:
            self.fc.set_flight_mode(mode)
        except Exception as exc2:
            what = f"{mode} failed: {short_error(exc2, 30)}"   # still one radio packet
            self.log(f"{kind}: {mode} failed too: {exc2!r}")
        send(p.message(p.DONE, 0, id={"waypoints": "fly"}.get(kind, kind) or "fly",
                       result=f"FAILED: {short_error(exc)} — {what}"))

    def _validate_pending(self):
        """The gates that must still hold at CONFIRM time, for any flight.

        Deliberately not _validate_fly(): that also demands an uploaded mission,
        which only the waypoints flight has — and which, once uploaded, cannot
        be lost inside the confirm window anyway. What *can* change in that
        window is the props declaration and the GPS fix, so those are what get
        re-read here.
        """
        if self.props_off:
            return False, "props are OFF — flight needs props ON"
        ok, reason = self._position_gate(self._pending)
        if not ok:
            return False, "no GPS 3D fix" if reason == "no GPS fix" else reason
        return True, "ok"

    def _validate_fly(self):
        """Safety gate for arming and flying the uploaded mission."""
        if self.props_off:
            return False, "props are OFF — flight needs props ON"
        if not self.fc.has_gps_fix():
            return False, "no GPS 3D fix"
        if not self.fc.has_mission():
            return False, "no mission uploaded — send waypoints first"
        return True, "ready — arm + fly takeoff->waypoints->RTL"

    def run_and_report(self, msg, send):
        """Handle a RUN. Motor tests execute immediately; flight missions are
        *prepared* and wait for a CONFIRM (two-step arm)."""
        seq = msg.get("seq", 0)
        mid = msg.get("id")

        # Runtime actions (no props/GPS gate) — handled before validation.
        item0 = next((i for i in self.menu() if i["id"] == mid), {})
        if item0.get("action") == "diagnostics":
            try:
                text = self.fc.diagnostics()
            except Exception as exc:
                text = f"error reading telemetry: {short_error(exc)}"
            self.log(f"diagnostics: {text}")
            send(p.message(p.ACK, seq, id=mid, accepted=True, reason="reading telemetry"))
            if self.link_stats is not None:
                # The radio's own view, so a flaky link can be told from a flaky FC.
                send(p.message(p.LOG, 0, text=link_summary(self.link_stats())))
            send(p.message(p.DONE, seq, id=mid, result=text))
            return
        if item0.get("action") == "toggle_props":
            self.props_off = not self.props_off
            state = "OFF" if self.props_off else "ON"
            self.log(f"props state toggled -> {state}")
            send(p.message(p.ACK, seq, id=mid, accepted=True,
                           reason=f"props now {state}"))
            send(p.message(p.DONE, seq, id=mid,
                           result=f"props now {state} — "
                                  f"{'motor tests' if self.props_off else 'flight missions'} enabled"))
            return

        accepted, reason = self._validate(mid)
        if not accepted:
            send(p.message(p.ACK, seq, id=mid, accepted=False, reason=reason))
            self.log(f"RUN {mid} rejected: {reason}")
            return
        item = next((i for i in self.menu() if i["id"] == mid), {})
        fly = item.get("fly")
        if fly in ("mission1", "mission2", "hover"):
            self._prepare(fly)
            if fly == "mission1":
                reason = ("Mission 1: takeoff to {:g} m, hover {:d} s + detect people, "
                          "land in place. Confirm to launch.".format(HOVER_ALT_M, int(HOVER_TIME_S)))
            elif fly == "hover":
                reason = ("Hover: takeoff to {:g} m (3 ft), hold {:d} s, land in place. "
                          "Confirm to launch.".format(HOVER3_ALT_M, int(HOVER3_TIME_S)))
            else:
                reason = ("Mission 2: takeoff to {:g} m, then FOLLOW the person "
                          "(keep {:g} m). Send STOP to land. Confirm to launch.".format(
                              HOVER_ALT_M, FOLLOW_DIST_M))
            send(p.message(p.ACK, seq, id=mid, accepted=True, confirm_required=True, reason=reason))
            self.log(f"{fly} prepared — awaiting CONFIRM")
            return
        if item.get("needs") == "props_on":
            # Nothing that flies starts from a RUN. Flights are prepared above and
            # launched by CONFIRM, inside MonitoredFlight's failsafes. The waypoint
            # flight (item 3) has its own path, upload then FLY_REQ then CONFIRM,
            # which is how the laptop client flies it.
            send(p.message(p.ACK, seq, id=mid, accepted=False,
                           reason="send waypoints, then FLY_REQ and CONFIRM"))
            self.log(f"RUN {mid} refused: it flies, and a RUN never flies")
            return
        send(p.message(p.ACK, seq, id=mid, accepted=True, reason=reason))
        self.log(f"RUN {mid} accepted — executing")
        try:
            ok, result = self.fc.run_mission(mid, self.motors)
        except Exception as exc:
            ok, result = False, f"error: {short_error(exc)}"
        send(p.message(p.DONE, seq, id=mid, result=result if ok else f"FAILED: {result}"))

    # -- camera (person detection during Mission 1) --------------------------
    def _open_camera(self):
        """UDP socket to receive the OAK-D publisher's person X/Y/Z, or None."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setblocking(False)
            s.bind(("127.0.0.1", CAMERA_UDP_PORT))
            return s
        except OSError:
            return None

    @staticmethod
    def _read_person(sock):
        """Drain the camera socket, return the latest person dict or None."""
        if sock is None:
            return None
        latest = None
        for _ in range(20):
            try:
                data, _addr = sock.recvfrom(1024)
            except (BlockingIOError, OSError):
                break
            try:
                msg = json.loads(data.decode())
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(msg, dict):       # a person is an object; drop anything else
                latest = msg
        return latest

    @staticmethod
    def _pz(person):
        """The person's distance for STATUS, or None without a usable one (the
        OAK says 0 m when it has no depth)."""
        z = person.get("z") if person else None
        return round(z, 2) if _is_number(z) and z > 0 else None

    def _arm_and_takeoff(self, send, mission_id, title, alt_m):
        """Set the takeoff height, arm, and start AUTO.TAKEOFF to alt_m. On a
        refusal, report it (DONE) and return False -- with PX4's own words, since
        in the field nobody can see the drone's console.

        AUTO.TAKEOFF climbs to MIS_TAKEOFF_ALT, so the height is set and
        confirmed first. Unconfirmed, PX4 may use its own stored height instead
        of the one this mission intends, and checking before arming means a
        failure never leaves the drone armed on the pad."""
        try:
            if not self.fc.set_takeoff_alt(alt_m):
                self.log(f"{mission_id.upper()}: MIS_TAKEOFF_ALT not confirmed — not arming")
                send(p.message(p.DONE, 0, id=mission_id,
                               result="FAILED: takeoff height not confirmed by PX4"))
                return False
            send(p.message(p.LOG, 0, text=f"{title}: arming"))
            self.log(f"{mission_id.upper()}: arming")
            if not self.fc.arm():
                why = getattr(self.fc, "arm_detail", "") or "no reason reported"
                send(p.message(p.LOG, 0, text="PX4 refused to arm: " + why))
                send(p.message(p.DONE, 0, id=mission_id, result="FAILED: arm rejected — " + why))
                return False
            send(p.message(p.LOG, 0, text="armed — takeoff to {:g} m".format(alt_m)))
            self.fc.set_flight_mode("TAKEOFF")
        except Exception as exc:
            send(p.message(p.DONE, 0, id=mission_id, result=f"FAILED: {short_error(exc)}"))
            return False
        return True

    def run_mission1(self, link, send):
        """Mission 1: arm -> takeoff -> hover HOVER_TIME_S while reporting detected
        people -> land in place. Same link-loss RTL / abort failsafes as run_flight."""
        if self._pending != "mission1":
            send(p.message(p.ACK, 0, accepted=False, reason="no confirmed flight pending"))
            return
        self._pending = None
        cam = self._open_camera()

        if not self._arm_and_takeoff(send, "mission1", "Mission 1", HOVER_ALT_M):
            if cam:
                cam.close()
            return

        hover_start = None
        people_seen = 0
        person_present = False
        last_person_at = None
        flight = MonitoredFlight(self, link, send, "mission1", "MISSION1",
                                 phase="takeoff",
                                 on_close=lambda: cam.close() if cam else None)
        for now, st in flight.ticks():
            person = self._read_person(cam)
            if person is not None:
                # Count a new person only after a real gap. This used to
                # increment on every rising edge, so one person the detector
                # dropped for a single frame - which it does routinely at
                # 10 fps - was counted again on the next hit, and a count of
                # "4 people" could be one person standing still.
                #
                # CAMERA_LOSS_S has been declared since this mission was
                # written and never referenced; this is the grace period it
                # was for.
                if last_person_at is None or now - last_person_at > CAMERA_LOSS_S:
                    people_seen += 1
                last_person_at = now
                person_present = True
            else:
                # Hold `present` across a brief dropout too, so the telemetry
                # and the hover logic do not flap in step with the detector.
                person_present = (last_person_at is not None
                                  and now - last_person_at <= CAMERA_LOSS_S)

            if flight.flying:
                if flight.phase == "takeoff" and st["alt"] >= HOVER_ALT_M * 0.9:
                    flight.phase = "hover"
                    hover_start = now
                    send(p.message(p.LOG, 0, text="hovering — detecting people"))
                elif (flight.phase == "hover" and hover_start
                      and now - hover_start > HOVER_TIME_S):
                    flight.phase = "land"
                    self.fc.set_flight_mode("LAND")
                    send(p.message(p.LOG, 0, text="hover complete — landing in place"))

            flight.extra = {"person": person_present, "seen": people_seen,
                            "pz": self._pz(person)}

        if flight.timed_out:
            send(p.message(p.DONE, 0, id="mission1", result="time cap -> RTL"))
            return
        send(p.message(p.DONE, 0, id="mission1",
                       result="landed & disarmed — {} person-detection(s){}".format(
                           people_seen, " (RTL)" if flight.rtl else "")))
        self.log("MISSION1: landed & disarmed")

    @staticmethod
    def _follow_setpoint(person):
        """person X (right+)/Z (forward dist) -> (vx forward, yaw_rate). vz=0 (hold alt).

        No depth, no setpoint. The OAK reports 0 m for a person it has no depth
        for, and camera_publisher passes that on. Read as a distance, 0 m is
        "too close", which sent the drone backwards, blind, for as long as the
        depth stayed missing. x comes from the same depth reading, so it is no
        use either: hold still, as with nobody in view."""
        z, x = person.get("z"), person.get("x", 0.0)
        if not _is_number(z) or not z > 0:
            return 0.0, 0.0
        if not _is_number(x):
            x = 0.0
        vx = 0.0
        if z > FOLLOW_DIST_M + FOLLOW_DIST_DEAD:
            vx = FOLLOW_FWD_MPS
        elif z < FOLLOW_DIST_M - FOLLOW_DIST_DEAD:
            vx = -FOLLOW_FWD_MPS
        yaw = 0.0
        if x > FOLLOW_X_DEAD:
            yaw = FOLLOW_YAW_RPS
        elif x < -FOLLOW_X_DEAD:
            yaw = -FOLLOW_YAW_RPS
        return vx, yaw

    def run_mission2(self, link, send):
        """Mission 2: arm -> takeoff -> OFFBOARD follow the person, keeping
        FOLLOW_DIST_M, until the client sends STOP (land) / ABORT (RTL) / link loss
        (RTL). No person in view -> hover in place (never drift)."""
        if self._pending != "mission2":
            send(p.message(p.ACK, 0, accepted=False, reason="no confirmed flight pending"))
            return
        self._pending = None
        cam = self._open_camera()

        if not self._arm_and_takeoff(send, "mission2", "Mission 2", HOVER_ALT_M):
            if cam:
                cam.close()
            return

        offboard = False
        flight = MonitoredFlight(self, link, send, "mission2", "MISSION2",
                                 allow_stop=True, tick=0.1, phase="takeoff",
                                 on_close=lambda: cam.close() if cam else None)
        for now, st in flight.ticks():
            person = self._read_person(cam)
            following = False
            if flight.flying:
                # once at altitude, enter OFFBOARD and stream velocity setpoints
                if not offboard and st["alt"] >= HOVER_ALT_M * 0.9:
                    for _ in range(10):
                        self.fc.send_velocity(0, 0, 0, 0)
                        time.sleep(0.02)
                    self.fc.set_flight_mode("OFFBOARD")
                    offboard = True
                    send(p.message(p.LOG, 0, text="following — send STOP to land"))
                if offboard:
                    if person is not None:
                        vx, yaw = self._follow_setpoint(person)
                        following = True
                    else:
                        vx, yaw = 0.0, 0.0        # no person -> hover, don't drift
                    self.fc.send_velocity(vx, 0, 0, yaw)

            flight.phase = "follow" if offboard else "takeoff"
            flight.extra = {"person": person is not None, "following": following,
                            "pz": self._pz(person)}

        if flight.timed_out:
            send(p.message(p.DONE, 0, id="mission2", result="time cap -> RTL"))
            return
        how = {"STOP": "landed (stopped)", "ABORT": "landed (RTL)",
               "LINKLOSS": "landed (link-loss RTL)"}.get(flight.ending, "landed & disarmed")
        send(p.message(p.DONE, 0, id="mission2", result=how))
        self.log("MISSION2: landed & disarmed")

    def run_hover(self, link, send):
        """Hover 3 ft: arm -> takeoff to HOVER3_ALT_M -> hold HOVER3_TIME_S ->
        land in place. STOP lands early. Link loss, ABORT and the time cap all
        LAND rather than RTL -- see HOVER3_ALT_M."""
        if self._pending != "hover":
            send(p.message(p.ACK, 0, accepted=False, reason="no confirmed flight pending"))
            return
        self._pending = None
        if not self._arm_and_takeoff(send, "hover", "Hover", HOVER3_ALT_M):
            return

        climb_start = _clock()
        hold_start = None
        flight = MonitoredFlight(self, link, send, "hover", "HOVER",
                                 allow_stop=True, failsafe="LAND", phase="takeoff")
        for now, st in flight.ticks():
            if not flight.flying:
                continue
            if flight.phase == "takeoff":
                if st["alt"] >= HOVER3_ALT_M * 0.9:
                    flight.phase = "hover"
                    hold_start = now
                    send(p.message(p.LOG, 0, text="at {:g} m — holding {:d} s".format(
                        HOVER3_ALT_M, int(HOVER3_TIME_S))))
                elif now - climb_start > HOVER3_CLIMB_S:
                    flight.phase = "land"
                    self.fc.set_flight_mode("LAND")
                    send(p.message(p.LOG, 0, text="never reached {:g} m — landing".format(
                        HOVER3_ALT_M)))
            elif flight.phase == "hover" and now - hold_start > HOVER3_TIME_S:
                flight.phase = "land"
                self.fc.set_flight_mode("LAND")
                send(p.message(p.LOG, 0, text="hold complete — landing in place"))

        if flight.timed_out:
            send(p.message(p.DONE, 0, id="hover", result="time cap -> LAND"))
            return
        how = {"STOP": "landed (stopped early)", "ABORT": "landed (aborted)",
               "LINKLOSS": "landed (link lost)"}.get(flight.ending, "landed & disarmed")
        send(p.message(p.DONE, 0, id="hover", result=how))
        self.log("HOVER: " + how)

    def run_flight(self, link, send):
        """CONFIRM received: arm + AUTO.MISSION, then monitor with a link-loss
        RTL failsafe until the drone lands and disarms. `link` is polled for the
        client's in-flight pings and ABORT; `send` pushes status/log back."""
        if self._pending != "waypoints":
            send(p.message(p.ACK, 0, accepted=False, reason="no confirmed flight pending"))
            return
        self._pending = None

        send(p.message(p.LOG, 0, text="arming..."))
        self.log("FLIGHT: arming")
        try:
            if not self.fc.arm():
                why = getattr(self.fc, "arm_detail", "") or "no reason reported"
                send(p.message(p.LOG, 0, text="PX4 refused to arm: " + why))
                send(p.message(p.DONE, 0, id="fly", result="FAILED: arm rejected — " + why))
                return
            send(p.message(p.LOG, 0, text="armed — AUTO.MISSION, taking off"))
            self.log("FLIGHT: armed, AUTO.MISSION")
            self.fc.set_flight_mode("MISSION")
        except Exception as exc:
            send(p.message(p.DONE, 0, id="fly", result=f"FAILED: {short_error(exc)}"))
            return

        flight = MonitoredFlight(self, link, send, "fly", "FLIGHT")
        for _now, _st in flight.ticks():
            pass                               # nothing mission-specific to do

        if flight.timed_out:
            send(p.message(p.DONE, 0, id="fly", result="flight time cap -> RTL"))
            return
        send(p.message(p.DONE, 0, id="fly",
                       result="landed & disarmed" + (" (RTL)" if flight.rtl else "")))
        self.log("FLIGHT: landed & disarmed")


class MonitoredFlight:
    """Everything that must be true on every tick of a flight, in one place.

    The missions differ in what they ask the aircraft to do. They do not differ
    in how a flight is watched: answer PINGs, honour ABORT, fail safe if the
    link goes quiet (RTL, or LAND where RTL would climb), push a status
    heartbeat, stop when it disarms, and give up at the time cap. That was
    written out three times, which is how failsafes
    drift apart. This repo has already paid for the same mistake once -- the
    serial transport was copied three times and grew three different bugs.

    Use it as the loop, and do the mission's own work in the body:

        flight = MonitoredFlight(self, link, send, "mission1", "MISSION1")
        for now, st in flight.ticks():
            ...                       # st is the current flight state
            flight.phase = "hover"    # shown in STATUS
            flight.extra = {...}      # extra STATUS fields
        if flight.timed_out: ...

    LINK_LOSS_S, STATUS_INTERVAL_S and FLIGHT_MAX_S are read from the module at
    run time, not captured, because the tests set them.
    """

    # What each failsafe mode does, as the operator reads it on the link.
    _FAILSAFE_TEXT = {"RTL": "returning home", "LAND": "landing in place"}

    def __init__(self, server, link, send, mission_id, log_tag, *,
                 allow_stop=False, tick=0.15, on_close=None, failsafe="RTL",
                 phase=None):
        self.server, self.link, self.send = server, link, send
        self.mission_id, self.log_tag = mission_id, log_tag
        self.allow_stop, self.tick, self.on_close = allow_stop, tick, on_close
        self.failsafe = failsafe    # flight mode for ABORT, link loss and the time cap
        self.rtl = False
        self.ending = None          # None -> flying; "STOP"/"ABORT"/"LINKLOSS"
        # Only missions that have phases report one. A waypoint flight has no
        # phases, and the client renders the field whenever it is present -- so
        # sending a phase it never updates would show "takeoff" for the whole
        # flight, including while the aircraft is halfway round the route.
        self.phase = phase
        self._report_phase = phase is not None
        self.extra = {}
        self.timed_out = False
        self._last_ping = _clock()
        self._last_status = 0.0
        self._deadline = _clock() + FLIGHT_MAX_S

    @property
    def flying(self):
        """True while nothing has ended the flight — guard mission work with it."""
        return self.ending is None

    def _close(self):
        if self.on_close:
            self.on_close()

    def _go_home(self, why):
        self.server.log(f"{self.log_tag}: {why} -> {self.failsafe}")
        self.send(p.message(p.LOG, 0, text=f"{why} — {self._FAILSAFE_TEXT[self.failsafe]}"))
        self.server.fc.set_flight_mode(self.failsafe)
        self.rtl = self.failsafe == "RTL"

    def _status(self, now, st):
        fields = dict(self.extra)
        if self._report_phase:
            fields["phase"] = ("RTL" if self.rtl else (self.ending or self.phase))
        self.send(p.message(p.STATUS, 0, rtl=self.rtl, **fields, **st))
        self._last_status = now

    def ticks(self):
        while _clock() < self._deadline:
            now = _clock()
            # Drain what has queued, not one line a tick: PINGs that piled up
            # during a blocking arm() used to be read one per tick afterwards,
            # so a link that died during arming looked alive for seconds.
            pinged = False
            for _ in range(DRAIN_PER_TICK):
                msg = self.link.poll()
                if not msg:
                    break
                mt = msg.get("t")
                if mt == p.PING:
                    self._last_ping = now
                    pinged = True
                    self.send(p.message(p.PONG, msg.get("seq", 0)))
                elif mt == p.STOP and self.allow_stop and self.ending is None:
                    self.ending = "STOP"
                    self.server.log(f"{self.log_tag}: STOP -> LAND")
                    self.send(p.message(p.LOG, 0, text="STOP — landing in place"))
                    self.server.fc.set_flight_mode("LAND")
                elif mt == p.ABORT and self.ending is None:
                    self.ending = "ABORT"
                    self._go_home("ABORT")
            if self.ending is None and now - self._last_ping > LINK_LOSS_S:
                self.ending = "LINKLOSS"
                self._go_home("LINK LOST")

            st = self.server.fc.flight_state()
            yield now, st                      # the mission does its own work here

            # STATUS rides on the PONG: the radio is half-duplex and the ground
            # has just finished talking, so this is the moment it is listening.
            # Two free-running 1 s timers (its PING, our STATUS) used to collide
            # a third of the time. Unsolicited only after the ground has been
            # quiet for two intervals, so a remote that pings every 5 s still
            # sees status.
            # 0.8 x, not 1 x: the ground's pings come every STATUS_INTERVAL_S
            # too, and judging "due" against the same period would skip every
            # other one.
            due = now - self._last_status
            if (pinged and due >= 0.8 * STATUS_INTERVAL_S) or due >= 2 * STATUS_INTERVAL_S:
                self._status(now, st)

            if not st["armed"]:                # it landed and disarmed
                self._close()
                return
            time.sleep(self.tick)

        self.timed_out = True
        self._close()
        self.server.log(f"{self.log_tag}: time cap reached -> {self.failsafe}")
        self.server.fc.set_flight_mode(self.failsafe)


# --------------------------------------------------------------------------
# LoRa serial transport (transparent line bridge on the other end).
# --------------------------------------------------------------------------
class LoRaLink(SerialLink):
    """The Jetson's link. Drops outbound messages while the stick is away
    rather than raising: the server loop has to keep running so it can answer
    once the stick is back.

    defer_open for the same reason, extended to startup. As a boot service this
    races USB enumeration -- the Pixhawk on this airframe has taken minutes to
    appear -- and raising here meant exit 1, which under Restart=on-failure with
    StartLimitIntervalSec=0 is a restart every RestartSec forever rather than a
    wait. port_finder so the retry re-resolves instead of hammering one path."""

    def __init__(self, port, baud, port_finder=find_lora_device):
        super().__init__(port, baud, raise_on_down=False, settle=DEFAULT_SETTLE_S,
                         defer_open=True, port_finder=port_finder,
                         log=lambda m: print(m, flush=True))


def link_summary(stats):
    """One short line of link counters, for the journal and the LOG reply."""
    if not stats:
        return "link: no counters"
    bits = ["link: rx {rx} bad {rx_bad} rej {rx_rejected} tx {tx} drop {tx_dropped}".format(**stats)]
    if stats.get("rssi") is not None:
        bits.append("rssi {} snr {}".format(stats["rssi"], stats.get("snr")))
    if stats.get("last_rx_s") is not None:
        bits.append("heard {:.0f}s ago".format(stats["last_rx_s"]))
    return " ".join(bits)[:ERROR_TEXT_MAX + 40]


class Dedupe:
    """Replies to the last few commands, by (type, seq), so a retransmitted
    command is answered from here and never acted on twice.

    The clients retransmit RUN, FLY_REQ, WP_* and CONFIRM when no reply comes
    back in time; without this, a lost ACK meant a motor test ran twice. Only
    the first DEDUPE_REPLIES replies are kept: a flight's whole LOG/STATUS
    stream is not something to replay."""

    KINDS = (p.RUN, p.CONFIRM, p.FLY_REQ, p.WP_BEGIN, p.WP, p.WP_END)

    def __init__(self):
        self._seen = {}

    def key(self, msg):
        t, seq = msg.get("t"), msg.get("seq")
        if t not in self.KINDS or not isinstance(seq, int) or seq <= 0:
            return None                 # seq 0 carries no identity
        return (t, seq)

    def replay(self, key):
        """The cached replies for key, or None if it is new (or lapsed)."""
        hit = self._seen.get(key)
        if hit is None or _clock() - hit[0] > DEDUPE_S:
            return None
        return hit[1]

    def recorder(self, key, send):
        """A send() that also files the first few replies under key."""
        replies = []
        self._seen[key] = (_clock(), replies)
        if len(self._seen) > 64:
            for k in sorted(self._seen, key=lambda k: self._seen[k][0])[:-32]:
                del self._seen[k]

        def record(m):
            if len(replies) < DEDUPE_REPLIES and m.get("t") != p.STATUS:
                replies.append(m)
            return send(m)
        return record


def serve(server, link, log=print):
    """Main loop: pump protocol messages between the LoRa link and the server."""
    log(f"C2 server up ({server.fc.name} FC, props {'OFF' if server.props_off else 'ON'}). "
        f"Waiting for the laptop...")
    if getattr(link, "authenticated", False):
        log("Link authenticated - unsigned commands will be ignored.")
    else:
        log("WARNING: the command link is NOT authenticated. Anything in radio "
            "range that speaks this protocol can command this aircraft. "
            "Run 'python3 radio/auth.py --init' on both machines. "
            "See docs/SECURITY.md.")
    server.link_authenticated = bool(getattr(link, "authenticated", False))
    stats = getattr(link, "stats", None)
    if callable(stats):
        server.link_stats = stats
    if server.indoor:
        log("Indoor mode: the hover (menu 8) is gated on an ARK Flow position, not GPS.")
    dedupe = Dedupe()
    # A flight's DONE is sent once, at the end, and the air can lose it; the
    # ground then waits for a result that never comes. The ground keeps
    # pinging after the flight, so the DONE is repeated with the next PONGs.
    last_done = {"msg": None, "at": 0.0, "n": 0}

    def tx(m):
        if m.get("t") == p.DONE and m.get("seq", 0) == 0:
            last_done.update(msg=m, at=_clock(), n=0)
        return link.send(m)
    last_rx = _clock()
    quiet_reported = False
    last_stats = _clock()
    while True:
        t = None
        try:
            msg = link.poll()
            if msg is None:
                now = _clock()
                if not quiet_reported and now - last_rx > QUIET_REPORT_S:
                    log(f"no traffic from the ground for {QUIET_REPORT_S:g} s "
                        f"({link_summary(stats() if callable(stats) else None)})")
                    quiet_reported = True
                time.sleep(0.02)
                continue
            last_rx = _clock()
            if quiet_reported:
                log("the ground is back")
                quiet_reported = False
            if callable(stats) and last_rx - last_stats > STATS_REPORT_S:
                log(link_summary(stats()))
                last_stats = last_rx
            t = msg.get("t")
            key = dedupe.key(msg)
            if key is not None:
                replay = dedupe.replay(key)
                if replay is not None:
                    log(f"{t} seq {key[1]} again - answering from the cache, not running it twice")
                    for reply in replay:
                        link.send(reply)
                    continue
                send = dedupe.recorder(key, tx)
            else:
                send = tx
            if t == p.RUN:
                server.run_and_report(msg, send)
            elif t == p.CONFIRM:
                server.confirm(link, send)
            else:
                for reply in server.handle(msg):
                    send(reply)
                if (t == p.PING and last_done["msg"] is not None
                        and last_done["n"] < DONE_REPEATS
                        and _clock() - last_done["at"] < DONE_REPEAT_S):
                    last_done["n"] += 1
                    link.send(last_done["msg"])
        except Exception as exc:
            # One bad message must not take the server down. Exiting is a restart
            # under systemd, and the new server knows nothing of a flight this
            # one was running, so the failsafes would go with it. poll() is
            # inside the try for the same reason: a garbled packet used to
            # escape it.
            log(f"error handling {t!r}: {exc!r}")


def wait_for_fc(link, args):
    """Retry the Pixhawk connection forever. While it's missing, keep answering
    the LoRa link so the operator sees WHY the drone isn't ready (instead of
    silence when the Pixhawk USB is unplugged or still booting)."""
    last_note = 0.0
    while True:
        device = find_fc_device() if args.fc_device == "auto" else args.fc_device
        try:
            print("FC device: {}".format(device), flush=True)
            return RealFC(device, args.fc_baud, indoor=getattr(args, "indoor", False))
        except SystemExit:
            pass  # missions.connect() exits on no-heartbeat; treat as retry
        except Exception as exc:
            print("FC connect failed: {}".format(exc), flush=True)
        if _clock() - last_note > 30:
            print("Pixhawk not connected — retrying every 5 s...", flush=True)
            last_note = _clock()
        end = _clock() + 5
        while _clock() < end:
            try:
                msg = link.poll()
                if msg is None:
                    time.sleep(0.05)
                    continue
                t = msg.get("t")
                seq = msg.get("seq", 0)
                if t == p.HELLO:
                    link.send(p.message(p.HELLO_ACK, seq, proto=p.PROTO_VERSION,
                                        fc="disconnected", props_off=True,
                                        armed=False, gps="n/a", batt=0,
                                        auth=bool(getattr(link, "authenticated", False))))
                    link.send(p.message(p.LOG, 0,
                                        text="Pixhawk NOT connected to the Jetson — check its USB cable"))
                elif t == p.PING:
                    link.send(p.message(p.PONG, seq))
                elif t == p.GET_MENU:
                    link.send(p.message(p.MENU, seq, item=None, last=True))
                    link.send(p.message(p.LOG, 0, text="no missions — Pixhawk not connected"))
            except Exception as exc:
                print("error on the link while waiting for the FC: {!r}".format(exc), flush=True)


def main():
    ap = argparse.ArgumentParser(description="Venator Jetson C2 server")
    ap.add_argument("--lora-port", default="auto",
                    help="LoRa stick serial port, or 'auto' to detect by stable ID")
    ap.add_argument("--lora-baud", type=int, default=115200)
    ap.add_argument("--fc-device", default="auto",
                    help="Pixhawk serial port, or 'auto' to detect by stable ID")
    ap.add_argument("--fc-baud", type=int, default=115200)
    ap.add_argument("--motors", type=int, default=4,
                    help="motor count (Holybro X500 V2 quad = 4)")
    ap.add_argument("--real", action="store_true",
                    help="connect the real Pixhawk (default is a safe mock FC)")
    # Props are ON by default: once the aircraft is in flight testing they stay
    # fitted, and the operator can't edit flags from the field. Motor tests are
    # then blocked (correct — never spin props by hand); flip state at runtime
    # from the laptop with the "Toggle props" menu item, or start with --props-off.
    ap.add_argument("--props-off", action="store_true",
                    help="declare props OFF (enables motor tests, blocks flight)")
    ap.add_argument("--props-on", action="store_true",
                    help="(default) declare props ON — kept for compatibility")
    # Indoor hover for the symposium: PX4 gets its position from the ARK Flow
    # (optical flow + range finder, drone/checks/check_flow.py), not GPS. Only
    # the hover's gate and altitude source change; see C2Server.indoor.
    ap.add_argument("--indoor", action="store_true",
                    help="gate the hover (menu 8) on an ARK Flow position instead of a GPS fix")
    args = ap.parse_args()

    # Line-buffer stdout so logs reach the journal immediately under systemd.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass

    # Open the LoRa link FIRST so the operator gets answers even when the
    # flight controller is missing (previously this crash-looped in silence).
    lora_port = find_lora_device() if args.lora_port == "auto" else args.lora_port
    print("LoRa device: {}".format(lora_port), flush=True)
    # An explicit port is the operator's word: only 'auto' re-detects the stick
    # when its node cannot be opened.
    port_finder = find_lora_device if args.lora_port == "auto" else None
    # LoRaLink defers its first open, so an absent or still-enumerating stick is
    # a wait rather than exit 1. Exiting here was a crash-loop under systemd:
    # Restart=on-failure with StartLimitIntervalSec=0 retried every 5 s forever,
    # which is how a demo loses the command link to a slow USB port.
    link = LoRaLink(lora_port, args.lora_baud, port_finder=port_finder)
    if not link.up:
        print("LoRa stick not there yet — the server is up and will attach to "
              "it as soon as it appears.", flush=True)

    if args.real:
        if missions is None:
            sys.exit("pymavlink/missions unavailable — run with the venv, or drop --real")
        fc = wait_for_fc(link, args)
    else:
        fc = MockFC()

    server = C2Server(fc, props_off=args.props_off, motors=args.motors, indoor=args.indoor)

    try:
        serve(server, link)
    except KeyboardInterrupt:
        print("\nC2 server stopped.")
    finally:
        link.close()
        fc.close()


if __name__ == "__main__":
    main()
