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
    """

    # On the class, not just the module, so a subclass can be asked what pacing
    # it uses and could raise it. tests/test_missions.py asserts this directly —
    # the gap is a safety property of the link, not an implementation detail.
    MIN_SEND_GAP_S = MIN_SEND_GAP_S

    _UNSET = object()

    def __init__(self, port, baud=115200, *, settle=0.0, report_raw=False,
                 raise_on_down=False, send_gap=None, log=print, auth_key=_UNSET):
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
        self._open()

    # --- the port ---------------------------------------------------------
    def _open(self):
        import serial
        # exclusive=True so a stray serial monitor cannot grab the port and
        # silently eat half the conversation.
        self.ser = serial.Serial(self.port, self.baud, timeout=0.2, exclusive=True)
        self._buf = ""
        if self.settle > 0:
            time.sleep(self.settle)
            self.ser.reset_input_buffer()    # drop the firmware's boot banner

    def _drop(self, exc):
        """The port went away. Report it once, not once per read."""
        if not self._down_reported:
            self._log("{} went away ({}) - retrying every {:g}s".format(
                self.port, exc, RECONNECT_WAIT_S))
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
