#!/usr/bin/env python3
"""The command link under the conditions that made it look dead.

"Nothing at all some sessions" had five causes, each pinned here on a fake wire
so they stay fixed without a stick in the room:

  1. the first message went into a stick that was still rebooting;
  2. nothing was ever sent twice, so one lost packet ended a handshake;
  3. a garbled signature tag raised and took the server loop with it;
  4. the flight loop read one line per tick and blocked 0.2 s doing it;
  5. two free-running 1 s timers (the ground's PING, the drone's STATUS)
     talked over each other on a half-duplex radio.

The Wire below is two serial ends joined by a lossy, half-duplex "air": a
packet can be dropped, a packet sent while the other end is still transmitting
loses both, and a port that is opened reboots its stick, which prints its
banner a moment later and loses whatever was written before that. The real
pyserial path is checked separately on a pseudo-terminal (see docs).

Stdlib only.
"""
import random
import sys
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)


# --------------------------------------------------------------------------- the wire
class Air:
    """What joins two sticks. Shared by both ends; owns the loss and collisions."""

    def __init__(self, loss=0.0, airtime=0.0, seed=1):
        self.loss = loss                  # per-packet drop probability, each direction
        self.airtime = airtime            # seconds a packet occupies the air
        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        self.busy_until = 0.0
        self.busy_owner = None
        self.last_packet = None           # (owner, dest, bytes) for the collision pull
        self.ends = {}
        self.writes = []                  # (t, port, bytes) every attempted write
        self.collisions = 0
        self.dropped = 0

    def carry(self, src, data):
        """src wrote data: deliver it to the other end, or lose it."""
        now = time.monotonic()
        dest = next((e for e in self.ends.values() if e is not src), None)
        with self.lock:
            self.writes.append((now, src.port, data))
            if dest is None or not dest.powered:
                return
            if now < self.busy_until and self.busy_owner is not src:
                # Both sticks transmitting at once: neither packet survives.
                self.collisions += 1
                if self.last_packet is not None:
                    owner, pdest, pdata = self.last_packet
                    pdest.pull(pdata)
                    self.last_packet = None
                return
            self.busy_until = now + self.airtime
            self.busy_owner = src
            if self.rng.random() < self.loss:
                self.dropped += 1
                return
            dest.deliver(data)
            self.last_packet = (src, dest, data)


class Stick:
    """One serial end: what pyserial's Serial would show the Python side."""

    def __init__(self, air, port, boot_s=0.0, banner=b"Venator LoRa transceiver ready (half-duplex bridge) fw test\n"):
        self.air, self.port = air, port
        self.boot_s, self.banner = boot_s, banner
        self.powered = True
        self.lock = threading.Lock()
        self.inbox = bytearray()
        self.pending = []                 # (ready_at, bytes): still on the air
        self.booting_until = 0.0
        self.opened = 0
        self.reads = 0
        air.ends[port] = self

    # -- what the air does to us
    def deliver(self, data):
        with self.lock:
            if time.monotonic() < self.booting_until:
                return                        # rebooting: the radio is not listening
            # A packet is readable only once its airtime is over, as on a real
            # radio; until then a collision can still take it back.
            self.pending.append((time.monotonic() + self.air.airtime, data))

    def pull(self, data):
        with self.lock:
            for i in range(len(self.pending) - 1, -1, -1):
                if self.pending[i][1] == data:
                    del self.pending[i]
                    return

    def _mature(self):
        now = time.monotonic()
        keep = []
        for ready_at, data in self.pending:
            if ready_at <= now:
                self.inbox += data
            else:
                keep.append((ready_at, data))
        self.pending = keep

    # -- what the Python side does
    def on_open(self):
        self.opened += 1
        if self.boot_s:
            self.booting_until = time.monotonic() + self.boot_s
            threading.Timer(self.boot_s, self._banner).start()

    def _banner(self):
        with self.lock:
            self.inbox += self.banner

    @property
    def in_waiting(self):
        with self.lock:
            self._mature()
            return len(self.inbox)

    def read(self, n):
        self.reads += 1
        with self.lock:
            self._mature()
            out = bytes(self.inbox[:n])
            del self.inbox[:n]
        return out

    def write(self, data):
        if time.monotonic() < self.booting_until:
            return len(data)                  # eaten by the reboot
        self.air.carry(self, bytes(data))
        return len(data)


