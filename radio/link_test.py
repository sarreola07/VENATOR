#!/usr/bin/env python3
"""
Venator LoRa link test — non-interactive, two-ended, scriptable.

The firmware README's link check ("open two serial monitors and type a line")
needs a human at each keyboard. This does the same check from the command line
so it can be run over SSH, from a script, or by an agent, and so it reports a
pass/fail exit code instead of a judgement call about what scrolled past.

Run one side as the responder and the other as the initiator:

    # machine B (the Jetson side, or whatever is standing in for it)
    python3 link_test.py --listen

    # machine A (the laptop / GCS side)
    python3 link_test.py --send --count 10

The initiator sends PINGs, the responder answers PONG, and the initiator prints
round-trip times and a loss summary. Exit code is 0 when loss is within
--allow-loss, 1 otherwise — safe to use in scripts.

Free-text mode carries a typed line across the link in either direction:

    python3 link_test.py --chat        # on both machines; type, press Enter

Speaks the same newline-JSON protocol as gcs_client.py and jetson_c2_server.py
(see docs/PROTOCOL.md), so a successful run proves the real link, not a
special-case one. Stdlib + pyserial only, so it runs on macOS, Windows and the
Jetson unchanged.
"""
import argparse
import sys
import threading
import time
from pathlib import Path


# Runnable from any folder: put the repo root on the import path so the
# sibling packages (radio/, drone/, ground/) import the same modules
# whether this is started by path, by a desktop launcher or by systemd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radio import protocol as p

CP210X_VID = 0x10C4     # Heltec V3 onboard USB-serial (Silicon Labs CP2102)

# The Heltec firmware is half-duplex and its UART buffer is only ~256 B, so
# sends are paced exactly as jetson_c2_server.LoRaLink paces them.
MIN_SEND_GAP_S = 0.30

# Opening the port toggles DTR/RTS, which resets the ESP32. Give it time to boot
# and print its banner before expecting it to carry traffic.
DEFAULT_SETTLE_S = 2.0

def _colors_ok():
    """Windows cmd.exe prints raw escape codes as garbage unless VT processing
    is switched on, and redirected output should never carry them at all. Ask
    for VT on Windows and fall back to plain text if it is refused."""
    if not sys.stdout.isatty():
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        # -11 = STD_OUTPUT_HANDLE, 0x4 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
        h = k.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k.SetConsoleMode(h, mode.value | 0x4))
    except Exception:
        return False


if _colors_ok():
    C_OK, C_WARN, C_ERR = "\033[92m", "\033[93m", "\033[91m"
    C_DIM, C_OFF = "\033[90m", "\033[0m"
else:
    C_OK = C_WARN = C_ERR = C_DIM = C_OFF = ""


def list_ports():
    """Every serial port we can see, with the Heltec sticks flagged."""
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return []
    out = []
    for pi in lp.comports():
        out.append((pi.device, pi.description or "", pi.vid == CP210X_VID))
    return out


def autodetect_port():
    """The first CP210x (Heltec) we can see, or None."""
    for device, _desc, is_heltec in list_ports():
        if is_heltec:
            return device
    return None


class Link:
    """A paced, line-oriented protocol link over the LoRa stick's serial port."""

    def __init__(self, port, baud=115200, settle=DEFAULT_SETTLE_S):
        import serial
        # exclusive=True so a stray serial monitor can't grab the port and
        # silently eat half the conversation.
        self.ser = serial.Serial(port, baud, timeout=0.2, exclusive=True)
        self._buf = ""
        self._last_send = 0.0
        if settle > 0:
            time.sleep(settle)
            self.ser.reset_input_buffer()    # drop the firmware's boot banner

    def send(self, msg):
        gap = MIN_SEND_GAP_S - (time.time() - self._last_send)
        if gap > 0:
            time.sleep(gap)
        self.ser.write(p.encode(msg).encode("utf-8"))
        self.ser.flush()
        self._last_send = time.time()

    def poll(self):
        """Next protocol message, or None. Non-protocol lines are returned as
        ('raw', text) so the caller can show the firmware banner rather than
        swallowing it — a silent link and a chatty one look very different."""
        try:
            data = self.ser.read(256).decode("utf-8", errors="replace")
        except Exception as exc:
            print(f"{C_ERR}serial read failed: {exc}{C_OFF}", flush=True)
            return None
        if data:
            self._buf += data
        if "\n" not in self._buf:
            return None
        line, self._buf = self._buf.split("\n", 1)
        msg = p.decode(line)
        if msg is None and line.strip():
            return ("raw", line.strip())
        return msg

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def show(item):
    """Print one polled item; return it if it was a protocol message."""
    if item is None:
        return None
    if isinstance(item, tuple):
        print(f"{C_DIM}  [{time.strftime('%H:%M:%S')}] radio: {item[1]}{C_OFF}", flush=True)
        return None
    return item


