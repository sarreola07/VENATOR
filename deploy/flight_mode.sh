#!/usr/bin/env bash
# Switch the C2 boot service between BENCH mode (props off — motor tests) and
# FLIGHT mode (props on — Mission 1/2/waypoints/hover), and between OUTDOOR
# (GPS gates every flight) and INDOOR (the hover alone is gated on the ARK Flow
# position, c2_server.py --indoor). Props-off is the safe default, so enabling
# flight is always a deliberate act.
#
#   ./deploy/flight_mode.sh on              # props ON  -> flight missions allowed
#   ./deploy/flight_mode.sh off             # props OFF -> motor tests allowed (default)
#   ./deploy/flight_mode.sh on indoor       # props ON, hover gated on the ARK Flow
#   ./deploy/flight_mode.sh off indoor      # props OFF, --indoor kept for the restart
#   ./deploy/flight_mode.sh indoor          # keep the props state, add --indoor
#   ./deploy/flight_mode.sh outdoor         # keep the props state, drop --indoor
#   ./deploy/flight_mode.sh status          # what mode is the service in?
#
# `on` and `off` keep the current indoor/outdoor choice unless the second word
# says otherwise: the handheld has no props toggle, so the demo goes
# `off indoor` (bench checks) -> `on indoor` (flight) -> `off indoor`, and the
# hover's gate never silently falls back to GPS between those.
#
# Everything is one drop-in, /etc/systemd/system/venator-c2.service.d/props.conf,
# which overrides the unit's ExecStart. Props ON + outdoor is the template's own
# ExecStart, so that combination deletes the drop-in rather than writing one.
#
# FLIGHT_MODE_DRY_RUN=1 prints what would be written and touches nothing (no
# sudo), which is how the tests read it.
set -euo pipefail

SVC="venator-c2.service"
DROPIN_DIR="/etc/systemd/system/${SVC}.d"
DROPIN="${DROPIN_DIR}/props.conf"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${REPO}/drone/c2_server.py"
PY="${REPO}/venv/bin/python"
DRY="${FLIGHT_MODE_DRY_RUN:-}"

# --- what is live now ---------------------------------------------------------
# Read from the drop-in itself: it is the only place the mode lives.
cur_props_off=0; cur_indoor=0
if [[ -r "${DROPIN}" ]]; then
  grep -q -- '--props-off' "${DROPIN}" && cur_props_off=1
  grep -q -- '--indoor'    "${DROPIN}" && cur_indoor=1
fi

describe() {  # $1 props_off (0/1)  $2 indoor (0/1)  -> one line, props first
  local props indoor
  if [[ "$1" == 1 ]]; then props="BENCH (props OFF) — motor tests allowed, flight blocked"
  else props="FLIGHT (props ON) — flight missions allowed"; fi
  if [[ "$2" == 1 ]]; then indoor="INDOOR — hover (menu 8) gated on the ARK Flow position"
  else indoor="OUTDOOR — every flight gated on a GPS 3D fix"; fi
  echo "Service mode: ${props}; ${indoor}"
}

place() {  # $1 indoor word or empty -> 0/1, defaulting to what is live
  case "${1:-}" in
    indoor)  echo 1 ;;
    outdoor) echo 0 ;;
    "")      echo "${cur_indoor}" ;;
    *) echo "Unknown place '${1}': use indoor or outdoor" >&2; exit 2 ;;
  esac
}

apply() {  # $1 props_off (0/1)  $2 indoor (0/1)
  local flags="--real"
  [[ "$1" == 1 ]] && flags+=" --props-off"
  [[ "$2" == 1 ]] && flags+=" --indoor"
  echo "==> $(describe "$1" "$2")"
  if [[ "$1" == 0 && "$2" == 0 ]]; then
    # The template's own ExecStart: nothing to override.
    if [[ -n "${DRY}" ]]; then echo "(dry run) would remove ${DROPIN}"; return; fi
    sudo rm -f "${DROPIN}"
    sudo rmdir "${DROPIN_DIR}" 2>/dev/null || true
  else
    local body
    body="$(printf '[Service]\nExecStart=\nExecStart=%s %s %s\n' "${PY}" "${SERVER}" "${flags}")"
    if [[ -n "${DRY}" ]]; then echo "(dry run) would write ${DROPIN}:"; echo "${body}"; return; fi
    sudo mkdir -p "${DROPIN_DIR}"
    printf '%s\n' "${body}" | sudo tee "${DROPIN}" >/dev/null
  fi
  sudo systemctl daemon-reload
  sudo systemctl restart "${SVC}"
  sleep 3
  journalctl -u "${SVC}" -n 4 --no-pager | sed 's/.*python\[[0-9]*\]: //'
  if [[ "$1" == 1 ]]; then echo "BENCH mode active — remove the props before motor tests."
  else echo "FLIGHT mode active — PROPS MUST BE ON."; fi
  [[ "$2" == 1 ]] && echo "INDOOR: the hover needs the ARK Flow position (menu 9 checks it), not GPS."
  return 0
}

case "${1:-status}" in
  on|off)
    # Validate the place word here, not inside $(...): an exit in a command
    # substitution ends only that subshell, and the mode would still change.
    case "${2:-}" in indoor|outdoor|"") ;; *)
      echo "Unknown place '${2}': use indoor or outdoor" >&2; exit 2 ;; esac
    [[ "$1" == on ]] && apply 0 "$(place "${2:-}")" || apply 1 "$(place "${2:-}")" ;;
  indoor)  apply "${cur_props_off}" 1 ;;
  outdoor) apply "${cur_props_off}" 0 ;;
  status)
    # First line is what deploy/symposium_check.sh reads: it looks for
    # "props OFF" / "BENCH" in it, so props stay first.
    describe "${cur_props_off}" "${cur_indoor}"
    systemctl is-active "${SVC}"
    ;;
  *)
    echo "Usage: $0 [on|off [indoor|outdoor] | indoor | outdoor | status]"; exit 2;;
esac