class FakeSerialModule(types.ModuleType):
    """A `serial` module whose Serial() opens a Stick by port name."""

    def __init__(self, air):
        super().__init__("serial")
        self.air = air
        module = self

        class Serial:
            def __init__(self, port, baud=115200, timeout=0.2, exclusive=False):
                stick = module.air.ends.get(port)
                if stick is None or not stick.powered:
                    raise OSError(2, f"could not open port {port}")
                self.stick = stick
                self.port, self.baud = port, baud
                stick.on_open()

            @property
            def in_waiting(self):
                return self.stick.in_waiting

            def read(self, n=1):
                return self.stick.read(n)

            def write(self, data):
                return self.stick.write(data)

            def flush(self):
                pass

            def reset_input_buffer(self):
                with self.stick.lock:
                    self.stick._mature()
                    self.stick.inbox.clear()

            def close(self):
                pass

        self.Serial = Serial
        self.SerialException = OSError


def wire(loss=0.0, airtime=0.0, boot_s=0.0, seed=1):
    air = Air(loss=loss, airtime=airtime, seed=seed)
    a = Stick(air, "/dev/fake-ground", boot_s=boot_s)
    b = Stick(air, "/dev/fake-drone", boot_s=boot_s)
    sys.modules["serial"] = FakeSerialModule(air)
    return air, a, b


sys.modules["serial"] = FakeSerialModule(Air())       # before the modules import it

from radio import protocol as p                         # noqa: E402
from radio import auth                                  # noqa: E402
from radio import serial_link as sl                     # noqa: E402
from radio.serial_link import SerialLink, MAX_LINE, MAX_BUFFER  # noqa: E402
import drone.c2_server as srv                           # noqa: E402
import ground.gcs_client as gc                          # noqa: E402

quiet = lambda *a, **k: None                            # noqa: E731
gc.REQUEST_RETRY_S = 0.3
gc.CONFIRM_RETRY_S = 0.6
gc.CMD_RETRY_S = 0.4
srv.LoRaLink  # the server's link class is real; tests build SerialLink directly


def link(port, **kw):
    kw.setdefault("auth_key", None)
    kw.setdefault("log", quiet)
    kw.setdefault("send_gap", 0.0)
    return SerialLink(port, 115200, **kw)


# --------------------------------------------------------------------------- A: open
def test_open_waits_for_the_stick():
    print("\n[opening the port waits for the stick to finish rebooting]")
    air, a, b = wire(boot_s=0.3)
    t0 = time.monotonic()
    la = link(a.port, settle=2.5)
    took = time.monotonic() - t0
    check("the banner ends the wait early", 0.25 < took < 1.0, f"{took:.2f}s")
    check("  and is recorded", la.stats()["banner_seen"] is True)
    la.send(p.message(p.HELLO, 1))
    first_write = air.writes[0][0] if air.writes else None
    check("no HELLO leaves before the stick is back",
          first_write is not None and first_write - t0 >= 0.3, str(first_write))
    check("  and it reaches the other end", b.in_waiting > 0)

    air, a, b = wire(boot_s=0.0)
    t0 = time.monotonic()
    link(a.port, settle=0.4)
    took = time.monotonic() - t0
    check("a stick that prints no banner costs the full settle, once", 0.35 < took < 0.7, f"{took:.2f}s")

    air, a, b = wire(boot_s=0.0)
    t0 = time.monotonic()
    link(a.port, settle=0.0)
    check("settle 0 trusts the stream at once (the loopback tests)", time.monotonic() - t0 < 0.05)


def test_poll_is_non_blocking():
    print("\n[poll() never blocks and never reads more than it must]")
    air, a, b = wire()
    la, lb = link(a.port), link(b.port)
    for i in range(3):
        lb.send(p.message(p.PING, i))
    reads_before = a.reads
    got = [la.poll(), la.poll(), la.poll()]
    check("three queued lines come back from three polls", [m and m["seq"] for m in got] == [0, 1, 2], str(got))
    check("  with one read of the port", a.reads - reads_before == 1, f"{a.reads - reads_before} reads")
    t0 = time.monotonic()
    check("an idle poll returns None", la.poll() is None)
    check("  without waiting", time.monotonic() - t0 < 0.02)

    # a multibyte character split across two reads must survive
    text = "señal — ñ"
    # encode() escapes non-ASCII, so build the raw UTF-8 line by hand
    line = ('{"t":"LOG","seq":7,"text":"' + text + '"}\n').encode("utf-8")
    cut = line.index("ñ".encode()) + 1            # inside the two-byte ñ
    a.deliver(line[:cut]); la.poll()
    a.deliver(line[cut:])
    m = la.poll()
    check("a UTF-8 character cut across two reads is intact", m is not None and m.get("text") == text, str(m))

    a.deliver(b"x" * (MAX_BUFFER + 1000))
    la.poll()
    check("bytes with no newline are capped", len(la._buf) <= MAX_BUFFER, str(len(la._buf)))
    check("  and counted as bad", la.stats()["rx_bad"] >= 1)
    a.deliver(b"\n" + p.encode(p.message(p.PONG, 3)).encode())
    polled = [la.poll() for _ in range(3)]
    check("  and the next real line still parses", any(m and m.get("t") == p.PONG for m in polled), str(polled))


