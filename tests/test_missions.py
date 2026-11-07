#!/usr/bin/env python3
"""
Regression tests for the flight missions (mock flight controller — nothing flies).

    ./venv/bin/python test_missions.py

Covers the paths that must not break before a field test:
  * menu integrity + packet sizes small enough for the LoRa firmware buffer
  * props interlock (flight vs motor tests) and the runtime props toggle
  * Mission 1: takeoff -> hover + person detection -> land
  * Mission 2: takeoff -> OFFBOARD follow -> STOP -> land
  * link-loss -> RTL failsafe on both missions
  * Hover 3 ft: gates, confirm cancel/expiry, LAND (never RTL) failsafes
  * a RUN never flies; a 0 m (no depth) reading never moves the drone
  * an error mid-flight triggers the failsafe and the server lives on; STOP
    lands an armed drone no flight loop is watching
  * the takeoff height is confirmed before arming
  * every reply fits the radio's 240 characters once signed
  * the old menu's radio listener cannot fly
  * client tolerates corrupted menu packets instead of crashing
"""
import json
import socket
import sys
import threading
import time
from pathlib import Path


# Runnable from any folder: put the repo root on the import path so the
# sibling packages (radio/, drone/, ground/) import the same modules
# whether this is started by path, by a desktop launcher or by systemd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radio import protocol as c2
from ground import gcs_client as gc
from drone import c2_server as srv

