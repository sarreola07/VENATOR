"""One serial transport for every tool that talks to a LoRa stick.

There used to be three near-copies of this — link_test.Link, the Jetson's
LoRaLink and the ground client's SerialTransport — and they drifted. The
reconnect fix landed in two of them; exclusive=True was missing from the third;
and the ground client never got the send pacing the other two had, so its abort
and stop paths could put two lines into a half-duplex radio with no gap. Each
of those was the same bug found three times, which is what having three copies
buys you.

The differences that were real are options here, and nothing else differs.

What the link guarantees, and why each one exists:

  * It waits for the stick to boot. Opening the port toggles DTR/RTS and the
    ESP32 reboots for about two seconds, printing its banner when it is ready.
    A message written before that is lost in the reboot. The bench tool waited
    a fixed two seconds; the ground client and the Jetson waited nothing, and
    the laptop's first HELLO went into a rebooting stick. That was the usual
    "nothing at all" session. Now every open waits for the banner (or `settle`
    seconds, whichever is first), on the first open and on every reconnect.
  * poll() never blocks when a line is already buffered, and never blocks on
    the port when nothing is waiting. It used to read(256) with a 0.2 s timeout
    on every call, which stalled the flight loop 0.2 s a tick and drained a
    backlog of pings at five a second.
  * A line the firmware would cut (over 240 bytes, after signing) is refused
    here rather than sent as broken JSON.
  * Every timer is monotonic. The Jetson has no RTC battery, so the wall clock
    steps when NTP arrives, and a step forward used to look like link loss.
  * Counters: how much came in, how much of it was junk or unsigned, how much
    went out or was dropped, when the peer was last heard, and the RSSI/SNR of
    the last packet when the stick firmware reports it. The handshake failure
    messages and the server's journal line come from these.

Stdlib + pyserial, like everything else in radio/.
"""
import threading
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radio import protocol as p
from radio import auth as _auth

# The Heltec firmware is half-duplex and its UART buffer is only ~256 B. Sending
# faster than the radio drains overflows it and silently corrupts messages, so
# every writer paces. This is not tuning — it is the reason messages arrive.
MIN_SEND_GAP_S = 0.30

# How long an open waits for the firmware's boot banner before trusting the
# stream. The ESP32 reboots when the port opens and is up again in about two
# seconds; the banner ends the wait early, so a stick that did not reboot (a
# port opened without toggling DTR) costs the full wait only once.
DEFAULT_SETTLE_S = 2.5

# A stick re-enumerates when it is unplugged, when USB resets, or when the
# Jetson browns out. It comes back on the same port a second or two later.
RECONNECT_WAIT_S = 2.0

# The firmware cuts a line at this many bytes and sends what it has, which the
# other end then drops as broken JSON. Checked after signing, which adds ~38 B.
MAX_LINE = 240

# Bytes with no newline in them are not a line, and a stick printing garbage
# must not grow memory forever.
MAX_BUFFER = 4096

# What LoRa_Transceiver.ino prints once it is up. The prefix is what the open
# waits for; the rest of the line may carry a version.
BANNER = b"Venator LoRa transceiver ready"

# A line the bridge firmware emits after each received packet with the radio's
# own view of the link. Absorbed into stats(), never handed to callers.
LINK_REPORT = "LINK"

# Unreadable lines are logged, a few of them, so their source can be told from
# the journal: this many at first, then every fiftieth, each cut to this length.
BAD_LINE_SAMPLES = 3
BAD_LINE_SHOW = 80

_clock = time.monotonic


class LinkDown(RuntimeError):
    """The stick's serial port is not currently usable."""


