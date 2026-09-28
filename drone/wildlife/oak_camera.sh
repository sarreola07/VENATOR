#!/usr/bin/env bash
# Camera 1 — OAK-D-S2 wildlife detection.
#
#   ./oak_camera.sh              # detect animals/people, print distance
#   ./oak_camera.sh view         # live view, auto day (colour) / night (mono)
#   ./oak_camera.sh day|night    # force one mode
#   ./oak_camera.sh calibrate    # AE readings, to tune the thresholds
#   ./oak_camera.sh info         # what OAK is this, which sensors, IR?
#   ./oak_camera.sh test         # prove it streams colour + stereo depth
#   ./oak_camera.sh images DIR   # run the detector over image files
#   ./oak_camera.sh status       # who currently owns the OAK
#
# Environment overrides:
#   CONF=0.5           confidence threshold
#   MIN_DIST/MAX_DIST  range gate in metres
#   SAVE_DIR           where annotated detections are written
#
# TWO PYTHONS, ON PURPOSE. This uses depthai 3.10 in ~/oak-venv. The flight
# person-tracker (../camera_publisher.py) uses depthai 2.32 in
# ~/oak_drone_project/depthai-env. The APIs are incompatible and neither script
# runs in the other's interpreter — see ../../docs/WILDLIFE_CAMERA.md.
set -uo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
# shellcheck source=lib_pid.sh
. "$HERE/lib_pid.sh"
PY="${OAK_PY:-/home/jetson/oak-venv/bin/python}"
LOG="${XDG_STATE_HOME:-$HOME/.local/state}/wildlife/oak.log"
mkdir -p "$(dirname "$LOG")"

CONF="${CONF:-0.5}"
MIN_DIST="${MIN_DIST:-0.3}"
MAX_DIST="${MAX_DIST:-35}"
SAVE_DIR="${SAVE_DIR:-$HOME/Pictures/wildlife}"

die() { echo "ERROR: $*" >&2; exit 1; }

[ -x "$PY" ] || die "depthai interpreter not found at $PY
Install it with:  $PY -m pip install depthai
or set OAK_PY to the right interpreter."

"$PY" -c 'import depthai' 2>/dev/null \
  || die "depthai is not installed in $PY
Run:  ${PY%/python}/pip install depthai"

# The OAK allows exactly one host process. The flight tracker and this detector
# both want it, so say plainly who has it rather than failing with a device
# error 20 seconds later.
tracker_pid() { script_pid camera_publisher.py; }
mine_pid() { script_pid oak_wildlife.py; }

check_free() {
    local t; t="$(tracker_pid)"
    if [ -n "$t" ]; then
        die "the flight person-tracker owns the OAK (pid $t).
The device allows only one host process. Stop it first:
    $(cd "$HERE/../.." && pwd)/drone/camera.sh stop"
    fi
    local m; m="$(mine_pid)"
    if [ -n "$m" ]; then
        die "a wildlife detector is already running (pid $m).
Stop it with:  kill $m"
    fi
}

# Launched from a desktop icon, the terminal closes the instant the command
# exits and you never see the output. OAK_HOLD=1 keeps it open.
#
# It lives here rather than in the launcher because the Desktop Entry spec
# forbids ';' and quote characters in Exec, so the usual
# `bash -c 'cmd; read -p ...'` wrapper fails desktop-file-validate. The
# .desktop actions pass `env OAK_HOLD=1` instead, which is spec-clean.
run() {
    if [ -n "${OAK_HOLD:-}" ]; then
        "$@"
        rc=$?
        echo
        read -r -p "Press Enter to close... " _
        exit $rc
    fi
    exec "$@"
}

case "${1:-detect}" in
    detect)
        check_free
        mkdir -p "$SAVE_DIR"
        echo "OAK wildlife detection — Ctrl+C to stop.  log: $LOG"
        # No exec here: the pipeline into tee needs this shell to stay alive.
        "$PY" "$HERE/oak_wildlife.py" \
            --conf "$CONF" --min-dist "$MIN_DIST" --max-dist "$MAX_DIST" \
            --save-dir "$SAVE_DIR" 2>&1 | tee -a "$LOG"
        exit "${PIPESTATUS[0]}"
        ;;
    view|daynight)
        # Live view that picks colour or mono from what auto-exposure is doing.
        check_free
        run "$PY" "$HERE/oak_daynight.py" "${@:2}"
        ;;
    night)
        check_free
        run "$PY" "$HERE/oak_daynight.py" --force night "${@:2}"
        ;;
    day)
        check_free
        run "$PY" "$HERE/oak_daynight.py" --force day "${@:2}"
        ;;
    calibrate)
        check_free
        run "$PY" "$HERE/oak_daynight.py" --calibrate
        ;;
    info)
        check_free
        run "$PY" "$HERE/oak_info.py"
        ;;
    test)
        check_free
        run "$PY" "$HERE/oak_test.py" --depth
        ;;
    images)
        shift
        [ $# -ge 1 ] || die "usage: $0 images <directory-or-image> [extra args]"
        check_free
        run "$PY" "$HERE/test_detector.py" "$@"
        ;;
    classes)
        check_free
        run "$PY" "$HERE/oak_wildlife.py" --list-classes
        ;;
    status)
        t="$(tracker_pid)"; m="$(mine_pid)"
        [ -n "$t" ] && echo "OAK: owned by the flight person-tracker (pid $t)"
        [ -n "$m" ] && echo "OAK: owned by the wildlife detector (pid $m)"
        [ -z "$t$m" ] && echo "OAK: free"
        usb=$(for d in /sys/bus/usb/devices/*/idVendor; do
                  [ "$(cat "$d" 2>/dev/null)" = "03e7" ] || continue
                  printf '%s Mbps' "$(cat "$(dirname "$d")/speed" 2>/dev/null)"
              done)
        [ -n "$usb" ] && echo "USB link: $usb" || echo "USB link: no 03e7 device present"
        # `|| true`: read returns non-zero at EOF, which would otherwise make a
        # perfectly successful status report exit 1.
        if [ -n "${OAK_HOLD:-}" ]; then echo; read -r -p "Press Enter to close... " _ || true; fi
        ;;
    *)
        die "unknown command '$1' (expected detect, view, day, night, calibrate, info, test, images, classes or status)"
        ;;
esac