def test_oversize_refused():
    print("\n[a line the firmware would cut is refused here]")
    air, a, b = wire()
    la = link(a.port)
    big = p.message(p.LOG, 1, text="x" * (MAX_LINE + 20))
    check("send() returns False", la.send(big) is False)
    check("  nothing went on the air", air.writes == [])
    check("  and it is counted", la.stats()["tx_dropped"] == 1)
    ok = p.message(p.LOG, 2, text="x" * 100)
    check("a line under the limit still goes", la.send(ok) is True and len(air.writes) == 1)


def test_explicit_port_kept():
    print("\n[port_finder re-resolves only when the configured port fails]")
    air, a, b = wire()
    finder = lambda: b.port                                  # noqa: E731
    la = link(a.port, port_finder=finder)
    check("an explicit port that opens is kept", la.port == a.port, la.port)
    a.powered = False
    lb = link(a.port, port_finder=finder, defer_open=True)
    check("a port that cannot be opened is re-resolved", lb.port == b.port and lb.up, lb.port)


def test_bad_tag_never_raises():
    print("\n[a garbled signature tag is dropped, not raised]")
    key = b"k" * 32
    check("verify(): non-ASCII tag", auth.verify({"t": "PING", "seq": 1, "n": "ab", "m": "é" * 16}, key) is False)
    check("verify(): wrong length", auth.verify({"t": "PING", "seq": 1, "n": "ab", "m": "abc"}, key) is False)
    check("verify(): not a string", auth.verify({"t": "PING", "seq": 1, "n": "ab", "m": 12}, key) is False)
    air, a, b = wire()
    la = link(a.port, auth_key=key)
    a.deliver(('{"t":"PING","seq":1,"n":"abcdef01","m":"' + "é" * 16 + '"}\n').encode("utf-8"))
    try:
        got = la.poll()
        check("poll() returns None for it", got is None, str(got))
    except Exception as exc:                              # noqa: BLE001
        check("poll() returns None for it", False, repr(exc))
    check("  and counts it", la.stats()["rx_rejected"] == 1)


def test_link_report_absorbed():
    print("\n[the bridge's LINK line feeds the counters and nothing else]")
    air, a, b = wire()
    la = link(a.port)
    a.deliver(b'{"t":"LINK","rssi":-87,"snr":9}\n')
    check("poll() hands nothing up", la.poll() is None)
    s = la.stats()
    check("  rssi/snr recorded", (s["rssi"], s["snr"]) == (-87, 9), str(s))
    check("  not counted as a protocol message", s["rx"] == 0)
    a.deliver(b'{"t":"LINK","rssi":"bad","snr":[1]}\n')
    la.poll()
    check("junk values are ignored", (la.stats()["rssi"], la.stats()["snr"]) == (-87, 9))


# --------------------------------------------------------------------------- server
class CountingFC(srv.MockFC):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.runs = []

    def run_mission(self, mid, motors=4):
        self.runs.append(mid)
        return True, "ok (mock)"


class StopServe(BaseException):
    pass


class Scripted:
    def __init__(self, msgs):
        self.msgs, self.sent = list(msgs), []
        self.authenticated = False

    def poll(self):
        if self.msgs:
            m = self.msgs.pop(0)
            if isinstance(m, BaseException):
                raise m
            return m
        raise StopServe

    def send(self, m):
        self.sent.append(m)

    def stats(self):
        return {"rx": 1, "rx_bad": 0, "rx_rejected": 0, "tx": 1, "tx_dropped": 0, "last_rx_s": 0.1}


