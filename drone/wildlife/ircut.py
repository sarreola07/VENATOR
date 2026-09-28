#!/usr/bin/env python3
"""
Day/night switching for the Waveshare IMX219-160 IR-CUT module on a Jetson.

    ./ircut.py status
    ./ircut.py night        # IR-CUT filter OFF -> IR passes -> night vision
    ./ircut.py day          # IR-CUT filter ON  -> normal daylight colour
    ./ircut.py --pin 13 night

WIRING (required - there is no software-only path)
-------------------------------------------------
The 22-pin CAM0 connector carries no spare GPIO, so the IR-CUT control line
has to come off the 40-pin header:

    camera board "IR-CUT" / IO pad  ->  Jetson 40-pin GPIO (default BOARD 7)
    camera board GND                ->  Jetson 40-pin GND (pin 6, 9, 14, ...)

Per Waveshare's documentation for this module:
    HIGH (3.3 V) = infrared filter OFF = night vision mode
    LOW  (GND)   = infrared filter ON  = daytime mode

The Jetson's 40-pin GPIO is 3.3 V logic, which matches the camera board's
3.3 V operating voltage. Do NOT drive this pad from a 5 V pin.

WHAT THIS SCRIPT CANNOT DO
--------------------------
The infrared LED illuminator boards are a separate thing. They are wired to
the camera board's 3.3 V output pads, so they are lit whenever the module has
power - there is no register or GPIO behind them. To switch those you would
have to feed their 3.3 V through a MOSFET or a transistor driven by another
GPIO. Nothing in V4L2, GStreamer or Argus can toggle them.

IR light is invisible to the eye. To check whether the LEDs are on, point a
phone camera at them: most phone sensors see 850 nm as a faint purple glow.
"""

import argparse
import sys
import time

# HIGH removes the filter. Named so the intent is readable at the call site.
NIGHT, DAY = 1, 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("day", "night", "status", "blink"),
                    help="day = filter on, night = filter off, "
                         "blink = alternate 3x to confirm wiring")
    ap.add_argument("--pin", type=int, default=7, metavar="BOARD_PIN",
                    help="40-pin header pin number driving IR-CUT (default 7)")
    args = ap.parse_args()

    try:
        import Jetson.GPIO as GPIO
    except ModuleNotFoundError:
        print("error: Jetson.GPIO not available (expected 2.1.13 on this board)",
              file=sys.stderr)
        return 1

    GPIO.setmode(GPIO.BOARD)
    GPIO.setwarnings(False)

    try:
        if args.mode == "status":
            # Read without taking ownership as an output, so we do not disturb
            # whatever level is currently applied.
            GPIO.setup(args.pin, GPIO.IN)
            lvl = GPIO.input(args.pin)
            print(f"BOARD pin {args.pin}: {'HIGH' if lvl else 'LOW'}  ->  "
                  f"{'night vision (IR-CUT filter OFF)' if lvl else 'daytime (IR-CUT filter ON)'}")
            print("\nNote: if nothing is wired to this pin the reading is a "
                  "floating value and means nothing.")
            print("A magenta/pink cast in the image is the reliable indicator "
                  "that the filter is OFF.")
            return 0

        GPIO.setup(args.pin, GPIO.OUT)

        if args.mode == "blink":
            print(f"Alternating BOARD pin {args.pin} 3x (watch for the filter "
                  f"to click and the colour cast to change)...")
            for i in range(3):
                GPIO.output(args.pin, NIGHT)
                print(f"  {i+1}/3 HIGH - night"); time.sleep(1.5)
                GPIO.output(args.pin, DAY)
                print(f"  {i+1}/3 LOW  - day");   time.sleep(1.5)
            return 0

        level = NIGHT if args.mode == "night" else DAY
        GPIO.output(args.pin, level)
        print(f"BOARD pin {args.pin} driven {'HIGH' if level else 'LOW'} -> "
              f"{args.mode} mode")
        if args.mode == "night":
            print("Expect a magenta/pink cast: the Bayer filters do not block IR.")
        else:
            print("Expect natural colour to return.")
        # Deliberately no GPIO.cleanup(): that would release the line and let it
        # float, undoing the mode the moment this process exits.
        return 0

    except RuntimeError as e:
        print(f"error: {e}\n"
              "If this is a permissions problem, add yourself to the gpio group:\n"
              "  sudo usermod -aG gpio $USER   (then log out and back in)\n"
              "or run this script with sudo.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
