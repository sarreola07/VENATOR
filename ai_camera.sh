#!/usr/bin/env bash
# AI camera tracking — on-demand toggle.
#
# Starts / stops the OAK-D person tracker (camera_publisher.py) as a background
# USER process. It is fully decoupled from the drone's MAVLink link and from any
# systemd service: it only reads the USB camera and publishes person coordinates
# on UDP 127.0.0.1:5005. Starting or stopping it NEVER opens /dev/ttyACM0, so it
# cannot restart the drone or interrupt background telemetry.
#
# Usage:
#   ./ai_camera.sh            # toggle: start if stopped, stop if running
#   ./ai_camera.sh start|stop|restart|status
#   ./ai_camera.sh stream     # start with the web stream: watch the video in a
#                             # laptop browser (Windows/Mac) at http://<jetson-ip>:8080
set -uo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CAMERA_PY="${CAMERA_PY:-/home/jetson/oak_drone_project/depthai-env/bin/python}"
SCRIPT="${REPO}/camera_publisher.py"

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/ai-camera"
PIDFILE="${STATE_DIR}/camera.pid"
LOGFILE="${STATE_DIR}/camera.log"
STREAM_PORT="${CAMERA_STREAM_PORT:-8080}"
mkdir -p "${STATE_DIR}"

notify() {
    # Desktop popup when launched from the GNOME session; always print too.
    if command -v notify-send >/dev/null 2>&1; then
        notify-send -a "AI Camera" -i "${REPO}/assets/ai-camera.png" "AI Camera" "$1" 2>/dev/null || true
    fi
    echo "AI Camera: $1"
}

# Echo the live camera_publisher PID, or nothing.
running_pid() {
    local pid=""
    if [[ -f "${PIDFILE}" ]]; then
        pid="$(cat "${PIDFILE}" 2>/dev/null || true)"
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null \
           && grep -qa "camera_publisher.py" "/proc/${pid}/cmdline" 2>/dev/null; then
            echo "${pid}"
            return 0
        fi
    fi
    # Fallback: a camera started outside this pidfile. Match the exact script
    # path (won't appear in incidental command lines) and exclude ourselves.
    pgrep -f "${SCRIPT}" 2>/dev/null | grep -vx "$$" | head -n1
}

# True when the running camera (PID $1) was started with the web stream.
is_streaming() {
    tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null | grep -q -- "--stream"
}

# Print the web stream address on each of the Jetson's networks.
stream_urls() {
    local ip a b label
    for ip in $(hostname -I 2>/dev/null); do
        [[ "${ip}" == *:* ]] && continue            # skip IPv6
        IFS=. read -r a b _ _ <<< "${ip}"
        label=""
        if [[ "${ip}" == "10.42.0.1" ]]; then
            label="  (Jetson Wi-Fi hotspot)"
        elif [[ "${ip}" == "192.168.55.1" ]]; then
            label="  (USB-C cable)"
        elif (( a == 100 && b >= 64 && b <= 127 )); then
            label="  (Tailscale)"
        fi
        echo "  http://${ip}:${STREAM_PORT}${label}"
    done
}

# start [--stream]
start() {
    local mode="${1:-}"
    local pid; pid="$(running_pid)"
    if [[ -n "${pid}" ]]; then
        if [[ "${mode}" == "--stream" ]] && ! is_streaming "${pid}"; then
            echo "Restarting the camera with the web stream on..."
            stop >/dev/null
        else
            notify "already running (PID ${pid})."
            is_streaming "${pid}" && stream_urls
            return 0
        fi
    fi
    if [[ ! -x "${CAMERA_PY}" ]]; then
        notify "DepthAI python not found at ${CAMERA_PY}."
        return 1
    fi
    echo "=== $(date) starting camera_publisher ${mode} ===" >> "${LOGFILE}"
    local logstart; logstart=$(( $(wc -l < "${LOGFILE}") + 1 ))
    nohup "${CAMERA_PY}" "${SCRIPT}" ${mode:+"${mode}"} >> "${LOGFILE}" 2>&1 &
    local newpid=$!
    echo "${newpid}" > "${PIDFILE}"
    sleep 2
    if kill -0 "${newpid}" 2>/dev/null; then
        if [[ "${mode}" != "--stream" ]]; then
            notify "started (PID ${newpid}) — tracking on UDP 5005."
        elif tail -n +"${logstart}" "${LOGFILE}" | grep -q "Web stream disabled"; then
            notify "started (PID ${newpid}), but the web stream could not open port ${STREAM_PORT} — see ${LOGFILE}"
        else
            notify "started with web stream (PID ${newpid}). Open in a laptop browser:"$'\n'"$(stream_urls)"
        fi
    else
        notify "failed to start — see ${LOGFILE}"
        tail -n 5 "${LOGFILE}" 2>/dev/null || true
        rm -f "${PIDFILE}"
        return 1
    fi
}

stop() {
    local pid; pid="$(running_pid)"
    if [[ -z "${pid}" ]]; then
        notify "not running."
        rm -f "${PIDFILE}"
        return 0
    fi
    kill "${pid}" 2>/dev/null || true
    for _ in $(seq 1 10); do
        kill -0 "${pid}" 2>/dev/null || break
        sleep 0.3
    done
    kill -0 "${pid}" 2>/dev/null && kill -9 "${pid}" 2>/dev/null || true
    rm -f "${PIDFILE}"
    notify "stopped (was PID ${pid})."
}

restart() {
    local pid mode=""; pid="$(running_pid)"
    [[ -n "${pid}" ]] && is_streaming "${pid}" && mode="--stream"
    stop; sleep 1; start "${mode}"
}

status() {
    local pid; pid="$(running_pid)"
    if [[ -n "${pid}" ]] && is_streaming "${pid}"; then
        echo "AI camera: RUNNING (PID ${pid}) with web stream on port ${STREAM_PORT}"
        stream_urls
    elif [[ -n "${pid}" ]]; then
        echo "AI camera: RUNNING (PID ${pid})"
    else
        echo "AI camera: stopped"
    fi
}

# Foreground preview window. The OAK-D allows only one owner, so stop any
# headless instance first, then run the windowed publisher until it's closed.
preview() {
    if [[ ! -x "${CAMERA_PY}" ]]; then
        notify "DepthAI python not found at ${CAMERA_PY}."
        return 1
    fi
    if [[ -n "$(running_pid)" ]]; then
        echo "Stopping the headless camera so the preview can open the OAK-D..."
        stop >/dev/null 2>&1 || true
    fi
    echo "Opening preview window — press q in the window (or Ctrl-C) to close."
    exec "${CAMERA_PY}" "${SCRIPT}" --preview
}

case "${1:-toggle}" in
    start)   start ;;
    stream)  start --stream ;;
    stop)    stop ;;
    restart) restart ;;
    status)  status ;;
    preview) preview ;;
    toggle)  if [[ -n "$(running_pid)" ]]; then stop; else start; fi ;;
    *) echo "Usage: $0 [start|stream|stop|restart|status|toggle|preview]"; exit 2 ;;
esac