class SerialLink:
    """A paced, line-oriented protocol link over a LoRa stick's serial port.

    settle        seconds to wait, at most, for the stick's boot banner after
                  opening before trusting the stream; 0 trusts it at once
    report_raw    return ("raw", text) for lines that are not protocol, instead
                  of dropping them — a silent link and a chatty one look very
                  different, and bench tools want to see the difference
    raise_on_down raise LinkDown from send() instead of dropping the message.
                  Interactive tools want to tell someone; long-running servers
                  want to stay up and answer once the stick is back.
    auth_key      shared secret. Defaults to whatever radio/auth.py finds; None
                  disables signing entirely. With a key, outbound messages are
                  signed and inbound ones that do not verify are dropped before
                  the caller sees them. Without one the link behaves exactly as
                  it did before authentication existed. See docs/SECURITY.md.
    defer_open    tolerate the stick being absent at construction: set the
                  reconnect timer instead of raising, so the caller comes up and
                  _ensure() picks the port up within RECONNECT_WAIT_S. For a
                  boot service, where the stick may still be enumerating -- the
                  Pixhawk on this airframe has taken minutes -- and where
                  raising means systemd restarts every RestartSec forever
                  instead of waiting. Off by default so interactive tools keep
                  failing immediately and visibly.
    port_finder   optional callable consulted when the configured port cannot
                  be opened, so a stick that comes back on a different node is
                  still found. An explicit port that works is never replaced.
    """

    # On the class, not just the module, so a subclass can be asked what pacing
    # it uses and could raise it. tests/test_missions.py asserts this directly —
    # the gap is a safety property of the link, not an implementation detail.
    MIN_SEND_GAP_S = MIN_SEND_GAP_S

    _UNSET = object()

    def __init__(self, port, baud=115200, *, settle=0.0, report_raw=False,
                 raise_on_down=False, send_gap=None, log=print, auth_key=_UNSET,
                 defer_open=False, port_finder=None):
        self.port, self.baud, self.settle = port, baud, settle
        self.report_raw, self.raise_on_down = report_raw, raise_on_down
        self.send_gap = self.MIN_SEND_GAP_S if send_gap is None else send_gap
        self._log = log
        self.ser = None
        self._buf = b""
        self._last_send = -1e9
        self._retry_at = 0.0
        self._down_reported = False
        self.auth_key = _auth.load_key() if auth_key is self._UNSET else auth_key
        self._seen = []          # replay window for this receiver
        self._rejected = 0
        self._port_finder = port_finder
        self._ever_open = False   # distinguishes "not there yet" from "went away"
        # send() and poll() may be called from two threads (link_test --chat,
        # phone_relay). Re-entrant, because send() may reconnect, which logs.
        self._lock = threading.RLock()
        self._stats = {"rx": 0, "rx_bad": 0, "rx_rejected": 0, "tx": 0,
                       "tx_dropped": 0, "opens": 0, "banner_seen": False,
                       "rssi": None, "snr": None}
        self._last_rx = None
        self._oversize_reported = 0
        if defer_open:
            # A missing stick is a wait, not a failure. Report it through the
            # same path as a mid-session loss so the message and the retry timer
            # are identical, then let _ensure() open it when it appears.
            try:
                self._open()
            except Exception as exc:
                self._drop(exc)
        else:
            self._open()

    # --- the port ---------------------------------------------------------
    def _open(self):
        import serial
        # exclusive=True so a stray serial monitor cannot grab the port and
        # silently eat half the conversation.
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.2, exclusive=True)
        except Exception:
            # The configured port is gone. A stick that re-enumerated may be on
            # another node, which is what find_lora_device() in
            # drone/c2_server.py exists to find. An explicit port that opens is
            # never second-guessed.
            found = self._port_finder() if self._port_finder is not None else None
            if not found or found == self.port:
                raise
            self._log("LoRa device now {}".format(found))
            self.port = found
            self.ser = serial.Serial(self.port, self.baud, timeout=0.2, exclusive=True)
        self._ever_open = True
        self._stats["opens"] += 1
        self._buf = b""
        self._settle()

    def _settle(self):
        """Wait for the stick to finish rebooting: its banner, or `settle` seconds.

        Opening the port resets the ESP32. Anything written before it is back
        up is lost, and its ROM boot text would otherwise arrive as junk.
        """
        if self.settle <= 0:
            return
        deadline = _clock() + self.settle
        seen = b""
        while _clock() < deadline:
            try:
                waiting = getattr(self.ser, "in_waiting", None)
                data = self.ser.read(waiting if waiting else 1)
            except Exception:
                data = b""
            if data:
                seen += data
                if BANNER in seen:
                    self._stats["banner_seen"] = True
                    break
                seen = seen[-512:]
            else:
                time.sleep(0.02)
        try:
            self.ser.reset_input_buffer()    # drop the firmware's boot banner
        except Exception:
            pass

    def _drop(self, exc):
        """The port is unusable. Report it once, not once per read."""
        if not self._down_reported:
            # "went away" is wrong for a port that was never open -- which is
            # the defer_open case at boot, where the stick is simply not
            # enumerated yet. Saying it went away sends people looking for a
            # disconnection that never happened.
            what = "went away" if self._ever_open else "is not there yet"
            self._log("{} {} ({}) - retrying every {:g}s".format(
                self.port, what, exc, RECONNECT_WAIT_S))
            self._down_reported = True
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.ser = None
        self._retry_at = _clock() + RECONNECT_WAIT_S

    def _ensure(self):
        """True if the port is usable. Retries on a timer while it is not."""
        if self.ser is not None:
            return True
        if _clock() < self._retry_at:
            return False
        try:
            self._open()
        except Exception:
            self._retry_at = _clock() + RECONNECT_WAIT_S
            return False
        self._log("{} is back".format(self.port))
        self._down_reported = False
        return True

    @property
    def up(self):
        return self.ser is not None

    # --- traffic ----------------------------------------------------------
    def send(self, msg):
        """True if it went out. Raises LinkDown instead when raise_on_down."""
        with self._lock:
            if not self._ensure():
                if self.raise_on_down:
                    raise LinkDown("{} is not available".format(self.port))
                return False
            if self.auth_key:
                msg = _auth.sign(msg, self.auth_key)
            line = p.encode(msg).encode("utf-8")
            if len(line) > MAX_LINE + 1:            # the newline is not sent on air
                # The firmware would cut this and the other end would drop the
                # remains. Refusing it here is the only way the sender finds out.
                self._stats["tx_dropped"] += 1
                self._oversize_reported += 1
                if self._oversize_reported == 1 or self._oversize_reported % 20 == 0:
                    self._log("message of {} bytes is over the {} byte line limit - "
                              "not sent ({})".format(len(line) - 1, MAX_LINE, msg.get("t")))
                return False
            gap = self.send_gap - (_clock() - self._last_send)
            if gap > 0:
                time.sleep(gap)
            try:
                self.ser.write(line)
                self.ser.flush()
            except Exception as exc:
                self._drop(exc)
                if self.raise_on_down:
                    raise LinkDown("{} went away mid-send".format(self.port)) from exc
                return False
            self._last_send = _clock()
            self._stats["tx"] += 1
            return True

    def poll(self):
        """Next protocol message, or None. With report_raw, a non-protocol line
        comes back as ("raw", text) rather than being swallowed.

        Never blocks: a line already buffered is returned without touching the
        port, and the port is read only for the bytes it says are waiting."""
        with self._lock:
            if isinstance(self._buf, str):         # a test poked a str in
                self._buf = self._buf.encode("utf-8")
            if b"\n" not in self._buf:
                if not self._ensure():
                    return None
                try:
                    waiting = getattr(self.ser, "in_waiting", None)
                    if waiting is None:
                        data = self.ser.read(256)   # a fake serial with no in_waiting
                    elif waiting:
                        data = self.ser.read(waiting)
                    else:
                        return None
                except Exception as exc:
                    self._drop(exc)
                    return None
                if data:
                    self._buf += data
                    if len(self._buf) > MAX_BUFFER:
                        # Keep the tail: if a line is in progress it is there.
                        self._buf = self._buf[-MAX_BUFFER:]
                        self._stats["rx_bad"] += 1
            while b"\n" in self._buf:
                raw, self._buf = self._buf.split(b"\n", 1)
                out = self._line(raw.decode("utf-8", errors="replace"))
                if out is not None:
                    return out
            return None

    def _line(self, line):
        """One complete line: a message to hand up, ("raw", text), or None."""
        msg = p.decode(line)
        if msg is None:
            text = line.strip()
            if not text:
                return None
            if BANNER.decode() in text:
                self._stats["banner_seen"] = True
            else:
                self._stats["rx_bad"] += 1
                # Show what the junk IS, a little of it: the counter alone cannot
                # tell a second remote with a different framing from corrupted
                # packets or a chatty stick. The first few, then one in fifty.
                n = self._stats["rx_bad"]
                if n <= BAD_LINE_SAMPLES or n % 50 == 0:
                    self._log("unreadable line #{} from {}: {!r}".format(
                        n, self.port, text[:BAD_LINE_SHOW]))
            return ("raw", text) if self.report_raw else None
        if msg.get("t") == LINK_REPORT:
            # The bridge's own report of the last packet it heard, when its
            # firmware sends one. Not a protocol message: absorbed here.
            for k in ("rssi", "snr"):
                v = msg.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    self._stats[k] = v
            return None
        if self.auth_key:
            if not _auth.verify(msg, self.auth_key, self._seen):
                self._rejected += 1
                self._stats["rx_rejected"] = self._rejected
                # Say it once, then rarely: a mismatched key or an unsigned
                # peer would otherwise bury the console, and that is the state
                # this is most likely to be in.
                if self._rejected == 1 or self._rejected % 50 == 0:
                    self._log("dropped {} unauthenticated message(s) on {} - "
                              "does the other end have the same key?".format(
                                  self._rejected, self.port))
                return None
            msg = _auth.strip(msg)
        self._stats["rx"] += 1
        self._last_rx = _clock()
        return msg

    # --- health -----------------------------------------------------------
    def stats(self):
        """Counters for a journal line or a diagnosis. `last_rx_s` is how long
        ago the peer was last heard (None: never); `rssi`/`snr` are the stick's
        own reading of the last packet when its firmware reports one."""
        out = dict(self._stats)
        out["up"] = self.up
        out["port"] = self.port
        out["last_rx_s"] = (None if self._last_rx is None
                            else round(_clock() - self._last_rx, 1))
        return out

    @property
    def rejected(self):
        return self._rejected

    @property
    def authenticated(self):
        return bool(self.auth_key)

    def close(self):
        with self._lock:
            try:
                if self.ser is not None:
                    self.ser.close()
            except Exception:
                pass
            self.ser = None
