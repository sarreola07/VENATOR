#!/usr/bin/env python3
"""
Venator GCS — portable laptop client (Windows / Mac / Linux).

Plug in the Heltec LoRa stick, run this, and it links to the Jetson and shows
the mission menu the Jetson advertises. One option lets you send waypoints for
the drone to fly to.

    python gcs_client.py            # auto-detect the LoRa stick
    python gcs_client.py --port COM5
    python gcs_client.py --mock     # no hardware: demo against a fake Jetson

Packaged into VenatorGCS(.exe/.app) by the GitHub Actions workflow.
"""
import argparse
import queue
import sys
import threading
import time
from pathlib import Path


# Runnable from any folder: put the repo root on the import path so the
# sibling packages (radio/, drone/, ground/) import the same modules
# whether this is started by path, by a desktop launcher or by systemd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radio import protocol as p
from radio.serial_link import SerialLink, DEFAULT_SETTLE_S

_clock = time.monotonic   # pacing and timeouts must not follow a clock step

REQUEST_RETRY_S = 2.0     # resend a command this often until its reply comes
CONFIRM_RETRY_S = 6.0     # CONFIRM: expect the drone to say something within this
CONFIRM_TRIES = 3
CMD_RETRY_S = 2.0         # STOP / ABORT in flight
CMD_TRIES = 5
QUIET_WARN_S = 5.0        # in flight, warn when the drone has said nothing for this long
DONE_WAIT_S = 90.0        # after an abort, how long to keep listening for DONE
DISARMED_WAIT_S = 12.0    # the drone reports disarmed: wait this long for its DONE, then stop

CP210X_VID = 0x10C4   # Heltec V3 onboard USB-serial (Silicon Labs CP2102)

C_OK = "\033[92m"
C_WARN = "\033[93m"
C_ERR = "\033[91m"
C_DIM = "\033[90m"
C_OFF = "\033[0m"


# --------------------------------------------------------------------------
# Transports: something that can send() and poll() protocol messages.
# --------------------------------------------------------------------------
class SerialTransport(SerialLink):
    """The ground station's link. Keeps running when the stick goes away so it
    can carry on once it is back; anything already in the air is covered by the
    drone's own link-loss RTL.

    Inherits the send pacing it used to lack — its abort and stop paths could
    emit two lines in one loop iteration with no gap between them."""

    def __init__(self, port, baud=115200):
        # settle: the stick reboots when the port opens and the first HELLO
        # used to go into that reboot. port_finder: a stick that re-enumerates
        # on another port mid-session is found again.
        super().__init__(port, baud, raise_on_down=False, settle=DEFAULT_SETTLE_S,
                         port_finder=autodetect_port,
                         log=lambda m: print("\n" + m, flush=True))


class MockTransport:
    """In-process fake Jetson so the client runs with no hardware."""

    def __init__(self):
        self.jetson = MockJetson()
        self._out = []          # messages queued for the client to poll()

    def send(self, m):
        self._out.extend(self.jetson.handle(m))

    def poll(self):
        return self._out.pop(0) if self._out else None

    def close(self):
        pass


