#!/usr/bin/env bash
# START the guided ARK Flow calibration:
#
#   bash ~/Desktop/VENATOR-flight/deploy/ark_calibration.sh
#   (or double-click "ARK calibration" on the Desktop)
#
# STOP it at any time with Ctrl+C, or by closing the window. After that only the
# Pixhawk's stream-rate restore is sent, and the report is saved. Nothing has been
# changed unless you typed YES to a change.
#
# This script does NOT change the C2 service's mode. It only:
#   1. asks you to confirm the kill switch is ON and the handheld is off the USB;
#   2. stops venator-c2 (asks for your password), because only one program may read
#      the Pixhawk port;
#   3. runs the calibration.
# The service stays stopped afterwards and starts again by itself on the next boot,
# in the mode its drop-in already holds (shown below).
set -u
WT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$WT/venv/bin/python"
say() { printf '%s\n' "$*"; }

say "== VENATOR ARK Flow calibration =="
say "Code: $WT  ($(git -C "$WT" log --oneline -1 2>/dev/null))"
[ -x "$PY" ] || { say "No Python at $PY - stopping."; exit 1; }
say "Service mode: $(bash "$WT/deploy/flight_mode.sh" status 2>/dev/null | head -1)"
say ""
say "The props are fitted. Before anything else:"
say "  - RC transmitter ON, KILL SWITCH ON"
say "  - handheld remote unplugged from the Jetson (battery-powered is fine)"
read -r -p "Kill switch ON and handheld unplugged? [y/N] " a
case "$a" in y|Y|yes|YES) ;; *) say "Stopped - nothing was changed."; exit 1 ;; esac

find_pix() { ls /dev/serial/by-id/*PX4* /dev/serial/by-id/*FMU* /dev/ttyACM* 2>/dev/null | head -1; }
pix=$(find_pix)
while [ -z "$pix" ]; do
  say ""
  say "The Pixhawk is NOT connected to the Jetson (no USB device for it)."
  say "Plug the Pixhawk's USB cable in at BOTH ends: the Jetson's USB hub and the Pixhawk."
  read -r -p "Press Enter to check again, or Ctrl+C to quit ... " _
  pix=$(find_pix)
done
say "Pixhawk: $pix"

n=$(ls /dev/ttyUSB* 2>/dev/null | wc -l)
if [ "$n" -gt 1 ]; then
  say "Two LoRa sticks are on the Jetson's USB. Unplug the HANDHELD, then run this again."
  exit 1
fi

if systemctl is-active --quiet venator-c2; then
  say ""
  say "Stopping venator-c2 so the calibration can use the Pixhawk (asks for your password)."
  sudo systemctl stop venator-c2 || { say "Could not stop venator-c2 - stopping."; exit 1; }
fi
if systemctl is-active --quiet venator-c2; then
  say "venator-c2 is still running - stopping."
  exit 1
fi

say ""
say "Starting the calibration menu: Enter = do the next check, a number = do or redo"
say "that check, A = apply changes (YES each), V = live readings, Q = quit and save."
"$PY" "$WT/drone/ark_calibrate.py"
rc=$?
say ""
say "Calibration ended. venator-c2 is still STOPPED."
say "It starts by itself on the next boot (power-cycle) in this mode:"
say "  $(bash "$WT/deploy/flight_mode.sh" status 2>/dev/null | head -1)"
say "For the indoor flight it must read FLIGHT (props ON) and INDOOR. If it does not:"
say "  cd ~/Desktop/VENATOR-flight && bash deploy/flight_mode.sh on indoor"
exit $rc