def run_listen(link, seconds):
    """Responder: answer PING/HELLO and report everything that arrives."""
    print(f"{C_OK}Listening.{C_OFF} Answering PING and HELLO. Ctrl-C to stop.", flush=True)
    end = time.time() + seconds if seconds else None
    heard = 0
    try:
        while end is None or time.time() < end:
            msg = show(link.poll())
            if msg is None:
                time.sleep(0.02)
                continue
            heard += 1
            t = msg.get("t")
            seq = msg.get("seq", 0)
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] <- {t} seq={seq}"
                  + (f"  {msg.get('text','')!r}" if t == p.LOG else ""), flush=True)
            if t == p.PING:
                link.send(p.message(p.PONG, seq))
                print(f"[{ts}] -> PONG seq={seq}", flush=True)
            elif t == p.HELLO:
                link.send(p.message(p.HELLO_ACK, seq, proto=p.PROTO_VERSION,
                                    armed=False, gps="link test", batt=0.0))
                print(f"[{ts}] -> HELLO_ACK seq={seq}", flush=True)
    except KeyboardInterrupt:
        print("\nstopped.", flush=True)
    print(f"\n{heard} protocol message(s) received.", flush=True)
    return 0 if heard else 1


def run_send(link, count, timeout, allow_loss):
    """Initiator: PING a fixed number of times and measure the round trip."""
    print(f"{C_OK}Pinging the other end{C_OFF} — {count} packet(s), "
          f"{timeout:.1f}s timeout each.", flush=True)
    rtts = []
    lost = 0
    for i in range(1, count + 1):
        seq = i
        sent = time.time()
        link.send(p.message(p.PING, seq))
        deadline = sent + timeout
        got = None
        while time.time() < deadline:
            msg = show(link.poll())
            # Ignore a stale PONG from an earlier, timed-out packet.
            if msg and msg.get("t") == p.PONG and msg.get("seq") == seq:
                got = msg
                break
            if msg is None:
                time.sleep(0.02)
        if got is None:
            lost += 1
            print(f"  seq={seq:<3} {C_ERR}lost{C_OFF} (no PONG in {timeout:.1f}s)", flush=True)
        else:
            rtt = (time.time() - sent) * 1000
            rtts.append(rtt)
            print(f"  seq={seq:<3} {C_OK}pong{C_OFF}  {rtt:7.0f} ms", flush=True)

    loss_pct = 100.0 * lost / count if count else 100.0
    print(f"\n--- link summary ---", flush=True)
    print(f"sent {count}, received {len(rtts)}, lost {lost} ({loss_pct:.0f}% loss)", flush=True)
    if rtts:
        print(f"rtt min/avg/max = {min(rtts):.0f}/{sum(rtts)/len(rtts):.0f}/{max(rtts):.0f} ms",
              flush=True)
    if loss_pct <= allow_loss:
        print(f"{C_OK}Link OK ✓{C_OFF}  (loss within the {allow_loss:.0f}% allowance)", flush=True)
        return 0
    print(f"{C_ERR}Link FAILED{C_OFF} — {loss_pct:.0f}% loss exceeds the "
          f"{allow_loss:.0f}% allowance.", flush=True)
    if not rtts:
        print("Nothing came back at all. Check that the other end is running "
              "--listen, that both sticks have the transceiver sketch, and that "
              "both are on 915 MHz / SF7 / syncword 0x12.", flush=True)
    return 1