class MockJetson:
    """Minimal fake of the Jetson C2 server for offline demos."""

    MENU = [
        {"id": 1, "name": "Sequential motor test", "needs": "props_off"},
        {"id": 2, "name": "All-motor test",        "needs": "props_off"},
        {"id": 3, "name": "Fly to waypoints",      "needs": "props_on", "gps": True},
        {"id": 4, "name": "Mission 1: hover + detect + land", "needs": "props_on", "gps": True},
        {"id": 5, "name": "Mission 2: follow person", "needs": "props_on", "gps": True},
    ]

    def handle(self, m):
        t = m.get("t")
        seq = m.get("seq", 0)
        if t == p.HELLO:
            return [p.message(p.HELLO_ACK, seq, proto=p.PROTO_VERSION,
                              armed=False, gps="no fix", batt=11.4)]
        if t == p.GET_MENU:
            return [p.message(p.MENU, seq, item=it, last=(i == len(self.MENU) - 1))
                    for i, it in enumerate(self.MENU)]
        if t == p.PING:
            return [p.message(p.PONG, seq)]
        if t == p.RUN:
            mid = m.get("id")
            item = next((i for i in self.MENU if i["id"] == mid), None)
            if item is None:
                return [p.message(p.ACK, seq, id=mid, accepted=False, reason="unknown mission")]
            if item.get("gps"):
                return [p.message(p.ACK, seq, id=mid, accepted=False,
                                  reason="no GPS fix (mock)")]
            return [p.message(p.ACK, seq, id=mid, accepted=True),
                    p.message(p.DONE, seq, id=mid, result="ok (mock)")]
        if t == p.WP_BEGIN:
            self._wp = []
            return [p.message(p.ACK, seq, ready=True)]
        if t == p.WP:
            self._wp.append(m)
            return [p.message(p.ACK, seq, i=m.get("i"))]
        if t == p.WP_END:
            n = len(getattr(self, "_wp", []))
            return [p.message(p.ACK, seq, uploaded=n, rejected=0,
                              note="stored (mock — no GPS, would not fly)")]
        if t == p.FLY_REQ:
            return [p.message(p.ACK, seq, accepted=False, reason="no GPS fix (mock)")]
        return []


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
def autodetect_port():
    """Return the serial device of the first CP210x (Heltec) found, or None."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    for pi in list_ports.comports():
        if pi.vid == CP210X_VID:
            return pi.device
    return None


class Console:
    """One reader thread for stdin, for the whole session.

    The follow monitor used to start a thread per flight that read one line;
    the thread outlived the flight and ate the next menu choice, and a second
    Enter during a flight did nothing. Every prompt goes through here instead,
    and the monitors can look for a line without blocking."""

    def __init__(self):
        self._q = queue.Queue()
        self._started = False
        self._eof = False

    def _start(self):
        if self._started:
            return
        self._started = True

        def pump():
            while True:
                line = sys.stdin.readline()
                if not line:
                    self._q.put(None)
                    return
                self._q.put(line.rstrip("\r\n"))
        threading.Thread(target=pump, daemon=True).start()

    def ask(self, prompt):
        """Like input(): prints the prompt, returns the line. EOFError at end."""
        self._start()
        if self._eof:
            raise EOFError
        print(prompt, end="", flush=True)
        while True:
            try:
                line = self._q.get(timeout=0.25)   # stays interruptible
            except queue.Empty:
                continue
            if line is None:
                self._eof = True
                raise EOFError
            return line

    def pending(self):
        """A line typed since last asked, or None. Never blocks."""
        self._start()
        try:
            line = self._q.get_nowait()
        except queue.Empty:
            return None
        if line is None:
            self._eof = True
            return None
        return line


console = Console()


def ask(prompt):
    return console.ask(prompt)


def _seq_matches(reply, sent_seq):
    """A reply answers our message when it echoes the seq. seq 0 or none is a
    server-initiated message (LOG, STATUS, DONE from a flight): accepted too."""
    rs = reply.get("seq")
    return rs in (None, 0) or rs == sent_seq


class Client:
    def __init__(self, transport):
        self.tx = transport
        self.seq = 0

    def _next_seq(self):
        self.seq += 1
        return self.seq

    # -- one request, retried ---------------------------------------------------
    def request(self, m, want, timeout=5.0, retry_s=None):
        """Send a message and wait for a reply of type in `want` (set/str).

        The same message (same seq) goes out again every `retry_s` until the
        reply comes or `timeout` passes. The server answers a repeat from its
        cache, so a retransmit never runs a command twice. Replies carrying
        another seq are someone else's and are skipped, not taken."""
        want = {want} if isinstance(want, str) else set(want)
        if retry_s is None:
            retry_s = REQUEST_RETRY_S          # read at call time: tests shorten it
        sent_seq = m.get("seq")
        end = _clock() + timeout
        next_send = 0.0
        tries = 0
        while _clock() < end:
            if _clock() >= next_send:
                if tries:
                    print(f"{C_DIM}  (no reply yet — sending {m.get('t')} again){C_OFF}")
                self.tx.send(m)
                tries += 1
                next_send = _clock() + retry_s
            r = self.tx.poll()
            if r is None:
                time.sleep(0.02)
                continue
            if r.get("t") == p.LOG:
                print(f"{C_DIM}  drone: {r.get('text','')}{C_OFF}")
                continue
            if r.get("t") in want and _seq_matches(r, sent_seq):
                return r
        return None

    def _link_stats(self):
        s = getattr(self.tx, "stats", None)
        return s() if callable(s) else None

    def handshake(self):
        print("Linking to drone...")
        r = None
        for attempt in range(3):
            r = self.request(p.message(p.HELLO, self._next_seq()), p.HELLO_ACK, timeout=6)
            if r is not None:
                break
            if attempt < 2:
                print(f"{C_WARN}No answer yet — trying again...{C_OFF}")
        if r is None:
            print(f"{C_ERR}No response from the Jetson.{C_OFF}")
            for line in self.diagnose(self._link_stats()):
                print(f"{C_WARN}  {line}{C_OFF}")
            return False
        print(f"{C_OK}Connected ✓{C_OFF}  proto v{r.get('proto')}  "
              f"armed={r.get('armed')}  gps={r.get('gps')}  batt={r.get('batt')} V")
        if r.get("indoor"):
            print(f"{C_WARN}Indoor mode on the drone: the hover is gated on the ARK Flow position.{C_OFF}")
        mine = bool(getattr(self.tx, "authenticated", False))
        if "auth" in r and bool(r["auth"]) != mine:
            print(f"{C_WARN}Only {'this laptop' if mine else 'the drone'} has a key: the other end "
                  f"will drop everything signed. Put the same key on both, or on neither.{C_OFF}")
        return True

    @staticmethod
    def diagnose(stats):
        """Why a handshake got nothing, from the link's own counters."""
        if not stats:
            return ["Is it powered and in range?"]
        if not stats.get("up"):
            return ["The LoRa stick's port could not be opened. Is it plugged in? "
                    "Is another program (a serial monitor) holding it?"]
        if stats.get("rx_rejected"):
            return ["The drone answered, but the signature did not verify: the two "
                    "machines have different keys (radio/auth.py).  See docs/SECURITY.md."]
        if stats.get("rx"):
            return ["Replies arrived but not a HELLO_ACK — a stale server? Try again."]
        if not stats.get("banner_seen") and not stats.get("rx_bad"):
            return ["Nothing at all came from the stick, not even its boot banner. "
                    "Wrong port, wrong baud, or the stick is not running the Venator firmware. "
                    "Try: python3 radio/link_test.py --list"]
        return ["The stick is alive but nothing came back from the drone. Is the Jetson's "
                "server running (systemctl status venator-c2) and its stick plugged in? "
                "Are both sticks on the same radio settings?"]

    def get_menu(self):
        # The menu is streamed one item per packet (each fits a LoRa frame), so
        # collect MENU messages until the one flagged last. LoRa is lossy, so
        # accept only well-formed items and de-duplicate by id — a corrupted
        # packet must never crash the client or show a bogus mission.
        #
        # Each item is its own packet and any of them can be lost, so the menu
        # is asked for again until a round brings nothing new: a lost item in
        # the middle is recovered by the next round and deduplicated by id.
        items, seen = [], set()
        dropped = 0
        end = _clock() + 10
        rounds = 0
        while _clock() < end and rounds < 4:
            rounds += 1
            req = p.message(p.GET_MENU, self._next_seq())
            self.tx.send(req)
            sent_at = _clock()
            new, saw_last, heard = 0, False, False
            round_end = min(end, _clock() + 3)
            while _clock() < round_end:
                r = self.tx.poll()
                if r is None:
                    # The request itself can be lost. Until the first item of
                    # this round arrives, send it again (same seq) on the usual
                    # retry period; once items are flowing, sending would only
                    # collide with the drone's stream on the half-duplex air.
                    if not heard and _clock() - sent_at >= REQUEST_RETRY_S:
                        self.tx.send(req)
                        sent_at = _clock()
                    time.sleep(0.02)
                    continue
                if r.get("t") != p.MENU:
                    continue
                heard = True
                it = r.get("item")
                if isinstance(it, dict):
                    if isinstance(it.get("id"), int) and isinstance(it.get("name"), str):
                        if it["id"] not in seen:
                            seen.add(it["id"])
                            items.append(it)
                            new += 1
                    else:
                        dropped += 1
                if r.get("last"):
                    saw_last = True
                    break
            if saw_last and (new == 0 or rounds >= 2) and items:
                break
            if not saw_last and items and rounds >= 3:
                break
        if dropped:
            print(f"{C_WARN}({dropped} menu packet(s) arrived corrupted and were "
                  f"ignored — pick 'r' to refresh){C_OFF}")
        items.sort(key=lambda i: i["id"])
        return items

    def run_mission(self, mid):
        r = self.request(p.message(p.RUN, self._next_seq(), id=mid), {p.ACK}, timeout=8)
        if r is None:
            print(f"{C_ERR}No ACK — command may not have arrived.{C_OFF}")
            return
        if not r.get("accepted", False):
            print(f"{C_WARN}Rejected: {r.get('reason','?')}{C_OFF}")
            return
        print(f"{C_OK}Accepted.{C_OFF} Running...")
        d = self.request(p.message(p.PING, self.seq), {p.DONE}, timeout=60)
        if d:
            print(f"{C_OK}Done:{C_OFF} {d.get('result','')}")

    def upload_waypoints(self):
        try:
            n = int(ask("How many waypoints? ").strip())
        except ValueError:
            print("Not a number."); return
        wps = []
        for i in range(n):
            raw = ask(f"  #{i+1} as lat,lon,alt(m): ").strip()
            try:
                lat, lon, alt = (float(x) for x in raw.split(","))
            except ValueError:
                print("  bad format, expected e.g. 37.4208,-122.0841,30"); return
            wps.append((lat, lon, alt))
        print(f"Sending {len(wps)} waypoints...")
        self.request(p.message(p.WP_BEGIN, self._next_seq(), count=len(wps)), {p.ACK})
        for i, (lat, lon, alt) in enumerate(wps):
            self.request(p.message(p.WP, self._next_seq(), i=i, lat=lat, lon=lon, alt=alt), {p.ACK})
        r = self.request(p.message(p.WP_END, self._next_seq()), {p.ACK})
        if not r or not r.get("uploaded"):
            print(f"{C_ERR}Upload failed:{C_OFF} {r.get('note','') if r else 'no response'}")
            return
        print(f"{C_OK}Upload result:{C_OFF} {r.get('uploaded')} stored, "
              f"{r.get('rejected')} rejected. {r.get('note','')}")
        self.fly_uploaded_mission()

    def fly_uploaded_mission(self):
        """Two-step arm+fly of the uploaded mission, then monitor the flight."""
        if ask("\nArm and FLY this mission now? (type FLY, else skip): ").strip().lower() != "fly":
            print("Mission stored on the drone; not flying now.")
            return
        # step 1 — ask the drone if it's safe to fly
        ack = self.request(p.message(p.FLY_REQ, self._next_seq()), {p.ACK}, timeout=8)
        if not ack or not ack.get("accepted"):
            print(f"{C_WARN}Cannot fly: {ack.get('reason') if ack else 'no response'}{C_OFF}")
            return
        # step 2 — explicit second confirmation
        print(f"{C_WARN}SAFETY: {ack.get('reason')}{C_OFF}")
        print(f"{C_WARN}The drone will ARM and TAKE OFF. Ctrl-C during flight = abort (return home).{C_OFF}")
        if ask("Type LAUNCH to arm and take off: ").strip().lower() != "launch":
            print("Aborted — not flying.")
            return
        self.monitor_flight(confirm=True)

    def mission_1_flow(self, mid):
        """Mission 1: server prepares (takeoff/hover/detect/land), two-step confirm."""
        ack = self.request(p.message(p.RUN, self._next_seq(), id=mid), {p.ACK}, timeout=10)
        if not ack or not ack.get("accepted"):
            print(f"{C_WARN}Cannot start Mission 1: {ack.get('reason') if ack else 'no response'}{C_OFF}")
            return
        print(f"{C_WARN}SAFETY: {ack.get('reason')}{C_OFF}")
        print(f"{C_DIM}Start the AI camera first (./ai_camera.sh start) so it can detect people.{C_OFF}")
        print(f"{C_WARN}The drone will ARM and TAKE OFF. Ctrl-C during flight = abort (return home).{C_OFF}")
        if ask("Type LAUNCH to arm and take off: ").strip().lower() != "launch":
            print("Aborted — not flying.")
            return
        self.monitor_flight(confirm=True)

    def mission_2_flow(self, mid):
        """Mission 2 (follow-me): prepare, two-step confirm, then follow monitor."""
        ack = self.request(p.message(p.RUN, self._next_seq(), id=mid), {p.ACK}, timeout=10)
        if not ack or not ack.get("accepted"):
            print(f"{C_WARN}Cannot start Mission 2: {ack.get('reason') if ack else 'no response'}{C_OFF}")
            return
        print(f"{C_WARN}SAFETY: {ack.get('reason')}{C_OFF}")
        print(f"{C_DIM}Start the AI camera first (./ai_camera.sh start) so it can see the person.{C_OFF}")
        print(f"{C_WARN}The drone will ARM, TAKE OFF, and FOLLOW. Ctrl-C = abort (RTL).{C_OFF}")
        if ask("Type LAUNCH to arm and take off: ").strip().lower() != "launch":
            print("Aborted — not flying.")
            return
        self.monitor_follow(confirm=True)

    # -- in flight ------------------------------------------------------------------
    def monitor_follow(self, confirm=False):
        """Follow monitor: pings + live status; type Enter to STOP (land), Ctrl-C to abort (RTL)."""
        print(f"{C_OK}Following.{C_OFF} Press Enter to STOP (land in place); Ctrl-C to abort (return home).")
        self._monitor("Mission 2 complete", confirm=confirm, allow_stop=True, show=self._show_follow)

    def monitor_flight(self, confirm=False):
        """Send flight heartbeats, show live status, Ctrl-C to abort (RTL)."""
        print(f"{C_OK}Launch confirmed.{C_OFF} Monitoring flight — Ctrl-C to abort (return home).")
        self._monitor("Flight complete", confirm=confirm, allow_stop=False, show=self._show_flight)

    @staticmethod
    def _show_follow(r):
        who = "person YES" if r.get("person") else "person no"
        if r.get("pz"):
            who += f" @ {r.get('pz')} m"
        foll = " following" if r.get("following") else ""
        tag = "  [RTL]" if r.get("rtl") else ""
        print(f"{C_OK}alt {r.get('alt')} m  {r.get('phase')}  {who}{foll}{tag}{C_OFF}")

    @staticmethod
    def _show_flight(r):
        tag = "  [RTL]" if r.get("rtl") else ""
        phase = f"  {r['phase']}" if r.get("phase") else ""
        who = ""
        if r.get("person") is not None:
            pz = r.get("pz")
            who = ("  person YES" + (f" @ {pz} m" if pz else "")) if r["person"] else "  person no"
            who += f" (seen {r.get('seen', 0)})"
        print(f"{C_OK}alt {r.get('alt')} m  mode {r.get('mode')}{phase}  "
              f"armed {r.get('armed')}{who}{tag}{C_OFF}")

    def _monitor(self, done_label, *, confirm, allow_stop, show):
        """The flight loop, shared by every flight.

        Every second a PING, so the drone knows the link is alive. CONFIRM,
        STOP and ABORT are commands the air can lose, so each is sent again on
        a timer until the drone's own words show it arrived: for CONFIRM any
        LOG/STATUS, for STOP/ABORT a STATUS whose phase says so (or a LOG, or
        the DONE). Ctrl-C aborts; the pings carry on afterwards, since the
        drone treats a silent link as a lost one and the operator still wants
        to see the landing. A quiet link is said out loud after QUIET_WARN_S."""
        pending = None        # {"t", "seq", "sent", "tries", "max", "retry"}
        if confirm:
            pending = {"t": p.CONFIRM, "seq": self._next_seq(), "sent": -1e9,
                       "tries": 0, "max": CONFIRM_TRIES, "retry": CONFIRM_RETRY_S}
        last_ping = -1e9
        last_heard = _clock()
        quiet_said = False
        abort_at = None
        disarmed_at = None
        try:
            while True:
                now = _clock()
                if disarmed_at is not None and now - disarmed_at > DISARMED_WAIT_S:
                    print(f"{C_WARN}The drone reports disarmed but its DONE never arrived. "
                          f"Check it, and the Jetson's journal, before the next flight.{C_OFF}")
                    return
                if abort_at is not None and now - abort_at > DONE_WAIT_S:
                    print(f"{C_WARN}No DONE from the drone after the abort. Its own link-loss "
                          f"failsafe lands it; check the Jetson's journal.{C_OFF}")
                    return
                if allow_stop and console.pending() is not None and pending is None \
                        and abort_at is None:
                    print(f"{C_WARN}STOP — landing in place...{C_OFF}")
                    pending = {"t": p.STOP, "seq": self._next_seq(), "sent": -1e9,
                               "tries": 0, "max": CMD_TRIES, "retry": CMD_RETRY_S}
                if pending is not None and now - pending["sent"] >= pending["retry"]:
                    if pending["tries"] >= pending["max"]:
                        print(f"{C_ERR}{pending['t']} sent {pending['max']} times with no sign it "
                              f"arrived. The drone's link-loss failsafe takes over when the "
                              f"pings stop.{C_OFF}")
                        pending = None
                    else:
                        if pending["tries"]:
                            print(f"{C_DIM}  (sending {pending['t']} again){C_OFF}")
                        self.tx.send(p.message(pending["t"], pending["seq"]))
                        pending["sent"] = now
                        pending["tries"] += 1
                if now - last_ping >= 1.0:
                    self.tx.send(p.message(p.PING, self._next_seq()))
                    last_ping = now
                if not quiet_said and now - last_heard > QUIET_WARN_S:
                    print(f"{C_WARN}link quiet {QUIET_WARN_S:g} s — nothing from the drone{C_OFF}")
                    quiet_said = True
                r = self.tx.poll()
                if r is None:
                    time.sleep(0.05)
                    continue
                last_heard = now
                if quiet_said:
                    print(f"{C_OK}link back{C_OFF}")
                    quiet_said = False
                t = r.get("t")
                if pending is not None and self._acknowledges(pending["t"], r):
                    pending = None
                if t == p.STATUS:
                    show(r)
                    if r.get("armed") is False and disarmed_at is None:
                        disarmed_at = now
                elif t == p.LOG:
                    print(f"{C_DIM}  drone: {r.get('text','')}{C_OFF}")
                elif t == p.ACK and not r.get("accepted", True):
                    print(f"{C_WARN}drone: {r.get('reason','refused')}{C_OFF}")
                    if abort_at is None and pending is None:
                        return           # the launch was refused: nothing is flying
                elif t == p.DONE:
                    print(f"{C_OK}{done_label}:{C_OFF} {r.get('result','')}")
                    return
        except KeyboardInterrupt:
            if abort_at is not None:
                print(f"\n{C_WARN}Already aborting. Ctrl-C again to leave the monitor.{C_OFF}")
            else:
                print(f"\n{C_WARN}ABORT — telling the drone to return home...{C_OFF}")
            # Fall into the same loop: the abort is retried like STOP, the pings
            # continue, and the landing is shown. A second Ctrl-C leaves.
            abort_at = _clock()
            pending = {"t": p.ABORT, "seq": self._next_seq(), "sent": -1e9,
                       "tries": 0, "max": CMD_TRIES, "retry": CMD_RETRY_S}
            try:
                self._monitor_after_abort(done_label, pending, show, abort_at)
            except KeyboardInterrupt:
                print(f"\n{C_WARN}Left the monitor. The drone's own failsafe lands it when "
                      f"the pings stop.{C_OFF}")

    def _monitor_after_abort(self, done_label, pending, show, abort_at):
        last_ping = -1e9
        while _clock() - abort_at < DONE_WAIT_S:
            now = _clock()
            if pending is not None and now - pending["sent"] >= pending["retry"]:
                if pending["tries"] >= pending["max"]:
                    print(f"{C_ERR}ABORT sent {pending['max']} times with no sign it arrived.{C_OFF}")
                    pending = None
                else:
                    if pending["tries"]:
                        print(f"{C_DIM}  (sending ABORT again){C_OFF}")
                    self.tx.send(p.message(pending["t"], pending["seq"]))
                    pending["sent"] = now
                    pending["tries"] += 1
            if now - last_ping >= 1.0:
                self.tx.send(p.message(p.PING, self._next_seq()))
                last_ping = now
            r = self.tx.poll()
            if r is None:
                time.sleep(0.05)
                continue
            t = r.get("t")
            if pending is not None and self._acknowledges(p.ABORT, r):
                pending = None
            if t == p.STATUS:
                show(r)
            elif t == p.LOG:
                print(f"{C_DIM}  drone: {r.get('text','')}{C_OFF}")
            elif t == p.DONE:
                print(f"{C_OK}{done_label}:{C_OFF} {r.get('result','')}")
                return
        print(f"{C_WARN}No DONE from the drone after the abort. Its own link-loss failsafe "
              f"lands it; check the Jetson's journal.{C_OFF}")

    @staticmethod
    def _acknowledges(cmd, r):
        """Whether reply r shows the drone acted on cmd (CONFIRM/STOP/ABORT)."""
        t = r.get("t")
        if t == p.DONE:
            return True
        if cmd == p.CONFIRM:
            return t in (p.LOG, p.STATUS, p.ACK)
        if t == p.ACK:
            return True                       # e.g. "no flight running ... landing"
        if t == p.STATUS:
            phase = str(r.get("phase") or "")
            return phase in ("STOP", "ABORT", "RTL", "LINKLOSS") or bool(r.get("rtl"))
        if t == p.LOG:
            text = str(r.get("text") or "")
            return cmd in text or "landing" in text or "returning" in text
        return False


