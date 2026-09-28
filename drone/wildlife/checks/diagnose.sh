#!/usr/bin/env bash
# Run the IMX219 health check and show the result in a GUI window.
# Used by the "Run health check" action of wildlife-camera.desktop.
set -uo pipefail

CHECK="$(dirname "$(readlink -f "$0")")/check_camera.sh"
export DISPLAY="${DISPLAY:-:1}"

if [ ! -x "$CHECK" ]; then
  zenity --error --no-wrap --title="IMX219 Camera" \
         --text="check_camera.sh not found at:\n$CHECK" 2>/dev/null
  exit 1
fi

# Strip ANSI colour so it renders cleanly in the zenity text view.
out=$("$CHECK" 2>&1 | sed 's/\x1b\[[0-9;]*m//g')
rc=$?

if [ $rc -eq 0 ]; then
  icon=info;  title="IMX219 Camera - healthy"
else
  icon=error; title="IMX219 Camera - problems found"
fi

printf '%s\n' "$out" | zenity --text-info \
  --title="$title" --width=640 --height=420 --font=monospace 2>/dev/null

command -v notify-send >/dev/null 2>&1 && \
  notify-send -i "camera-video" "IMX219 health check" \
    "$(printf '%s\n' "$out" | tail -1)"

exit $rc