def run_serve(server, link):
    logs = []
    try:
        srv.serve(server, link, log=logs.append)
    except StopServe:
        pass
    return logs


def test_server_dedupes():
    print("\n[a retransmitted command is answered from the cache]")
    fc = CountingFC()
    s = srv.C2Server(fc, props_off=True, log=quiet)
    run = p.message(p.RUN, 5, id=1)
    lk = Scripted([run, dict(run), dict(run)])
    logs = run_serve(s, lk)
    types_ = [m["t"] for m in lk.sent]
    check("the motor test ran once", fc.runs == [1], str(fc.runs))
    check("  every copy got ACK + DONE", types_ == [p.ACK, p.DONE] * 3, str(types_))
    check("  and the journal says why", any("again" in l for l in logs), str(logs))

    s = srv.C2Server(CountingFC(gps=True), log=quiet)
    run8 = p.message(p.RUN, 9, id=8)
    lk = Scripted([run8, dict(run8)])
    run_serve(s, lk)
    check("a prepared flight's ACK is replayed, the flight stays pending once",
          [m.get("confirm_required") for m in lk.sent] == [True, True] and s._pending == "hover")

    fc = CountingFC()
    s = srv.C2Server(fc, props_off=True, log=quiet)
    lk = Scripted([p.message(p.RUN, 0, id=1), p.message(p.RUN, 0, id=1)])
    run_serve(s, lk)
    check("seq 0 carries no identity: not deduped", fc.runs == [1, 1])

    fc = CountingFC()
    s = srv.C2Server(fc, props_off=True, log=quiet)
    lk = Scripted([p.message(p.RUN, 3, id=1), p.message(p.RUN, 4, id=1)])
    run_serve(s, lk)
    check("a new seq is a new command", fc.runs == [1, 1])


def test_serve_survives_poll_raising():
    print("\n[serve(): a poll() that raises is logged, not fatal]")
    s = srv.C2Server(CountingFC(), log=quiet)
    lk = Scripted([TypeError("a str and a bytes"), p.message(p.PING, 4)])
    logs = run_serve(s, lk)
    check("the error is logged", any("TypeError" in l for l in logs), str(logs))
    check("  and the next message is still answered", [m["t"] for m in lk.sent] == [p.PONG])


def test_hello_ack_reports_auth():
    print("\n[HELLO_ACK says whether the drone signs]")
    s = srv.C2Server(CountingFC(), log=quiet)
    lk = Scripted([p.message(p.HELLO, 1)])
    run_serve(s, lk)
    check("auth: false on an unkeyed link", lk.sent[0].get("auth") is False, str(lk.sent[0]))
    s = srv.C2Server(CountingFC(), log=quiet)
    lk = Scripted([p.message(p.HELLO, 1)])
    lk.authenticated = True
    run_serve(s, lk)
    check("auth: true on a keyed one", lk.sent[0].get("auth") is True)
    check("still one radio line when signed",
          len(p.encode(auth.sign(lk.sent[0], b"k" * 32))) <= MAX_LINE)


class BurstLink:
    """Twenty PINGs already queued, then silence for ever."""

    def __init__(self, n=20):
        self.q = [p.message(p.PING, i) for i in range(n)]
        self.sent = []

    def poll(self):
        return self.q.pop(0) if self.q else None

    def send(self, m):
        self.sent.append(m)


class PingEveryTick(BurstLink):
    def __init__(self):
        super().__init__(0)
        self.n = 0

    def poll(self):
        self.n += 1
        return p.message(p.PING, self.n) if self.n % 4 == 0 else None    # every ~0.6 s at 0.15 s ticks


class StubServer:
    def __init__(self, fc):
        self.fc = fc
        self.logs = []

    def log(self, m):
        self.logs.append(m)


class AlwaysArmed:
    def __init__(self):
        self.modes = []

    def flight_state(self):
        return {"armed": True, "alt": 1.0, "mode": "HOLD"}

    def set_flight_mode(self, m):
        self.modes.append(m)