def flag_label(item):
    bits = []
    if item.get("needs") == "props_off":
        bits.append("props OFF")
    elif item.get("needs") == "props_on":
        bits.append("props ON")
    if item.get("gps"):
        bits.append("needs GPS")
    return f"  {C_DIM}({', '.join(bits)}){C_OFF}" if bits else ""


def menu_loop(client):
    items = client.get_menu()
    if not items:
        print(f"{C_ERR}The drone sent no menu.{C_OFF}")
        return
    while True:
        print("\n=== Missions ===")
        for it in items:
            # .get() everywhere: never let odd remote data crash the client
            print(f"  {it.get('id','?')}) {it.get('name','(unnamed)')}{flag_label(it)}")
        print("  r) Refresh menu     q) Quit")
        choice = ask("\nSelect: ").strip().lower()
        if choice == "q":
            print("Bye.")
            return
        if choice == "r":
            fresh = client.get_menu()
            if fresh:
                items = fresh
            else:
                print(f"{C_WARN}No menu received — the drone may be out of range.{C_OFF}")
            continue
        if not choice.isdigit():
            print("Enter a number or q."); continue
        mid = int(choice)
        item = next((i for i in items if i.get("id") == mid), None)
        if item is None:
            print("No such mission."); continue
        name = item.get("name", "").lower()
        try:
            if name.startswith("fly to waypoints"):
                client.upload_waypoints()       # collect + upload + two-step fly
            elif name.startswith("mission 1"):
                client.mission_1_flow(mid)      # prepare + two-step fly (hover+detect)
            elif name.startswith("mission 2"):
                client.mission_2_flow(mid)      # prepare + two-step fly (follow-me)
            else:
                client.run_mission(mid)         # motor tests, props toggle, etc.
        except KeyboardInterrupt:
            print(f"\n{C_WARN}Cancelled — back to the menu.{C_OFF}")
        except Exception as exc:
            # Never let one bad exchange end the session while you're in the field.
            print(f"{C_ERR}Command failed: {exc}{C_OFF}")
            print(f"{C_DIM}(still connected — pick another option, or 'r' to refresh){C_OFF}")
        # The props toggle changes the menu labels, so refresh after it
        if "toggle props" in name:
            fresh = client.get_menu()
            if fresh:
                items = fresh


