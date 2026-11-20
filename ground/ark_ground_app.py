#!/usr/bin/env python3
"""
ARK ground station application — laptop-side CLI for indoor hovering via LoRa.

Validates that the ARK sensor is ready for flight and triggers the hover mission
(4 feet, 10 seconds) on the drone via LoRa commands.

Usage:
    python ark_ground_app.py --check              # Validate ARK sensor
    python ark_ground_app.py --hover              # Run full hover mission (4 ft, 10s)
    python ark_ground_app.py --port /dev/ttyUSB0  # Specify LoRa device (auto-detect)

Workflow:
    1. Connect to drone via LoRa
    2. Run ARK validation (--check)
    3. If ready, trigger hover mission (--hover)
    4. Confirm arming when prompted
    5. Monitor flight to completion
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radio import protocol as p
from radio.serial_link import SerialLink

# Menu ids on the drone (drone/c2_server.py menu()). Ints, because the handheld
# remote's menu is `struct Item { int id; ... }` and could never send a string.
ARK_CHECK_ID = 9
HOVER_ID = 8

C_OK = "\033[92m"
C_WARN = "\033[93m"
C_ERR = "\033[91m"
C_DIM = "\033[90m"
C_OFF = "\033[0m"


def autodetect_port():
    """Find the first LoRa stick (Heltec V3 / CP210x)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    CP210X_VID = 0x10C4
    for pi in list_ports.comports():
        if pi.vid == CP210X_VID:
            return pi.device
    return None