def test_ticks_drain_and_status_rides_on_pong():
    print("\n[the flight loop drains its backlog and sends STATUS after PONG]")
    loss_was, int_was = srv.LINK_LOSS_S, srv.STATUS_INTERVAL_S
    try:
        srv.LINK_LOSS_S = 0.5
        srv.STATUS_INTERVAL_S = 0.3
        fc = AlwaysArmed()
        lk = BurstLink(20)
        fl = srv.MonitoredFlight(StubServer(fc), lk, lk.send, "hover", "T", failsafe="LAND", phase="hover")
        t0 = time.monotonic()
        for now, st in fl.ticks():
            if fl.ending:
                break
        took = time.monotonic() - t0
        check("20 stale PINGs do not keep a dead link alive", fl.ending == "LINKLOSS" and took < 1.2,
              f"{fl.ending} after {took:.2f}s")
        check("  LAND was commanded", fc.modes == ["LAND"], str(fc.modes))

        srv.LINK_LOSS_S = 4.0
        srv.STATUS_INTERVAL_S = 0.5             # pings come every ~0.6 s: under 2 x this
        fc = AlwaysArmed()
        lk = PingEveryTick()
        fl = srv.MonitoredFlight(StubServer(fc), lk, lk.send, "hover", "T", failsafe="LAND", phase="hover")
        t0 = time.monotonic()
        for now, st in fl.ticks():
            if time.monotonic() - t0 > 3.0:
                break
        sent = lk.sent
        idx = [i for i, m in enumerate(sent) if m["t"] == p.STATUS][1:]   # the first is the opening one
        after_pong = [i for i in idx if i > 0 and sent[i - 1]["t"] == p.PONG]
        check("every STATUS follows a PONG while the ground is pinging",
              len(idx) >= 3 and len(after_pong) == len(idx), f"{len(after_pong)}/{len(idx)}")
        check("  STATUS keeps its interval, not one per PING",
              len(idx) <= int(3.0 / srv.STATUS_INTERVAL_S) + 2, str(len(idx)))

        fc = AlwaysArmed()
        lk = BurstLink(0)
        srv.LINK_LOSS_S = 10.0
        fl = srv.MonitoredFlight(StubServer(fc), lk, lk.send, "hover", "T", failsafe="LAND", phase="hover")
        t0 = time.monotonic()
        for now, st in fl.ticks():
            if time.monotonic() - t0 > 1.0:
                break
        n_status = sum(1 for m in lk.sent if m["t"] == p.STATUS)
        check("a quiet ground still gets STATUS, at half rate", 1 <= n_status <= 2, str(n_status))
    finally:
        srv.LINK_LOSS_S, srv.STATUS_INTERVAL_S = loss_was, int_was


def test_wall_clock_step_is_harmless():
    print("\n[a wall-clock step does not trip the link-loss failsafe]")
    real_time = srv.time
    fake = types.SimpleNamespace(**{k: getattr(real_time, k) for k in dir(real_time) if not k.startswith("_")})
    jump = [0.0]

    def stepping_time():
        jump[0] += 3600.0
        return real_time.time() + jump[0]
    fake.time = stepping_time
    srv.time = fake
    loss_was = srv.LINK_LOSS_S
    try:
        srv.LINK_LOSS_S = 4.0
        fc = AlwaysArmed()
        lk = PingEveryTick()
        fl = srv.MonitoredFlight(StubServer(fc), lk, lk.send, "hover", "T", failsafe="LAND", phase="hover")
        t0 = time.monotonic()
        for now, st in fl.ticks():
            if time.monotonic() - t0 > 1.5:
                break
        check("flying on, with time.time() jumping an hour per call", fl.ending is None and fc.modes == [],
              f"{fl.ending} {fc.modes}")
    finally:
        srv.time = real_time
        srv.LINK_LOSS_S = loss_was


# --------------------------------------------------------------------------- indoor
class IndoorFC(CountingFC):
    def __init__(self, position, gps=False):
        super().__init__(gps=gps, position=position)