def main():
    ap = argparse.ArgumentParser(description="Venator GCS — portable LoRa client")
    ap.add_argument("--port", help="serial port (default: auto-detect the Heltec)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--mock", action="store_true", help="run against a fake Jetson (no hardware)")
    args = ap.parse_args()

    print("=" * 48)
    print(" Venator GCS — drone command over LoRa")
    print("=" * 48)

    if args.mock:
        print(f"{C_WARN}[mock mode] no hardware — talking to a simulated Jetson{C_OFF}")
        tx = MockTransport()
    else:
        port = args.port or autodetect_port()
        if not port:
            print(f"{C_ERR}No LoRa stick found.{C_OFF} Plug in the Heltec, or pass --port, "
                  f"or use --mock to demo without hardware.")
            return 1
        print(f"Using LoRa stick on {port}")
        try:
            tx = SerialTransport(port, args.baud)
            if tx.authenticated:
                print(f"{C_OK}Link authenticated.{C_OFF}")
            else:
                print(f"{C_WARN}The command link is NOT authenticated — anything in "
                      f"radio range can command the aircraft.{C_OFF}\n"
                      f"{C_DIM}  python3 radio/auth.py --init   (on this machine and "
                      f"the Jetson, same key){C_OFF}")
        except Exception as e:
            print(f"{C_ERR}Could not open {port}: {e}{C_OFF}")
            return 1

    client = Client(tx)
    try:
        if client.handshake():
            menu_loop(client)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except EOFError:
        print("\nBye.")
    finally:
        tx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
