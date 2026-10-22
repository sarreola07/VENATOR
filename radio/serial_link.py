"""One serial transport for every tool that talks to a LoRa stick.

There used to be three near-copies of this — link_test.Link, the Jetson's
LoRaLink and the ground client's SerialTransport — and they drifted. The
reconnect fix landed in two of them; exclusive=True was missing from the third;
and the ground client never got the send pacing the other two had, so its abort
and stop paths could put two lines into a half-duplex radio with no gap. Each
of those was the same bug found three times, which is what having three copies
buys you.

The differences that were real are options here, and nothing else differs.

Stdlib + pyserial, like everything else in radio/.
"""
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

# The firmware prints a boot banner. Tools that open a stick fresh wait it out
# and drop it; long-running services that expect to reopen mid-session do not.
DEFAULT_SETTLE_S = 2.0

# A stick re-enumerates when it is unplugged, when USB resets, or when the
# Jetson browns out. It comes back on the same port a second or two later.
RECONNECT_WAIT_S = 2.0


class LinkDown(RuntimeError):
    """The stick's serial port is not currently usable."""


class SerialLink:
    """A paced, line-oriented protocol link over a LoRa stick's serial port.

    settle        seconds to wait after opening before trusting the stream
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
    port_finder   optional callable re-consulted on every reconnect attempt, so
                  a stick that comes back on a different node is still found.
                  Without it the first resolved path is frozen for the process's
                  life, which defeats drone/c2_server.py's find_lora_device()
                  ("so a replug (ttyUSB0->ttyUSB1) can't kill the service").
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
        self._buf = ""
        self._last_send = 0.0
        self._retry_at = 0.0
        self._down_reported = False
        self.auth_key = _auth.load_key() if auth_key is self._UNSET else auth_key
        self._seen = []          # replay window for this receiver
        self._rejected = 0
        self._port_finder = port_finder
        self._ever_open = False   # distinguishes "not there yet" from "went away"
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
        # Re-resolve first: a stick that re-enumerated may be on another node,
        # and freezing the path found at construction is what find_lora_device()
        # in drone/c2_server.py exists to avoid.
        if self._port_finder is not None:
            found = self._port_finder()
            if found and found != self.port:
                self._log("LoRa device now {}".format(found))
                self.port = found
        # exclusive=True so a stray serial monitor cannot grab the port and
        # silently eat half the conversation.
        self.ser = serial.Serial(self.port, self.baud, timeout=0.2, exclusive=True)
        self._ever_open = True
        self._buf = ""
        if self.settle > 0:
            time.sleep(self.settle)
            self.ser.reset_input_buffer()    # drop the firmware's boot banner

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
        self._retry_at = time.time() + RECONNECT_WAIT_S

    def _ensure(self):
        """True if the port is usable. Retries on a timer while it is not."""
        if self.ser is not None:
            return True
        if time.time() < self._retry_at:
            return False
        try:
            self._open()
        except Exception:
            self._retry_at = time.time() + RECONNECT_WAIT_S
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
        if not self._ensure():
            if self.raise_on_down:
                raise LinkDown("{} is not available".format(self.port))
            return False
        gap = self.send_gap - (time.time() - self._last_send)
        if gap > 0:
            time.sleep(gap)
        if self.auth_key:
            msg = _auth.sign(msg, self.auth_key)
        try:
            self.ser.write(p.encode(msg).encode("utf-8"))
            self.ser.flush()
        except Exception as exc:
            self._drop(exc)
            if self.raise_on_down:
                raise LinkDown("{} went away mid-send".format(self.port)) from exc
            return False
        self._last_send = time.time()
        return True

    def poll(self):
        """Next protocol message, or None. With report_raw, a non-protocol line
        comes back as ("raw", text) rather than being swallowed."""
        if not self._ensure():
            return None
        try:
            data = self.ser.read(256).decode("utf-8", errors="replace")
        except Exception as exc:
            self._drop(exc)
            return None
        if data:
            self._buf += data
        if "\n" not in self._buf:
            return None
        line, self._buf = self._buf.split("\n", 1)
        msg = p.decode(line)
        if msg is None:
            if self.report_raw and line.strip():
                return ("raw", line.strip())
            return None
        if self.auth_key:
            if not _auth.verify(msg, self.auth_key, self._seen):
                self._rejected += 1
                # Say it once, then rarely: a mismatched key or an unsigned
                # peer would otherwise bury the console, and that is the state
                # this is most likely to be in.
                if self._rejected == 1 or self._rejected % 50 == 0:
                    self._log("dropped {} unauthenticated message(s) on {} - "
                              "does the other end have the same key?".format(
                                  self._rejected, self.port))
                return None
            msg = _auth.strip(msg)
        return msg

    @property
    def authenticated(self):
        return bool(self.auth_key)

    def close(self):
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass
        self.ser = None