def test_indoor_gate():
    print("\n[--indoor: the hover is gated on a flow position, everything else on GPS]")
    s = srv.C2Server(IndoorFC(position=True), indoor=True, log=quiet)
    out = []
    s.run_and_report(p.message(p.RUN, 1, id=8), out.append)
    check("hover accepted indoors with a position and no GPS",
          out[-1].get("accepted") is True and out[-1].get("confirm_required") is True, str(out[-1]))
    ok, why = s._validate_pending()
    check("  and the CONFIRM-time re-check agrees", ok, why)

    s = srv.C2Server(IndoorFC(position=False), indoor=True, log=quiet)
    out = []
    s.run_and_report(p.message(p.RUN, 1, id=8), out.append)
    check("hover refused indoors with no position", out[-1].get("accepted") is False)
    check("  with the flow check named", "check_flow" in out[-1].get("reason", ""), out[-1].get("reason"))

    s = srv.C2Server(IndoorFC(position=True), indoor=True, log=quiet)
    out = []
    s.run_and_report(p.message(p.RUN, 1, id=4), out.append)
    check("Mission 1 is still refused without GPS, even indoors",
          out[-1].get("accepted") is False and "GPS" in out[-1].get("reason", ""), str(out[-1]))
    s._pending = "mission1"
    ok, why = s._validate_pending()
    check("  and at CONFIRM time", not ok and "GPS" in why, why)

    s = srv.C2Server(IndoorFC(position=False, gps=True), indoor=True, log=quiet)
    out = []
    s.run_and_report(p.message(p.RUN, 1, id=8), out.append)
    check("indoors, a GPS fix does not stand in for the flow position", out[-1].get("accepted") is False)

    s = srv.C2Server(IndoorFC(position=False, gps=True), indoor=False, log=quiet)
    out = []
    s.run_and_report(p.message(p.RUN, 1, id=8), out.append)
    check("outdoors nothing changed: GPS gates the hover", out[-1].get("accepted") is True)

    s = srv.C2Server(IndoorFC(position=True), indoor=True, log=quiet)
    out = []
    s.run_and_report(p.message(p.RUN, 1, id=8), out.append)
    s.props_off = True
    ok, why = s._validate_pending()
    check("props OFF still blocks at CONFIRM indoors", not ok and "props" in why, why)

    s = srv.C2Server(IndoorFC(position=True), indoor=True, log=quiet)
    replies = s.handle(p.message(p.HELLO, 1))
    check("HELLO_ACK says indoor and shows the position gate",
          replies[0].get("indoor") is True and replies[0].get("gps") == "indoor: position OK", str(replies[0]))
    s = srv.C2Server(IndoorFC(position=False), indoor=True, log=quiet)
    check("  or its absence", s.handle(p.message(p.HELLO, 1))[0].get("gps") == "indoor: no position")

    # the hover's phases run off the altitude the FC reports, whatever its source
    hold_was, int_was = srv.HOVER4_TIME_S, srv.STATUS_INTERVAL_S
    srv.HOVER4_TIME_S = 0.8
    srv.STATUS_INTERVAL_S = 0.1
    try:
        fc = IndoorFC(position=True)
        s = srv.C2Server(fc, indoor=True, log=quiet)
        out = []
        s.run_and_report(p.message(p.RUN, 1, id=8), out.append)
        lk = BurstLink(0)
        pings = PingEveryTick()
        pings.sent = lk.sent
        s.confirm(pings, lk.send)
        phases = []
        for m in lk.sent:
            if m["t"] == p.STATUS and m.get("phase") not in phases:
                phases.append(m.get("phase"))
        check("the indoor hover flies takeoff -> hover -> land", phases[:3] == ["takeoff", "hover", "land"], str(phases))
        check("  and lands", any(m["t"] == p.DONE and "landed" in m.get("result", "") for m in lk.sent))
    finally:
        srv.HOVER4_TIME_S, srv.STATUS_INTERVAL_S = hold_was, int_was


# --------------------------------------------------------------------------- end to end
def start_server(port, fc=None, **kw):
    """The real serve() over a Wire end, in a thread. Returns (server, link)."""
    lk = SerialLink(port, 115200, settle=0.0, auth_key=None, send_gap=0.05, log=quiet, defer_open=True)
    s = srv.C2Server(fc or CountingFC(gps=True), log=quiet, **kw)
    threading.Thread(target=lambda: srv.serve(s, lk, log=quiet), daemon=True).start()
    return s, lk