def run_chat(link):
    """Free text both ways: stdin goes out as LOG, arrivals print as they land."""
    eof = "Ctrl-Z then Enter" if sys.platform == "win32" else "Ctrl-D"
    print(f"{C_OK}Chat mode.{C_OFF} Type a line and press Enter to send it. "
          f"Ctrl-C (or {eof}) to quit.", flush=True)
    stop = threading.Event()

    def rx():
        while not stop.is_set():
            msg = show(link.poll())
            if msg is None:
                time.sleep(0.02)
                continue
            if msg.get("t") == p.LOG:
                print(f"{C_WARN}them>{C_OFF} {msg.get('text','')}", flush=True)
            else:
                print(f"{C_DIM}  ({msg.get('t')} seq={msg.get('seq')}){C_OFF}", flush=True)

    reader = threading.Thread(target=rx, daemon=True)
    reader.start()
    seq = 0
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            seq += 1
            # MAX_LINE in the firmware is 240 B and the JSON wrapper costs ~25 B.
            if len(line) > 180:
                print(f"{C_WARN}too long — trimmed to 180 characters{C_OFF}", flush=True)
                line = line[:180]
            link.send(p.message(p.LOG, seq, text=line))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        reader.join(timeout=1.0)
    print("\nchat ended.", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Two-ended LoRa link test for the Venator C2 link.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--listen", action="store_true",
                      help="responder: answer PING/HELLO and print what arrives")
    mode.add_argument("--send", action="store_true",
                      help="initiator: send PINGs and measure the round trip")
    mode.add_argument("--chat", action="store_true",
                      help="send typed lines both ways as free text")
    mode.add_argument("--list", action="store_true",
                      help="list serial ports and exit")
    ap.add_argument("--port", default="auto",
                    help="serial port, or 'auto' to detect the Heltec by USB ID")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--count", type=int, default=10, help="--send: packets to send")
    ap.add_argument("--timeout", type=float, default=5.0,
                    help="--send: seconds to wait for each PONG")
    ap.add_argument("--allow-loss", type=float, default=20.0,
                    help="--send: loss %% that still counts as a pass (default 20)")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="--listen: stop after this long (default: until Ctrl-C)")
    ap.add_argument("--settle", type=float, default=DEFAULT_SETTLE_S,
                    help="seconds to wait after opening the port for the ESP32 to reboot")
    args = ap.parse_args()

    if args.list:
        ports = list_ports()
        if not ports:
            print("No serial ports found (is pyserial installed?).")
            return 1
        for device, desc, is_heltec in ports:
            tag = f"  {C_OK}<- Heltec LoRa{C_OFF}" if is_heltec else ""
            print(f"{device:<28} {desc}{tag}")
        return 0

    if not (args.listen or args.send or args.chat):
        ap.error("pick a mode: --listen, --send, --chat or --list")

    port = autodetect_port() if args.port == "auto" else args.port
    if port is None:
        print(f"{C_ERR}No Heltec stick found.{C_OFF} Plug it in, or name the port "
              f"with --port. `--list` shows what is attached.", flush=True)
        return 1

    print(f"Using {port} @ {args.baud} baud.", flush=True)
    try:
        link = Link(port, args.baud, settle=args.settle)
    except Exception as exc:
        print(f"{C_ERR}Could not open {port}: {exc}{C_OFF}", flush=True)
        print("On macOS use the /dev/cu.* name, not /dev/tty.*. On Linux make "
              "sure you are in the 'dialout' group (see setup.sh).", flush=True)
        return 1

    try:
        if args.listen:
            return run_listen(link, args.seconds)
        if args.send:
            return run_send(link, args.count, args.timeout, args.allow_loss)
        return run_chat(link)
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
