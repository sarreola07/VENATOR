#!/usr/bin/env bash
# Camera 1 — OAK-D-S2 wildlife detection.
#
#   ./oak_camera.sh              # detect animals/people, print distance
#   ./oak_camera.sh gui          # operator GUI for a phone, on :8080
#   ./oak_camera.sh stop         # release the OAK (handles the boot service too)
#   ./oak_camera.sh restart      # stop, then start the GUI
#   ./oak_camera.sh view         # live view, auto day (colour) / night (mono)
#   ./oak_camera.sh day|night    # force one mode
#   ./oak_camera.sh calibrate    # AE readings, to tune the thresholds
#   ./oak_camera.sh info         # what OAK is this, which sensors, IR?
#   ./oak_camera.sh test         # prove it streams colour + stereo depth
#   ./oak_camera.sh images DIR   # run the detector over image files
#   ./oak_camera.sh status       # who currently owns the OAK
#
# Environment overrides:
#   CONF               force ONE confidence threshold for every class. Unset by
#                      default, which is what you want: classes.py holds a
#                      per-class threshold table, and setting CONF throws it
#                      away. Only useful for sweeps.
#   MODEL              HubAI model id (default: MegaDetector V6, see classes.py)
#   SHAVES             recompile the network for N SHAVE cores (default: archive)
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

# Deliberately NOT defaulted: an unset CONF leaves the per-class thresholds in
# classes.py in charge. Defaulting it to 0.5 (as this did) silently collapsed
# the whole table back to one global number.
CONF="${CONF:-}"
MODEL="${MODEL:-}"
SHAVES="${SHAVES:-}"
MIN_DIST="${MIN_DIST:-0.3}"
MAX_DIST="${MAX_DIST:-35}"
SAVE_DIR="${SAVE_DIR:-$HOME/Pictures/wildlife}"

# Build the optional flags once, so every call site stays readable.
OPTS=()
[ -n "$CONF" ]   && OPTS+=(--conf "$CONF")
[ -n "$MODEL" ]  && OPTS+=(--model "$MODEL")
[ -n "$SHAVES" ] && OPTS+=(--shaves "$SHAVES")

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
gui_pid() { script_pid gui_server.py; }

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
    # The GUI owns the device too. Without this it was invisible to the
    # arbitration and you got a bare X_LINK_DEVICE_ALREADY_IN_USE twenty
    # seconds in - the exact failure this function exists to prevent.
    local g; g="$(gui_pid)"
    if [ -n "$g" ]; then
        # Once the GUI runs as a boot service, telling someone to kill the pid
        # is wrong advice: systemd restarts it five seconds later and the
        # device is busy again. Name the unit instead.
        if systemctl is-active --quiet venator-gui.service 2>/dev/null; then
            die "the operator GUI owns the OAK and runs as a boot service (pid $g).
Stop it with:  sudo systemctl stop venator-gui
It will come back on the next boot; 'sudo systemctl disable venator-gui'
stops that too."
        fi
        die "the operator GUI owns the OAK (pid $g).
Stop it with:  $HERE/oak_camera.sh stop"
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
            "${OPTS[@]+"${OPTS[@]}"}" \
            --min-dist "$MIN_DIST" --max-dist "$MAX_DIST" \
            --save-dir "$SAVE_DIR" 2>&1 | tee -a "$LOG"
        exit "${PIPESTATUS[0]}"
        ;;
    gui)
        # Operator GUI: live MJPEG off the camera's own encoder, detections
        # over SSE, boxes drawn in the browser. Nothing is decoded here.
        check_free
        mkdir -p "$SAVE_DIR"
        echo "OAK operator GUI — Ctrl+C to stop.  log: $LOG"
        # No exec: the pipeline into tee needs this shell alive.
        "$PY" "$HERE/gui_server.py" \
            "${OPTS[@]+"${OPTS[@]}"}" \
            --min-dist "$MIN_DIST" --max-dist "$MAX_DIST" \
            --save-dir "$SAVE_DIR" "${@:2}" 2>&1 | tee -a "$LOG"
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
        run "$PY" "$HERE/test_detector.py" "${OPTS[@]+"${OPTS[@]}"}" "$@"
        ;;
    classes)
        check_free
        run "$PY" "$HERE/oak_wildlife.py" "${OPTS[@]+"${OPTS[@]}"}" --list-classes
        ;;
    status)
        # gui_pid was missing here, so this reported "OAK: free" while the
        # operator GUI held the device - the one place where being wrong is
        # actively misleading, because status is what you check before
        # wondering why detect refuses to start.
        t="$(tracker_pid)"; m="$(mine_pid)"; g="$(gui_pid)"
        [ -n "$t" ] && echo "OAK: owned by the flight person-tracker (pid $t)"
        [ -n "$m" ] && echo "OAK: owned by the wildlife detector (pid $m)"
        if [ -n "$g" ]; then
            if systemctl is-active --quiet venator-gui.service 2>/dev/null; then
                echo "OAK: owned by the operator GUI (pid $g, boot service venator-gui)"
            else
                echo "OAK: owned by the operator GUI (pid $g)"
            fi
        fi
        [ -z "$t$m$g" ] && echo "OAK: free"
        usb=$(for d in /sys/bus/usb/devices/*/idVendor; do
                  [ "$(cat "$d" 2>/dev/null)" = "03e7" ] || continue
                  printf '%s Mbps' "$(cat "$(dirname "$d")/speed" 2>/dev/null)"
              done)
        [ -n "$usb" ] && echo "USB link: $usb" || echo "USB link: no 03e7 device present"
        # `|| true`: read returns non-zero at EOF, which would otherwise make a
        # perfectly successful status report exit 1.
        if [ -n "${OAK_HOLD:-}" ]; then echo; read -r -p "Press Enter to close... " _ || true; fi
        ;;
    stop)
        # The unit first: killing the pid while systemd supervises it just
        # invites a restart five seconds later.
        if systemctl is-active --quiet venator-gui.service 2>/dev/null; then
            echo "The GUI is a boot service; stopping the unit (asks for sudo)..."
            sudo systemctl stop venator-gui.service \
                && { echo "GUI stopped. It returns on the next boot."; exit 0; } \
                || die "could not stop venator-gui.service"
        fi
        stopped=0
        for p in "$(gui_pid)" "$(mine_pid)"; do
            [ -n "$p" ] || continue
            kill "$p" 2>/dev/null || true
            # Give it a chance to unwind the pipeline cleanly before forcing.
            for _ in 1 2 3 4 5 6 7 8 9 10; do
                kill -0 "$p" 2>/dev/null || break
                sleep 0.3
            done
            kill -0 "$p" 2>/dev/null && kill -9 "$p" 2>/dev/null || true
            echo "stopped pid $p"
            stopped=1
        done
        [ "$stopped" = 0 ] && echo "Nothing to stop — the OAK is free."
        ;;
    restart)
        "$0" stop
        sleep 1
        exec "$0" gui "${@:2}"
        ;;
    *)
        die "unknown command '$1' (expected detect, gui, stop, restart, view, day, night, calibrate, info, test, images, classes or status)"
        ;;
esac