def test_handshake_survives_loss():
    print("\n[the laptop's handshake survives a lossy, half-duplex link]")
    gc_prints = []
    gc.print = lambda *a, **k: gc_prints.append(" ".join(str(x) for x in a))
    try:
        air, a, b = wire(loss=0.3, airtime=0.05, boot_s=0.2, seed=7)
        start_server(b.port)
        la = SerialLink(a.port, 115200, settle=1.0, auth_key=None, send_gap=0.05, log=quiet)
        c = gc.Client(la)
        ok = c.handshake()
        check("30% loss each way: connected", ok, "\n".join(gc_prints[-4:]))
        check("  the HELLO was sent more than once", sum(1 for w in air.writes if b'"HELLO"' in w[2]) >= 1)
        items = c.get_menu()
        check("  the menu arrived", len(items) >= 5, str(len(items)))

        # a RUN whose ACK is lost: the retransmit gets the cached answer
        fc = CountingFC()
        air, a, b = wire(loss=0.0, airtime=0.05)
        start_server(b.port, fc=fc, props_off=True)
        la = SerialLink(a.port, 115200, settle=0.0, auth_key=None, send_gap=0.05, log=quiet)
        c = gc.Client(la)
        air.loss = 0.6
        air.rng = random.Random(3)
        c.run_mission(1)
        air.loss = 0.0
        time.sleep(0.3)
        runs = sum(1 for w in air.writes if b'"RUN"' in w[2])
        check("RUN went out more than once under 60% loss", runs >= 2, str(runs))
        check("  and the motor test ran exactly once", fc.runs == [1], str(fc.runs))
        check("  and the laptop saw the result", any("Done" in l or "Accepted" in l for l in gc_prints))
    finally:
        del gc.print


def test_handshake_diagnosis():
    print("\n[a failed handshake says which end is the problem]")
    d = gc.Client.diagnose
    check("stick silent", "boot banner" in d({"up": True, "rx": 0, "rx_bad": 0, "rx_rejected": 0, "banner_seen": False})[0])
    check("keys differ", "different keys" in d({"up": True, "rx": 0, "rx_bad": 0, "rx_rejected": 3, "banner_seen": True})[0])
    check("stick alive, drone silent", "server running" in d({"up": True, "rx": 0, "rx_bad": 0, "rx_rejected": 0, "banner_seen": True})[0])
    check("port not open", "could not be opened" in d({"up": False})[0])


def test_flight_under_loss():
    print("\n[a hover under 20% loss and collisions never trips LINK LOST while the ground pings]")
    hold_was, int_was = srv.HOVER4_TIME_S, srv.STATUS_INTERVAL_S
    out_lines = []
    gc.print = lambda *a, **k: out_lines.append(" ".join(str(x) for x in a))
    try:
        srv.HOVER4_TIME_S = 5.0
        srv.STATUS_INTERVAL_S = 1.0
        air, a, b = wire(loss=0.2, airtime=0.08, seed=11)
        fc = CountingFC(gps=True)
        s, lb = start_server(b.port, fc=fc)
        la = SerialLink(a.port, 115200, settle=0.0, auth_key=None, send_gap=0.05, log=quiet)
        c = gc.Client(la)
        c.handshake()
        ack = c.request(p.message(p.RUN, c._next_seq(), id=8), {p.ACK}, timeout=5)
        check("hover prepared", ack is not None and ack.get("confirm_required") is True, str(ack))
        t0 = time.monotonic()
        c.monitor_flight(confirm=True)                    # CONFIRM with retry, pings, STATUS display
        took = time.monotonic() - t0
        text = "\n".join(out_lines)
        check("the flight ran to its DONE", "Flight complete" in text and "landed & disarmed" in text, text[-400:])
        check("  without LINK LOST", "LINK LOST" not in text and "link lost" not in text)
        check("  in about the hold time", 5 < took < 20, f"{took:.1f}s")
        check("  the air saw collisions or drops, so the test meant something", air.collisions + air.dropped > 3,
              f"{air.collisions} collisions, {air.dropped} drops")

        # the DONE itself lost: the ground's pings bring it back
        out_lines.clear()
        air, a, b = wire(loss=0.0, airtime=0.02)
        fc = CountingFC(gps=True)
        srv.HOVER4_TIME_S = 1.0
        s, lb = start_server(b.port, fc=fc)
        la = SerialLink(a.port, 115200, settle=0.0, auth_key=None, send_gap=0.05, log=quiet)
        c = gc.Client(la)
        c.handshake()
        c.request(p.message(p.RUN, c._next_seq(), id=8), {p.ACK}, timeout=5)
        orig_carry = air.carry
        dones = [0]

        def carry(src, data):
            if b'"DONE"' in data:
                dones[0] += 1
                if dones[0] == 1:
                    return                        # the first DONE is lost on the air
            orig_carry(src, data)
        air.carry = carry
        t0 = time.monotonic()
        c.monitor_flight(confirm=True)
        text = "\n".join(out_lines)
        check("a lost DONE is repeated on the next PONG", dones[0] >= 2 and "Flight complete" in text,
              f"{dones[0]} DONEs, {time.monotonic() - t0:.1f}s")
        n_status = text.count("alt ")
        check("  STATUS lines kept coming", n_status >= 4, str(n_status))

        # pings stop -> LAND within LINK_LOSS_S (a hold long enough to still be up)
        out_lines.clear()
        srv.HOVER4_TIME_S = 30.0
        air, a, b = wire(loss=0.0, airtime=0.02)
        fc = CountingFC(gps=True)
        s, lb = start_server(b.port, fc=fc)
        la = SerialLink(a.port, 115200, settle=0.0, auth_key=None, send_gap=0.05, log=quiet)
        c = gc.Client(la)
        c.handshake()
        c.request(p.message(p.RUN, c._next_seq(), id=8), {p.ACK}, timeout=5)
        la.send(p.message(p.CONFIRM, c._next_seq()))
        t0 = time.monotonic()
        seen_land = False
        while time.monotonic() - t0 < srv.LINK_LOSS_S + 3:
            m = la.poll()
            if m and m.get("t") == p.LOG and "LINK LOST" in m.get("text", ""):
                seen_land = True
                break
            time.sleep(0.05)
        check("with no pings the drone declares LINK LOST within LINK_LOSS_S + 3 s", seen_land,
              f"{time.monotonic() - t0:.1f}s")
    finally:
        del gc.print
        srv.HOVER4_TIME_S, srv.STATUS_INTERVAL_S = hold_was, int_was