class ARKClient:
    def __init__(self, port=None):
        if port is None:
            port = autodetect_port()
        if port is None:
            raise RuntimeError("LoRa device not found. Use --port to specify.")
        self.link = SerialLink(port, raise_on_down=True, settle=2.0)
        self.seq = 0

    def _next_seq(self):
        self.seq += 1
        return self.seq

    def request(self, msg, want_types, timeout=8.0):
        """Send message, wait for one of want_types. want_types can be str or list."""
        want = {want_types} if isinstance(want_types, str) else set(want_types)
        self.link.send(msg)
        end = time.time() + timeout
        while time.time() < end:
            r = self.link.poll()
            if r is None:
                time.sleep(0.05)
                continue
            if r.get("t") == p.LOG:
                print(f"{C_DIM}  drone: {r.get('text', '')}{C_OFF}")
                continue
            if r.get("t") in want:
                return r
        return None

    def handshake(self):
        """Link check: HELLO → HELLO_ACK."""
        print("Linking to drone...")
        r = self.request(p.message(p.HELLO, self._next_seq()), p.HELLO_ACK)
        if r is None:
            print(f"{C_ERR}✗ No response. Is the drone on and in range?{C_OFF}")
            return False
        armed = "ARMED" if r.get("armed") else "disarmed"
        gps = r.get("gps", "?")
        batt = r.get("batt", "?")
        print(f"{C_OK}✓ Connected{C_OFF}  "
              f"{armed} | GPS: {gps} | Batt: {batt}V")
        return True

    def check_ark(self):
        """Validate ARK sensor readiness."""
        print("\n=== ARK Sensor Check ===")
        r = self.request(p.message(p.RUN, self._next_seq(), id=ARK_CHECK_ID),
                         [p.ACK, p.DONE], timeout=20.0)
        if r is None:
            print(f"{C_ERR}✗ No response from drone{C_OFF}")
            return False

        if r.get("t") == p.ACK:
            if r.get("accepted"):
                print(f"{C_OK}✓ Check started{C_OFF}")
            else:
                reason = r.get("reason", "unknown reason")
                print(f"{C_ERR}✗ Check failed: {reason}{C_OFF}")
                return False

        # Collect LOG messages until DONE
        while True:
            r = self.link.poll()
            if r is None:
                time.sleep(0.05)
                continue
            if r.get("t") == p.LOG:
                text = r.get("text", "")
                # Parse the log level prefix if present
                if text.startswith("["):
                    print(f"  {text}")
                else:
                    print(f"  {text}")
            elif r.get("t") == p.DONE:
                result = r.get("result", "unknown")
                if "fail" in result.lower() or "error" in result.lower():
                    print(f"{C_WARN}⚠ ARK Check: {result}{C_OFF}")
                    return False
                print(f"{C_OK}✓ ARK ready{C_OFF}")
                return True
            elif r.get("t") in [p.ACK, p.PING, p.PONG]:
                continue
            else:
                time.sleep(0.05)

    def run_hover(self):
        """Trigger hover mission: takeoff to 4 ft, hold 10s, land."""
        print("\n=== Hover Mission (4 ft, 10 s) ===")

        # Send RUN
        r = self.request(p.message(p.RUN, self._next_seq(), id=HOVER_ID),
                         p.ACK, timeout=5.0)
        if r is None:
            print(f"{C_ERR}✗ No response from drone{C_OFF}")
            return False

        if not r.get("accepted"):
            reason = r.get("reason", "unknown")
            print(f"{C_ERR}✗ Drone rejected: {reason}{C_OFF}")
            return False

        print(f"{C_OK}✓ Mission accepted, waiting for CONFIRM prompt{C_OFF}")

        # Wait for drone to ask for CONFIRM (usually comes in mission prep)
        for _ in range(50):  # 5 second timeout
            r = self.link.poll()
            if r is None:
                time.sleep(0.1)
                continue
            if r.get("t") == p.LOG:
                text = r.get("text", "")
                print(f"  {text}")
                if "confirm" in text.lower() or "ready" in text.lower():
                    break
            time.sleep(0.05)

        # CONFIRM is a human's decision, never this script's. The two-step arm
        # exists so that no single command can put the aircraft in the air, and
        # a script that confirms its own RUN deletes the step it is built on.
        # The server lapses the request after PENDING_CONFIRM_S (60 s), so a
        # prompt left unanswered fails safe on its own.
        print(f"\n{C_WARN}The drone is asking for CONFIRM. This ARMS the "
              f"aircraft and takes off.{C_OFF}")
        print(f"{C_DIM}RC transmitter on and bound, kill switch in your hand, "
              f"area clear, props torqued. You have 60 s.{C_OFF}")
        try:
            answer = input("Type FLY to launch, anything else to cancel: ").strip()
        except EOFError:
            answer = ""          # piped or non-interactive: never launch
        if answer != "FLY":
            print(f"{C_WARN}Cancelled — sending ABORT{C_OFF}")
            self.request(p.message(p.ABORT, self._next_seq()), p.ACK, timeout=3.0)
            return False

        print("Confirming arming...")
        r = self.request(p.message(p.CONFIRM, self._next_seq()),
                         p.ACK, timeout=3.0)
        if r is None:
            print(f"{C_WARN}⚠ No CONFIRM ack (may still proceed){C_OFF}")

        # Collect LOG and STATUS messages until DONE
        print("\nFlight in progress...")
        while True:
            r = self.link.poll()
            if r is None:
                time.sleep(0.05)
                continue
            if r.get("t") == p.LOG:
                text = r.get("text", "")
                print(f"  {text}")
            elif r.get("t") == p.STATUS:
                alt = r.get("alt", 0)
                mode = r.get("mode", "?")
                print(f"  alt={alt:.1f}m mode={mode}")
            elif r.get("t") == p.DONE:
                result = r.get("result", "unknown")
                print(f"{C_OK}✓ Flight complete: {result}{C_OFF}")
                return True
            elif r.get("t") in [p.PING, p.PONG]:
                continue
            else:
                time.sleep(0.05)

    def close(self):
        self.link.close()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="LoRa device (default: auto-detect)")
    ap.add_argument("--check", action="store_true",
                    help="Validate ARK sensor and show results")
    ap.add_argument("--hover", action="store_true",
                    help="Run full hover mission (4 ft, 10 s)")
    ap.add_argument("--demo", action="store_true", help="Offline demo (no hardware)")
    args = ap.parse_args()

    if not (args.check or args.hover):
        ap.print_help()
        return 1

    if args.demo:
        print(f"{C_WARN}Demo mode (no hardware){C_OFF}")
        return 0

    try:
        client = ARKClient(port=args.port)

        if not client.handshake():
            return 1

        if args.check:
            success = client.check_ark()
            return 0 if success else 1

        if args.hover:
            if not client.check_ark():
                print(f"{C_ERR}ARK sensor not ready. Fix issues before flying.{C_OFF}")
                return 1
            if not client.run_hover():
                return 1

        return 0

    except KeyboardInterrupt:
        print(f"\n{C_WARN}Cancelled{C_OFF}")
        return 130
    except Exception as exc:
        print(f"{C_ERR}✗ Error: {exc}{C_OFF}")
        return 2
    finally:
        try:
            client.close()
        except:
            pass


if __name__ == "__main__":
    sys.exit(main())
