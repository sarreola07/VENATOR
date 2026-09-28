#!/usr/bin/env bash
# Launcher wrapper for the IMX219 CAM0 live feed on Jetson Orin Nano.
# Called by wildlife-camera.desktop, but fine to run directly:
#
#   ./imx219_camera.sh            # live 720p window, auto day/night (~46 fps at 7W)
#   ./imx219_camera.sh 1080p      # live 1080p window (~25 fps at 7W)
#   ./imx219_camera.sh day        # force colour
#   ./imx219_camera.sh night      # force black and white
#   ./imx219_camera.sh snapshot   # full-res 3280x2464 still into ~/Pictures
#
# Environment overrides:
#   DAYNIGHT=schedule|auto|day|night   default schedule (sunrise/sunset)
#   FLIP=0..7                 nvvidconv flip-method, default 2 = rotate 180
#
# Argus will not share the sensor between two consumers, so this refuses to
# start a second capture and offers to take over instead. Set
# IMX219_NONINTERACTIVE=1 to make that refusal silent and non-blocking.

set -uo pipefail

FEED="$(dirname "$(readlink -f "$0")")/imx219_feed.py"
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/imx219-live.log"
mkdir -p "$(dirname "$LOG")"

# When launched from a .desktop, DISPLAY is normally already set. Fall back
# to the seat0 session's display if it is missing (e.g. run over SSH).
export DISPLAY="${DISPLAY:-:1}"
# gdm keeps the X cookie under the runtime dir rather than ~/.Xauthority, so a
# bare environment (ssh, cron, detached shell) has no way to reach the server.
if [ -z "${XAUTHORITY:-}" ] && [ -r "/run/user/$(id -u)/gdm/Xauthority" ]; then
  export XAUTHORITY="/run/user/$(id -u)/gdm/Xauthority"
fi

log() { echo "$(date -Is) $*" >>"$LOG"; }

die() {
  log "ERROR: $*"
  # Surface the failure even though the .desktop sets Terminal=false.
  if [ -n "${IMX219_NONINTERACTIVE:-}" ]; then
    echo "ERROR: $*" >&2
  elif command -v zenity >/dev/null 2>&1; then
    zenity --error --no-wrap --title="IMX219 Camera" \
           --text="$*\n\nLog: $LOG" 2>/dev/null
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send -u critical "IMX219 Camera" "$*"
  else
    echo "ERROR: $*" >&2
  fi
  exit 1
}

# PID of an existing live-feed window, if any.
running_pid() { pgrep -f 'imx219_feed\.py --display' | head -1; }

# Ask to stop an existing feed. Returns 0 if the camera is now free.
take_over() {
  local pid=$1 why=$2
  if [ -n "${IMX219_NONINTERACTIVE:-}" ]; then
    echo "live feed already running (pid $pid); refusing to $why" >&2
    log "refused: feed already running (pid $pid)"
    return 1
  fi
  if command -v zenity >/dev/null 2>&1; then
    zenity --question --no-wrap --title="IMX219 Camera" \
      --text="The live feed is already running (pid $pid).\nThe camera cannot be shared between two captures.\n\nStop it and $why?" \
      2>/dev/null || { log "user declined takeover"; exit 0; }
  fi
  log "stopping existing feed pid $pid"
  # imx219_feed.py traps SIGTERM and unwinds the pipeline to NULL, which is
  # what gives Argus a clean stream-off. Allow a generous grace period: a
  # SIGKILL here can leave the IMX219 mid-frame, and recovering from that
  # needs an nvargus-daemon restart (and sometimes a power cycle).
  kill -TERM "$pid" 2>/dev/null
  for _ in $(seq 48); do              # up to 12s
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    log "WARNING: pid $pid ignored SIGTERM after 12s; sending SIGKILL." \
        "The sensor may be left mid-frame - if capture then fails, run:" \
        "sudo systemctl restart nvargus-daemon"
    kill -9 "$pid" 2>/dev/null
    sleep 2
  fi
  sleep 1          # let nvargus-daemon release the sensor
  return 0
}

[ -x "$FEED" ] || die "feed script not found or not executable:\n$FEED"
[ -e /dev/video0 ] || die "/dev/video0 is missing.\nThe camera overlay may not be applied, or the ribbon is unseated.\nRun the health check to diagnose."

mode="${1:-720p}"
existing=$(running_pid)

# Day/night and rotation. Defaults come from the feed itself (auto, rotate-180);
# override per-invocation, e.g.  DAYNIGHT=night ./imx219_camera.sh 720p
DAYNIGHT="${DAYNIGHT:-schedule}"
FLIP="${FLIP:-2}"
opts=(--daynight "$DAYNIGHT" --flip "$FLIP")

case "$mode" in
  720p|1080p|"")
    [ "$mode" = "" ] && mode=720p
    if [ -n "$existing" ]; then
      take_over "$existing" "restart the feed at $mode" || exit 1
    fi
    sensor_mode=4; [ "$mode" = "1080p" ] && sensor_mode=2
    log "starting: $mode (sensor-mode=$sensor_mode, daynight=$DAYNIGHT, flip=$FLIP, DISPLAY=$DISPLAY)"
    exec "$FEED" --display --mode "$sensor_mode" "${opts[@]}" >>"$LOG" 2>&1
    ;;
  day|night)
    # Force a colour or black-and-white feed rather than metering the light.
    if [ -n "$existing" ]; then
      take_over "$existing" "restart the feed in $mode mode" || exit 1
    fi
    log "starting: 720p forced $mode mode (flip=$FLIP, DISPLAY=$DISPLAY)"
    exec "$FEED" --display --mode 4 --daynight "$mode" --flip "$FLIP" >>"$LOG" 2>&1
    ;;
  snapshot)
    if [ -n "$existing" ]; then
      take_over "$existing" "take the snapshot" || exit 1
    fi
    out="$HOME/Pictures/imx219-$(date +%Y%m%d-%H%M%S).jpg"
    mkdir -p "$HOME/Pictures"
    log "snapshot -> $out"
    if "$FEED" --mode 0 --out 3280x2464 --snapshot "$out" "${opts[@]}" >>"$LOG" 2>&1; then
      echo "saved $out"
      command -v notify-send >/dev/null 2>&1 && \
        notify-send -i camera-photo "IMX219 Camera" "Saved $(basename "$out")"
      [ -z "${IMX219_NONINTERACTIVE:-}" ] && command -v xdg-open >/dev/null 2>&1 && \
        xdg-open "$out" >/dev/null 2>&1 &
      exit 0
    else
      die "snapshot failed — see log"
    fi
    ;;
  *)
    die "unknown mode '$mode' (expected 720p, 1080p, day, night or snapshot)"
    ;;
esac