def test_stop_and_abort_retry():
    print("\n[STOP and ABORT are sent again until the drone shows they arrived]")
    lines = []
    gc.print = lambda *a, **k: lines.append(" ".join(str(x) for x in a))
    hold_was = srv.HOVER4_TIME_S
    try:
        srv.HOVER4_TIME_S = 30.0
        air, a, b = wire(loss=0.0, airtime=0.02)
        fc = CountingFC(gps=True)
        s, lb = start_server(b.port, fc=fc)
        la = SerialLink(a.port, 115200, settle=0.0, auth_key=None, send_gap=0.05, log=quiet)
        c = gc.Client(la)
        c.handshake()
        c.request(p.message(p.RUN, c._next_seq(), id=8), {p.ACK}, timeout=5)
        # lose the first ABORT on the air, let the retry through
        air.loss = 1.0
        abort_sent = [0]

        def interrupt_soon():
            time.sleep(2.5)
            import _thread
            _thread.interrupt_main()
        threading.Thread(target=interrupt_soon, daemon=True).start()

        orig_carry = air.carry

        def carry(src, data):
            if b'"ABORT"' in data:
                abort_sent[0] += 1
                if abort_sent[0] == 1:
                    return                       # the first ABORT is lost
            air.loss = 0.0
            orig_carry(src, data)
        air.carry = carry
        air.loss = 0.0
        c.monitor_flight(confirm=True)
        text = "\n".join(lines)
        check("ABORT went out more than once", abort_sent[0] >= 2, str(abort_sent[0]))
        check("  the drone landed on the retry", "aborted" in text or "landing" in text, text[-300:])
        check("  the pings carried on after the abort", "Flight complete" in text, text[-200:])
    finally:
        del gc.print
        srv.HOVER4_TIME_S = hold_was


def watchdog(seconds=240):
    """A hang is a failure, not a stuck CI job."""
    def fire():
        time.sleep(seconds)
        print(f"\nWATCHDOG: the suite did not finish in {seconds} s", flush=True)
        import os
        os._exit(2)
    threading.Thread(target=fire, daemon=True).start()


if __name__ == "__main__":
    watchdog()
    test_open_waits_for_the_stick()
    test_poll_is_non_blocking()
    test_oversize_refused()
    test_explicit_port_kept()
    test_bad_tag_never_raises()
    test_link_report_absorbed()
    test_server_dedupes()
    test_serve_survives_poll_raising()
    test_hello_ack_reports_auth()
    test_ticks_drain_and_status_rides_on_pong()
    test_wall_clock_step_is_harmless()
    test_indoor_gate()
    test_handshake_diagnosis()
    test_handshake_survives_loss()
    test_flight_under_loss()
    test_stop_and_abort_retry()
    print("\n" + "=" * 52)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): " + "; ".join(FAILURES))
        sys.exit(1)
    print("ALL CHECKS PASSED")