FAILURES = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + (f"   {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


class FakeLink:
    """Stands in for the LoRa link. Pings for `ping_for` s, then goes silent.
    Optionally injects a STOP after `stop_at` seconds."""

    def __init__(self, ping_for=100.0, stop_at=None):
        self.t0 = time.time()
        self.ping_for = ping_for
        self.stop_at = stop_at
        self.sent = []
        self._stopped = False

    def poll(self):
        el = time.time() - self.t0
        if self.stop_at is not None and el > self.stop_at and not self._stopped:
            self._stopped = True
            return c2.message(c2.STOP, 0)
        return c2.message(c2.PING, 0) if el < self.ping_for else None

    def send(self, m):
        self.sent.append(m)

    def texts(self):
        return [m.get("text", "") for m in self.sent if m["t"] == c2.LOG]

    def phases(self):
        out = []
        for m in self.sent:
            if m["t"] == c2.STATUS and m.get("phase") not in out:
                out.append(m.get("phase"))
        return out

    def done(self):
        d = [m for m in self.sent if m["t"] == c2.DONE]
        return d[-1]["result"] if d else None


def person_injector(stop_evt):
    """Publish OAK-D-style person packets to the camera UDP port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while not stop_evt.is_set():
        s.sendto(json.dumps({"x": 0.5, "y": 0.0, "z": 4.0, "conf": 0.9}).encode(),
                 ("127.0.0.1", srv.CAMERA_UDP_PORT))
        time.sleep(0.1)
    s.close()


def make_server(gps=True, props_off=False, mission=False):
    # Sample status faster than the default 1 s so short test flights capture
    # every phase transition.
    srv.STATUS_INTERVAL_S = 0.25
    fc = srv.MockFC(gps=gps)
    if mission:
        fc.upload_waypoints([(37.42, -122.08, 5.0)])
    return srv.C2Server(fc, props_off=props_off)


# --------------------------------------------------------- shared failsafe loop
def test_monitored_flight():
    """MonitoredFlight is now the only failsafe loop, so all three missions
    inherit whatever it does. That makes it worth testing head-on — especially
    STOP, which it understands but which most missions must ignore."""
    print("\n[shared failsafe loop]")

    # Globals are restored afterwards so this test cannot change how the ones
    # after it behave.
    hover_was, cap_was = srv.HOVER_TIME_S, srv.FLIGHT_MAX_S
    try:
        # A mission 1 that correctly ignores STOP runs to its hover timeout, so
        # shorten it — on the default 60 s this one check costs a minute.
        srv.HOVER_TIME_S = 1.0

        # STOP must land mission 2 and be ignored by everything else. If the
        # allow_stop gate were wrong, a STOP would put a flying aircraft into
        # LAND during a mission that never offered STOP as an option.
        _, link = run_mission(2, stop_at=0.3)
        check("mission 2 honours STOP", "stopped" in (link.done() or ""), link.done())
        _, link = run_mission(1, stop_at=0.3)
        check("mission 1 ignores STOP", "stopped" not in (link.done() or ""), link.done())

        s = make_server()
        s.props_off = False
        link = FakeLink(ping_for=100.0)
        real_poll, sent_abort = link.poll, []

        def abort_after_a_moment():
            if time.time() - link.t0 > 0.3 and not sent_abort:
                sent_abort.append(True)
                return c2.message(c2.ABORT, 0)
            return real_poll()

        link.poll = abort_after_a_moment
        s._pending = "mission1"
        srv.HOVER_TIME_S = 30.0      # long enough that ABORT is what ends it
        s.run_mission1(link, link.send)
        check("ABORT returns home", "RTL" in (link.done() or ""), link.done())
        check("and says so on the link",
              any("ABORT" in t for t in link.texts()), str(link.texts()[:3]))

        # The time cap is the backstop when nothing else fires. run_flight is
        # gated on an uploaded mission, so this needs _pending "waypoints" --
        # anything else and it declines before it ever reaches the loop.
        s2 = make_server(mission=True)
        s2.props_off = False
        s2._pending = "waypoints"
        quiet = FakeLink(ping_for=100.0)
        srv.FLIGHT_MAX_S = 1.5       # long enough to arm, short enough to cap
        s2.run_flight(quiet, quiet.send)
        check("time cap ends the flight", "time cap" in (quiet.done() or ""), quiet.done())
        # A waypoint flight has no phases. The client renders whatever phase it
        # is sent, so one it never updates would read "takeoff" all the way
        # round the route.
        check("waypoint flight sends no phase field",
              not any("phase" in m for m in quiet.sent if m["t"] == c2.STATUS),
              str([m for m in quiet.sent if m["t"] == c2.STATUS][:1]))
    finally:
        srv.HOVER_TIME_S, srv.FLIGHT_MAX_S = hover_was, cap_was


# ---------------------------------------------------------------- menu / packets
def test_menu():
    print("\n[menu + LoRa packet safety]")
    s = make_server()
    msgs = s.handle(c2.message(c2.GET_MENU, 1))
    sizes = [len(c2.encode(m)) for m in msgs]
    check("every menu item has id and name",
          all(isinstance(m["item"].get("id"), int)
              and isinstance(m["item"].get("name"), str) for m in msgs))
    check("exactly one packet flagged last",
          sum(1 for m in msgs if m.get("last")) == 1)
    check("each packet < 200 B (firmware buffer is ~256 B)",
          max(sizes) < 200, f"largest {max(sizes)} B")
    check("no server-internal keys leak to the wire",
          not any(k in m["item"] for m in msgs for k in ("fly", "action")))
    check("sends are paced to avoid buffer overflow",
          srv.LoRaLink.MIN_SEND_GAP_S >= 0.2, f"{srv.LoRaLink.MIN_SEND_GAP_S}s gap")


# ---------------------------------------------------------------- props gating
def test_props():
    print("\n[props interlock + runtime toggle]")
    s = make_server(props_off=False)
    check("props default to ON (flight ready out of the box)", s.props_off is False)
    for mid, label in ((4, "Mission 1"), (5, "Mission 2")):
        out = []
        s.run_and_report(c2.message(c2.RUN, 1, id=mid), out.append)
        check(f"{label} accepted with props ON", out[-1].get("accepted") is True,
              out[-1].get("reason", "")[:44])
    out = []
    s.run_and_report(c2.message(c2.RUN, 1, id=1), out.append)
    check("motor test refused with props ON", out[-1].get("accepted") is False)
    out = []
    s.run_and_report(c2.message(c2.RUN, 1, id=6), out.append)
    check("props toggle flips state", s.props_off is True, out[-1].get("result", ""))
    out = []
    s.run_and_report(c2.message(c2.RUN, 1, id=4), out.append)
    check("Mission 1 refused after toggling props OFF", out[-1].get("accepted") is False)


def test_fly_gates():
    print("\n[waypoint flight gates]")
    cases = [
        (make_server(gps=False, props_off=True, mission=True), "props OFF"),
        (make_server(gps=False, props_off=False, mission=True), "no GPS"),
        (make_server(gps=True, props_off=False, mission=False), "no mission uploaded"),
    ]
    for s, why in cases:
        r = s.handle(c2.message(c2.FLY_REQ, 1))[0]
        check(f"FLY_REQ refused: {why}", r.get("accepted") is False, r.get("reason", ""))
    s = make_server(gps=True, props_off=False, mission=True)
    r = s.handle(c2.message(c2.FLY_REQ, 1))[0]
    check("FLY_REQ accepted when all conditions met", r.get("accepted") is True)
    check("acceptance demands a second confirmation", r.get("confirm_required") is True)


# ---------------------------------------------------------------- missions
def run_mission(which, ping_for=100.0, stop_at=None, people=True):
    s = make_server()
    out = []
    s.run_and_report(c2.message(c2.RUN, 1, id=4 if which == 1 else 5), out.append)
    link = FakeLink(ping_for=ping_for, stop_at=stop_at)
    stop_evt = threading.Event()
    if people:
        threading.Thread(target=person_injector, args=(stop_evt,), daemon=True).start()
    (s.run_mission1 if which == 1 else s.run_mission2)(link, link.send)
    stop_evt.set()
    return s, link


def test_mission1():
    print("\n[Mission 1: hover + detect + land]")
    srv.HOVER_TIME_S = 2.0
    s, link = run_mission(1)
    check("phases takeoff -> hover -> land",
          link.phases() == ["takeoff", "hover", "land"], str(link.phases()))
    check("PX4 told the intended takeoff altitude",
          getattr(s.fc, "_takeoff_alt", None) == srv.HOVER_ALT_M,
          f"MIS_TAKEOFF_ALT={getattr(s.fc, '_takeoff_alt', None)}")
    check("people were detected and counted",
          any(m.get("seen", 0) > 0 for m in link.sent if m["t"] == c2.STATUS))
    check("ends landed & disarmed", "landed" in (link.done() or ""), link.done())

    print("\n[Mission 1: link lost mid-flight]")
    srv.LINK_LOSS_S = 2.0
    _, link = run_mission(1, ping_for=1.0)
    check("link loss announced", any("LINK LOST" in t for t in link.texts()))
    check("returned home (RTL)", "RTL" in (link.done() or ""), link.done())


def test_mission2():
    print("\n[Mission 2: follow person]")
    for x, z, wvx, wyaw in ((0.0, 4.0, +1, 0), (0.0, 2.0, -1, 0),
                            (0.0, 3.0, 0, 0), (0.6, 3.0, 0, +1), (-0.6, 3.0, 0, -1)):
        vx, yaw = srv.C2Server._follow_setpoint({"x": x, "z": z})
        ok = ((vx > 0) == (wvx > 0)) and ((vx < 0) == (wvx < 0)) \
             and ((yaw > 0) == (wyaw > 0)) and ((yaw < 0) == (wyaw < 0))
        check(f"controller x={x:+.1f} z={z:.1f} -> vx={vx:+.2f} yaw={yaw:+.2f}", ok)

    # stop late enough that the drone reaches altitude and actually follows first
    s, link = run_mission(2, stop_at=3.0)
    check("entered follow phase", "follow" in link.phases(), str(link.phases()))
    check("actively followed the person",
          any(m.get("following") for m in link.sent if m["t"] == c2.STATUS))
    check("velocity setpoints were streamed", getattr(s.fc, "_last_vel", None) is not None,
          str(getattr(s.fc, "_last_vel", None)))
    check("STOP landed it in place", "stopped" in (link.done() or ""), link.done())

    print("\n[Mission 2: link lost while following]")
    _, link = run_mission(2, ping_for=1.0)
    check("returned home (RTL)", "RTL" in (link.done() or ""), link.done())

    print("\n[Mission 2: camera loss -> hover, never drift]")
    s, link = run_mission(2, stop_at=2.0, people=False)
    check("no person -> zero velocity commanded",
          getattr(s.fc, "_last_vel", (1, 0, 0, 1))[0] == 0.0
          and getattr(s.fc, "_last_vel", (1, 0, 0, 1))[3] == 0.0,
          str(getattr(s.fc, "_last_vel", None)))


# ---------------------------------------------------------------- hover 3 ft
class ModeLogFC(srv.MockFC):
    """MockFC that remembers every flight mode it was put in, and can be told
    never to climb (a takeoff that stalls)."""

    def __init__(self, gps=True, climbs=True):
        super().__init__(gps=gps)
        self.modes, self.climbs = [], climbs

    def set_flight_mode(self, mode):
        self.modes.append(mode)
        return super().set_flight_mode(mode)

    def flight_state(self):
        st = super().flight_state()
        if not self.climbs and st["armed"] and self._t_land is None:
            st["alt"] = 0.1
        return st


def run_hover(ping_for=100.0, stop_at=None, climbs=True):
    fc = ModeLogFC(climbs=climbs)
    s = srv.C2Server(fc, props_off=False)
    out = []
    s.run_and_report(c2.message(c2.RUN, 1, id=8), out.append)
    link = FakeLink(ping_for=ping_for, stop_at=stop_at)
    s.confirm(link, link.send)
    return fc, out[-1], link


def test_hover():
    print("\n[Hover 3 ft: the LoRa remote's flight]")
    srv.STATUS_INTERVAL_S = 0.25
    hold_was, loss_was, climb_was = srv.HOVER3_TIME_S, srv.LINK_LOSS_S, srv.HOVER3_CLIMB_S
    try:
        srv.HOVER3_TIME_S = 1.0

        # Gates: a remote with a knob must not be able to launch past these.
        for gps, props_off, why in ((True, True, "props OFF"), (False, False, "no GPS")):
            s = srv.C2Server(srv.MockFC(gps=gps), props_off=props_off)
            out = []
            s.run_and_report(c2.message(c2.RUN, 1, id=8), out.append)
            check(f"hover refused: {why}", out[-1].get("accepted") is False,
                  out[-1].get("reason", ""))
            check(f"  and nothing is left pending ({why})", s._pending is None)

        fc, ack, link = run_hover()
        check("hover accepted only with a second confirmation",
              ack.get("accepted") is True and ack.get("confirm_required") is True,
              ack.get("reason", "")[:50])
        check("PX4 told 3 ft (0.91 m)", getattr(fc, "_takeoff_alt", None) == 0.91,
              f"MIS_TAKEOFF_ALT={getattr(fc, '_takeoff_alt', None)}")
        check("phases takeoff -> hover -> land",
              link.phases() == ["takeoff", "hover", "land"], str(link.phases()))
        check("ends landed & disarmed", link.done() == "landed & disarmed", link.done())
        check("never RTL (it would climb to RTL_DESCEND_ALT)", "RTL" not in fc.modes,
              str(fc.modes))

        srv.LINK_LOSS_S = 1.0
        fc, _, link = run_hover(ping_for=0.5)
        check("link loss lands in place, not RTL",
              fc.modes[-1] == "LAND" and "RTL" not in fc.modes, str(fc.modes))
        check("  and says so", any(t.startswith("LINK LOST — landing") for t in link.texts()),
              str(link.texts()[-2:]))
        check("  DONE names the cause", link.done() == "landed (link lost)", link.done())
        srv.LINK_LOSS_S = loss_was

        srv.HOVER3_TIME_S = 30.0
        fc, _, link = run_hover(stop_at=1.0)
        check("STOP from the remote lands early", link.done() == "landed (stopped early)",
              link.done())

        srv.HOVER3_CLIMB_S = 1.0
        fc, _, link = run_hover(climbs=False)
        check("a takeoff that never reaches 3 ft lands instead of waiting",
              any("never reached" in t for t in link.texts()) and "LAND" in fc.modes,
              str(link.texts()[-2:]))
    finally:
        srv.HOVER3_TIME_S, srv.LINK_LOSS_S, srv.HOVER3_CLIMB_S = hold_was, loss_was, climb_was

    print("\n[confirm step: cancel and expiry]")
    s = srv.C2Server(ModeLogFC(), props_off=False)
    out = []
    s.run_and_report(c2.message(c2.RUN, 1, id=8), out.append)
    r = s.handle(c2.message(c2.ABORT, 2))
    check("ABORT before CONFIRM cancels the prepared flight",
          s._pending is None and r and r[0].get("accepted") is True, str(r))
    link = FakeLink()
    s.confirm(link, link.send)
    check("  so a later CONFIRM launches nothing",
          not s.fc._armed and link.sent and link.sent[0].get("accepted") is False,
          str(link.sent[:1]))

    s.run_and_report(c2.message(c2.RUN, 3, id=8), out.append)
    s._pending_at -= srv.PENDING_CONFIRM_S + 1
    link = FakeLink()
    s.confirm(link, link.send)
    check("a CONFIRM after the window lapses launches nothing",
          not s.fc._armed and s._pending is None, str(link.sent[:1]))
    check("ABORT with nothing pending is ignored", s.handle(c2.message(c2.ABORT, 4)) == [])

    # The gates are checked when a flight is prepared, but CONFIRM can arrive up
    # to PENDING_CONFIRM_S later. Props toggle immediately (menu id 6, no confirm
    # of its own) and a GPS fix can drop, so both have to be re-read at CONFIRM
    # or the interlock is only advisory.
    print("\n[confirm re-checks the gates it checked at prepare time]")
    s = srv.C2Server(ModeLogFC(), props_off=False)
    out = []
    s.run_and_report(c2.message(c2.RUN, 1, id=8), out.append)
    check("hover prepared while props are ON", s._pending == "hover")
    s.run_and_report(c2.message(c2.RUN, 2, id=6), out.append)   # toggle props OFF
    check("  props toggled OFF inside the confirm window", s.props_off is True)
    link = FakeLink()
    s.confirm(link, link.send)
    check("  CONFIRM is refused, and nothing arms",
          not s.fc._armed and s._pending is None
          and link.sent and link.sent[0].get("accepted") is False,
          str(link.sent[:1]))
    check("  the operator is told why", "props are OFF" in
          (link.sent[0].get("reason", "") if link.sent else ""),
          str(link.sent[:1]))

    s = srv.C2Server(ModeLogFC(gps=True), props_off=False)
    s.run_and_report(c2.message(c2.RUN, 1, id=8), [].append)
    s.fc._gps = False                                    # fix drops before CONFIRM
    link = FakeLink()
    s.confirm(link, link.send)
    check("a GPS fix lost inside the confirm window also blocks the launch",
          not s.fc._armed and s._pending is None
          and link.sent and link.sent[0].get("accepted") is False,
          str(link.sent[:1]))


# ---------------------------------------------------------------- motor tests on the real FC
def test_motor_refusal():
    print("\n[motor test refusal reaches the operator]")
    import types
    real = srv.missions          # None here: tests import drone.c2_server as a package
    try:
        fc = srv.RealFC.__new__(srv.RealFC)     # no Pixhawk: skip connecting
        fc.master = None
        srv.missions = types.SimpleNamespace(mission_1=lambda m, n: False,
                                             mission_2=lambda m, n: True)
        ok, why = fc.run_mission(1, 4)
        check("PX4 refusal -> not reported as done", ok is False and "refused" in why, why)
        check("accepted test -> done", fc.run_mission(2, 4) == (True, "done"))
    finally:
        srv.missions = real


# ---------------------------------------------------------------- nothing flies from a RUN
class CountingFC(srv.MockFC):
    """MockFC that remembers which missions run_mission was asked to run."""

    def __init__(self, gps=True):
        super().__init__(gps=gps)
        self.ran = []

    def run_mission(self, mid, motors=4):
        self.ran.append(mid)
        return super().run_mission(mid, motors)


def test_run_never_flies():
    print("\n[a RUN never flies: flights wait for CONFIRM]")
    fc = CountingFC()
    s = srv.C2Server(fc, props_off=False)
    out = []
    s.run_and_report(c2.message(c2.RUN, 1, id=3), out.append)
    ack = out[-1] if out else {}
    check("RUN 3 (waypoints) refused, with props ON and a GPS fix",
          ack.get("accepted") is False, ack.get("reason", ""))
    check("  the operator is told the way that does fly", "FLY_REQ" in ack.get("reason", ""))
    check("  nothing ran, nothing armed, nothing pending",
          fc.ran == [] and not fc._armed and s._pending is None, str(fc.ran))

    # Every flight item either waits for a CONFIRM or is refused. None executes.
    for item in s.menu():
        if item.get("needs") != "props_on":
            continue
        s._prepare(None)
        out = []
        s.run_and_report(c2.message(c2.RUN, 1, id=item["id"]), out.append)
        ack = out[-1] if out else {}
        check(f"  item {item['id']} waits for CONFIRM or is refused",
              ack.get("confirm_required") is True or ack.get("accepted") is False,
              str(ack)[:70])
    check("  none of them reached run_mission", fc.ran == [], str(fc.ran))

    fc = srv.RealFC.__new__(srv.RealFC)      # no Pixhawk: skip connecting
    fc.master = None
    ok, why = fc.run_mission(3, 4)
    check("the real FC runs nothing for item 3 either", ok is False, why)

    srv.STATUS_INTERVAL_S = 0.25
    s = make_server(gps=True, props_off=False, mission=True)
    r = s.handle(c2.message(c2.FLY_REQ, 1))[0]
    link = FakeLink()
    s.confirm(link, link.send)
    check("waypoints still fly the way the laptop sends them: FLY_REQ, then CONFIRM",
          r.get("confirm_required") is True and "landed" in (link.done() or ""), link.done())


def test_no_depth():
    print("\n[Mission 2: no depth means no movement]")
    for person in ({"x": 0.0, "z": 0.0}, {"x": 0.6, "z": 0.0}, {"x": -0.6, "z": 0.0},
                   {"x": 0.6}, {"x": 0.6, "z": None}, {"x": 0.6, "z": float("nan")},
                   {"x": 0.6, "z": -1.0}, {"x": 0.6, "z": "2.0"}, {"x": 0.6, "z": True}):
        vx, yaw = srv.C2Server._follow_setpoint(person)
        check(f"{person} -> hold still", (vx, yaw) == (0.0, 0.0), f"vx={vx:+.2f} yaw={yaw:+.2f}")
    vx, yaw = srv.C2Server._follow_setpoint({"x": "left", "z": 4.0})
    check("a bad x with good depth still closes the distance, without turning",
          vx > 0 and yaw == 0.0, f"vx={vx:+.2f} yaw={yaw:+.2f}")
    check("STATUS shows no distance for a 0 m reading",
          srv.C2Server._pz({"z": 0.0}) is None and srv.C2Server._pz({"x": 1}) is None
          and srv.C2Server._pz({"z": 2.5}) == 2.5)

    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.setblocking(False)
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        tx.sendto(b"[1, 2, 3]", rx.getsockname())
        time.sleep(0.05)
        check("a camera packet that isn't an object is dropped",
              srv.C2Server._read_person(rx) is None)
        tx.sendto(b'{"x": 0.1, "z": 2.0}', rx.getsockname())
        tx.sendto(b'"noise"', rx.getsockname())
        time.sleep(0.05)
        check("  and doesn't hide the person before it",
              srv.C2Server._read_person(rx) == {"x": 0.1, "z": 2.0})
    finally:
        rx.close()
        tx.close()


# ---------------------------------------------------------------- errors in flight
class CrashingFC(ModeLogFC):
    """Raises from flight_state once a flight is under way: a serial error, say,
    or a bug in a mission loop. Optionally the failsafe command fails too."""

    def __init__(self, after=5, text="serial port went away", failsafe_text=None):
        super().__init__()
        self.after, self.text, self.failsafe_text, self.reads = after, text, failsafe_text, 0

    def flight_state(self):
        st = super().flight_state()
        if st["armed"] and self._t_land is None:
            self.reads += 1
            if self.reads > self.after:
                raise OSError(self.text)
        return st

    def set_flight_mode(self, mode):
        if self.failsafe_text and mode in ("LAND", "RTL"):
            raise OSError(self.failsafe_text)
        return super().set_flight_mode(mode)


class StopServe(BaseException):
    """Ends serve() from a test. A BaseException, so serve() can't swallow it."""


class ScriptedLink(FakeLink):
    """Feeds serve() a script of messages. With until_done, it then keeps the
    link alive with PINGs until a DONE goes out, sends one last PING (seq 99),
    and stops serve(); without, it stops serve() when the script runs out."""

    def __init__(self, msgs, until_done=False):
        super().__init__()
        self.msgs, self.until_done, self.closing = list(msgs), until_done, False

    def poll(self):
        if self.msgs:
            return self.msgs.pop(0)
        if self.until_done and not any(m["t"] == c2.DONE for m in self.sent):
            return c2.message(c2.PING, 0)
        if self.until_done and not self.closing:
            self.closing = True
            return c2.message(c2.PING, 99)
        raise StopServe


def run_serve(server, link):
    logs = []
    try:
        srv.serve(server, link, log=logs.append)
    except StopServe:
        pass
    return logs


def test_flight_errors():
    print("\n[an error mid-flight triggers the failsafe, and the server lives on]")
    srv.STATUS_INTERVAL_S = 0.25
    for which, rid, mode, said in (("hover", 8, "LAND", "landing in place"),
                                   ("mission2", 5, "RTL", "returning home")):
        fc = CrashingFC()
        s = srv.C2Server(fc, props_off=False)
        s.run_and_report(c2.message(c2.RUN, 1, id=rid), [].append)
        link = FakeLink()
        try:
            s.confirm(link, link.send)
            raised = None
        except Exception as exc:              # the old behaviour: it killed the server
            raised = exc
        check(f"{which}: the error doesn't escape the flight", raised is None, repr(raised))
        check(f"  and puts the drone in its failsafe, {mode}", fc.modes[-1:] == [mode],
              str(fc.modes))
        check("  and tells the operator", link.done() == f"FAILED: serial port went away — {said}",
              link.done())

    fc = CrashingFC(failsafe_text="FC link down")
    s = srv.C2Server(fc, props_off=False)
    s.run_and_report(c2.message(c2.RUN, 1, id=8), [].append)
    link = FakeLink()
    s.confirm(link, link.send)
    check("a failsafe that can't be sent is reported, not hidden",
          (link.done() or "").endswith("— LAND failed: FC link down"), link.done())

    # Through serve() itself: crash mid-flight, then the next PING still answered.
    fc = CrashingFC()
    s = srv.C2Server(fc, props_off=False)
    link = ScriptedLink([c2.message(c2.RUN, 1, id=8), c2.message(c2.CONFIRM, 2)],
                        until_done=True)
    run_serve(s, link)
    after = link.sent[[m["t"] for m in link.sent].index(c2.DONE):] if link.done() else []
    check("serve(): a crashed hover lands, and the server answers the next PING",
          fc.modes[-1:] == ["LAND"] and any(m["t"] == c2.PONG and m["seq"] == 99 for m in after),
          f"{fc.modes} {[m['t'] for m in after]}")

    class BrokenUploadFC(srv.MockFC):
        def upload_waypoints(self, wps):
            raise RuntimeError("PX4 went quiet mid-upload")

    s = srv.C2Server(BrokenUploadFC(gps=True), props_off=False)
    link = ScriptedLink([c2.message(c2.WP_BEGIN, 1), c2.message(c2.WP_END, 2),
                         c2.message(c2.PING, 3)])
    logs = run_serve(s, link)
    check("serve(): a message that raises is logged, not fatal",
          any("PX4 went quiet" in line for line in logs), str(logs[-1:]))
    check("  and the next message is still answered",
          any(m["t"] == c2.PONG and m["seq"] == 3 for m in link.sent), str(link.sent[-1:]))


def test_orphan_stop():
    print("\n[STOP lands an armed drone that no flight loop is watching]")
    fc = ModeLogFC()
    s = srv.C2Server(fc, props_off=False)
    check("STOP with the drone disarmed does nothing",
          s.handle(c2.message(c2.STOP, 1)) == [] and fc.modes == [], str(fc.modes))
    fc.arm()                       # armed, no flight loop: a server restarted mid-flight
    r = s.handle(c2.message(c2.STOP, 2))
    check("STOP while armed and idle -> LAND", fc.modes == ["LAND"], str(fc.modes))
    check("  and says why", bool(r) and r[0].get("accepted") is True
          and "armed" in r[0].get("reason", ""), str(r))

    fc = ModeLogFC()
    s = srv.C2Server(fc, props_off=False)
    s._prepare("hover")
    fc.arm()
    s.handle(c2.message(c2.ABORT, 3))
    check("ABORT while armed and idle -> LAND, and drops the prepared flight",
          fc.modes == ["LAND"] and s._pending is None, f"{fc.modes} {s._pending}")


# ---------------------------------------------------------------- takeoff height
def test_takeoff_height():
    print("\n[the takeoff height is confirmed before arming]")
    import types

    class Reply:
        def __init__(self, pid, value):
            self.param_id, self.param_value = pid, value

    class FakeMaster:
        target_system = target_component = 1

        def __init__(self, replies):
            self.replies, self.sets = list(replies), 0
            self.mav = types.SimpleNamespace(param_set_send=self._set)

        def _set(self, *args):
            self.sets += 1

        def recv_match(self, type=None, blocking=True, timeout=None):
            return self.replies.pop(0) if self.replies else None

    real = srv.mavutil
    try:
        try:   # the real library's decoding, where it's installed (not in CI)
            from pymavlink.dialects.v20 import common as mav2
            pkt = mav2.MAVLink_param_value_message(b"MIS_TAKEOFF_ALT", 0.91, 9, 1000, 5)
            decoded = mav2.MAVLink(None).parse_char(pkt.pack(mav2.MAVLink(None)))
        except ImportError:
            decoded = None
        srv.mavutil = types.SimpleNamespace(
            mavlink=types.SimpleNamespace(MAV_PARAM_TYPE_REAL32=9))
        fc = srv.RealFC.__new__(srv.RealFC)
        cases = [([Reply("MIS_TAKEOFF_ALT", 0.91)], True, "PX4's reply confirms it"),
                 ([Reply(b"MIS_TAKEOFF_ALT\x00", 0.9100000262)], True,
                  "  as bytes padded with NULs too"),
                 ([Reply("SYS_AUTOSTART", 4001.0)], False,
                  "another parameter's PARAM_VALUE is not a reply"),
                 ([Reply("SYS_AUTOSTART", 4001.0), Reply("MIS_TAKEOFF_ALT", 0.91)], True,
                  "  and is skipped on the way to the real one"),
                 ([Reply("MIS_TAKEOFF_ALT", 2.5)] * 2, False,
                  "a different value is not a confirmation"),
                 ([], False, "no reply is not a confirmation")]
        if decoded is not None:
            cases.append(([decoded], True, "pymavlink's own decoding of PX4's reply confirms it"))
        for replies, want, label in cases:
            fc.master = FakeMaster(replies)
            check(label, fc.set_takeoff_alt(0.91) is want)
        fc.master = FakeMaster([])
        fc.set_takeoff_alt(0.91)
        check("  an unanswered set is sent twice, then given up", fc.master.sets == 2,
              f"{fc.master.sets} sends")
    finally:
        srv.mavutil = real

    class HeightFC(ModeLogFC):
        def __init__(self, confirms):
            super().__init__()
            self.confirms, self.calls = confirms, []

        def set_takeoff_alt(self, alt_m):
            self.calls.append("height")
            super().set_takeoff_alt(alt_m)
            return self.confirms

        def arm(self, timeout=8):
            self.calls.append("arm")
            return super().arm(timeout)

    hold_was = srv.HOVER3_TIME_S
    try:
        srv.HOVER3_TIME_S = 0.5
        for confirms in (False, True):
            fc = HeightFC(confirms)
            s = srv.C2Server(fc, props_off=False)
            s.run_and_report(c2.message(c2.RUN, 1, id=8), [].append)
            link = FakeLink()
            s.confirm(link, link.send)
            if confirms:
                check("a confirmed height is set before arming",
                      fc.calls[:2] == ["height", "arm"] and link.done() == "landed & disarmed",
                      f"{fc.calls} {link.done()}")
            else:
                check("an unconfirmed height stops the flight before arming",
                      fc.calls == ["height"] and not fc._armed
                      and "takeoff height" in (link.done() or ""), f"{fc.calls} {link.done()}")
    finally:
        srv.HOVER3_TIME_S = hold_was


# ---------------------------------------------------------------- radio line budget
def test_radio_line_budget():
    """Both firmware sketches carry 240 characters a line (MAX_LINE) and cut the
    rest, and a cut line is lost. Signing adds about 40. So every reply the
    server can make, at its longest, must fit signed."""
    print("\n[every reply fits the radio's 240 characters once signed]")
    from radio import auth
    key = b"k" * 32

    def signed(m):
        return len(c2.encode(auth.sign(m, key)).rstrip("\n"))

    srv.STATUS_INTERVAL_S = 0.25
    sent = []
    s = srv.C2Server(srv.MockFC(gps=True), props_off=False)
    for mid in (3, 4, 5, 8):
        s._prepare(None)
        s.run_and_report(c2.message(c2.RUN, 65535, id=mid), sent.append)
    s._prepare(None)
    s.fc.upload_waypoints([(37.42, -122.08, 5.0)])
    sent += s.handle(c2.message(c2.FLY_REQ, 65535))
    s._prepare(None)
    s.fc.arm()
    sent += s.handle(c2.message(c2.STOP, 65535))          # the armed-but-idle reply
    sent += s.handle(c2.message(c2.GET_MENU, 65535))

    class Worst(srv.MockFC):
        """The longest texts the real FC can produce: arm_detail is capped at
        120, diagnostics at 150, and an error can say anything."""
        arm_detail = "x" * 120

        def arm(self, timeout=8):
            return False

        def diagnostics(self):
            return "d" * 150

        def run_mission(self, mid, motors=4):
            raise RuntimeError("e" * 500)

    s = srv.C2Server(Worst(gps=True), props_off=False)
    link = FakeLink()
    s.run_and_report(c2.message(c2.RUN, 65535, id=5), sent.append)   # longest id: mission2
    s.confirm(link, link.send)                                       # PX4 refuses to arm
    s.run_and_report(c2.message(c2.RUN, 65535, id=7), sent.append)   # diagnostics
    s.props_off = True
    s.run_and_report(c2.message(c2.RUN, 65535, id=1), sent.append)   # a motor test that raises
    sent += link.sent

    for fc in (CrashingFC(text="c" * 500), CrashingFC(text="c" * 500, failsafe_text="f" * 500)):
        for rid in (5, 8):
            s = srv.C2Server(fc, props_off=False, log=lambda *_: None)   # 500-char log lines
            fc._armed, fc._t_land, fc.reads = False, None, 0
            s.run_and_report(c2.message(c2.RUN, 65535, id=rid), sent.append)
            link = FakeLink()
            s.confirm(link, link.send)
            sent += link.sent

    longest = max(sent, key=signed)
    check(f"{len(sent)} replies, longest {signed(longest)} of 240 characters signed",
          signed(longest) <= 240, c2.encode(longest)[:90])
    check("  long errors are cut, not sent whole",
          not any("c" * 81 in m.get("result", "") or "e" * 81 in m.get("result", "")
                  for m in sent))


# ---------------------------------------------------------------- the old menu's radio listener
def test_lora_listener_cannot_fly():
    print("\n[the old mission menu's radio listener cannot fly]")
    import importlib
    import inspect
    import types
    names = ("pymavlink", "pymavlink.mavutil", "serial", "drone.missions")
    saved = {n: sys.modules.get(n) for n in names}
    try:
        # CI installs neither library, and missions.py exits at import without
        # them. Stand-ins are enough: nothing here talks to a flight controller.
        for name in ("pymavlink", "serial"):
            try:
                importlib.import_module(name)
            except ImportError:
                sys.modules[name] = types.ModuleType(name)
        if not hasattr(sys.modules["pymavlink"], "mavutil"):
            sys.modules["pymavlink"].mavutil = types.SimpleNamespace()
            sys.modules["pymavlink.mavutil"] = sys.modules["pymavlink"].mavutil
        sys.modules.pop("drone.missions", None)
        missions = importlib.import_module("drone.missions")

        check("mission 3 always asks for FLY at the keyboard (no require_confirm)",
              list(inspect.signature(missions.mission_3).parameters) == ["master"],
              str(inspect.signature(missions.mission_3)))
        flown = []
        missions.mission_3 = lambda *a, **k: flown.append(a)
        for text in ("4", "4.0", " 4 "):
            missions.handle_lora_msg(None, text, props_off=False, motors=4)
        check("a radio '4' flies nothing", flown == [], f"{len(flown)} flights")
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


# ---------------------------------------------------------------- client robustness
def test_client_robustness():
    print("\n[client survives corrupted LoRa packets]")

    class BadTx:
        def __init__(self):
            self.out = []

        def send(self, m):
            if m.get("t") == c2.GET_MENU:
                self.out = [
                    c2.message(c2.MENU, 1, item={"id": 1, "name": "Sequential motor test"}),
                    c2.message(c2.MENU, 1, item={"id": 6}),          # corrupt: no name
                    c2.message(c2.MENU, 1, item="garbage"),           # corrupt: not a dict
                    c2.message(c2.MENU, 1, item={"id": 1, "name": "Sequential motor test"}),  # dup
                    c2.message(c2.MENU, 1, item={"id": 4, "name": "Mission 1"}, last=True),
                ]

        def poll(self):
            return self.out.pop(0) if self.out else None

        def close(self):
            pass

    items = gc.Client(BadTx()).get_menu()
    check("corrupted items dropped", [i["id"] for i in items] == [1, 4], str(items))
    try:
        for it in items:
            f"{it.get('id')}) {it.get('name')}{gc.flag_label(it)}"
        check("menu renders without crashing", True)
    except Exception as exc:
        check("menu renders without crashing", False, str(exc))


if __name__ == "__main__":
    test_monitored_flight()
    test_menu()
    test_props()
    test_fly_gates()
    test_mission1()
    test_mission2()
    test_hover()
    test_motor_refusal()
    test_run_never_flies()
    test_no_depth()
    test_flight_errors()
    test_orphan_stop()
    test_takeoff_height()
    test_radio_line_budget()
    test_lora_listener_cannot_fly()
    test_client_robustness()
    print("\n" + "=" * 52)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): " + "; ".join(FAILURES))
        sys.exit(1)
    print("ALL CHECKS PASSED")
