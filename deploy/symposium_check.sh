#!/usr/bin/env bash
# Pre-demo check — the one you run before you speak.
#
# Read-only and no sudo: it reports, it never changes anything. One line per
# check, short enough to read from across a room, and it exits non-zero if
# something that matters is wrong so the terminal window tells you at a glance.
#
#   bash deploy/symposium_check.sh
#
# WHAT COUNTS AS A FAILURE, AND WHAT DOES NOT
#
# The GPS is a known hardware fault (fix_type 0 = no GPS connected, an M10 cable
# or port problem). It blocks outdoor flight and nothing that gets demonstrated,
# so it prints as INFO rather than turning the whole check red. A check that
# cries wolf about a thing you already know and cannot fix today is a check you
# stop reading.
#
# NRestarts is printed for every service on purpose. A climbing restart counter
# is the only outward sign of the crash-loop failures this project hit twice in
# one week -- the unit otherwise looks perfectly healthy in `systemctl status`.
set -uo pipefail          # NOT -e: a failed check must print, not abort the run

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"

EVIDENCE_DIR="${EVIDENCE_DIR:-${HOME}/Pictures/wildlife}"
FRESH_S="${FRESH_S:-45}"          # evidence newer than this means the camera is live
UNITS=(venator-gui venator-net-fallback venator-c2)

G=$'\033[92m'; R=$'\033[91m'; Y=$'\033[93m'; B=$'\033[94m'; Z=$'\033[0m'
bad=0
ok()   { printf "  ${G}[ OK ]${Z} %s\n" "$*"; }
fail() { printf "  ${R}[FAIL]${Z} %s\n" "$*"; bad=1; }
warn() { printf "  ${Y}[WARN]${Z} %s\n" "$*"; }
info() { printf "  ${B}[INFO]${Z} %s\n" "$*"; }
head_() { printf "\n${B}== %s ==${Z}\n" "$*"; }

printf "\n${B}VENATOR — pre-demo check${Z}   %s\n" "$(date '+%F %H:%M:%S')"

# ---------------------------------------------------------------- services
head_ "Boot services"
for u in "${UNITS[@]}"; do
    # `is-enabled`/`is-active` exit non-zero for a perfectly valid answer like
    # "disabled" or "inactive", so a `|| echo unknown` fallback appends a second
    # line to the real one. Take the output and only substitute when it is empty.
    en="$(systemctl is-enabled "$u" 2>/dev/null)"; en="${en:-unknown}"
    ac="$(systemctl is-active  "$u" 2>/dev/null)"; ac="${ac:-unknown}"
    nr="$(systemctl show "$u" -p NRestarts --value 2>/dev/null || echo '?')"
    line="$(printf '%-22s %-9s %-9s restarts=%s' "$u" "$en" "$ac" "$nr")"
    if [[ "$ac" != "active" ]]; then
        fail "${line}   <- not running"
    elif [[ "$en" != "enabled" ]]; then
        fail "${line}   <- will NOT start on the next boot"
    elif [[ "$nr" =~ ^[0-9]+$ ]] && (( nr > 0 )); then
        # Not fatal on its own -- it is running now -- but it means something
        # died and was restarted, which is worth knowing before an audience.
        warn "${line}   <- it has restarted; check journalctl -u ${u} -b"
    else
        ok "${line}"
    fi
done

# ---------------------------------------------------------------- props
head_ "Props interlock"
fm="$(bash "${HERE}/flight_mode.sh" status 2>/dev/null | head -1)"
if [[ "$fm" == *"props OFF"* || "$fm" == *BENCH* ]]; then
    ok "${fm}"
else
    # The handheld remote has no props toggle (its menu is 1, 2, 8, 7), so if
    # the server boots props ON the operator cannot recover from the radio.
    fail "${fm:-flight_mode.sh gave no answer}"
    fail "      motor tests will be REFUSED. Fix: bash deploy/flight_mode.sh off"
fi

# ---------------------------------------------------------------- camera
head_ "Camera"
newest="$(ls -t "${EVIDENCE_DIR}"/*.jpg 2>/dev/null | head -1)"
if [[ -z "${newest}" ]]; then
    fail "no evidence frames in ${EVIDENCE_DIR}"
else
    age=$(( $(date +%s) - $(stat -c %Y "${newest}") ))
    # Evidence freshness rather than /api/status: it needs no token, and a frame
    # on disk is proof the whole chain ran -- device, pipeline, detector, writer.
    if (( age <= FRESH_S )); then
        ok "capturing — newest frame ${age}s old ($(basename "${newest}"))"
    else
        warn "newest frame is ${age}s old ($(basename "${newest}"))"
        warn "      the detector only writes on a detection, so this is normal"
        warn "      in an empty room. Walk in front of it and re-run."
    fi
    info "$(ls -1 "${EVIDENCE_DIR}"/*.jpg 2>/dev/null | wc -l) frames saved in total"
fi
if curl -sf --max-time 5 http://127.0.0.1:8080/healthz >/dev/null 2>&1; then
    ok "GUI answering on :8080"
else
    fail "GUI not answering on http://127.0.0.1:8080/healthz"
fi

# ---------------------------------------------------------------- radios + FC
head_ "Radios and flight controller"
lora="$(ls /dev/serial/by-id/ 2>/dev/null | grep -i 'CP2102\|Silicon_Labs' | head -1)"
[[ -n "$lora" ]] && ok "LoRa stick  ${lora}" || fail "LoRa stick NOT present"

fc="$(ls /dev/serial/by-id/ 2>/dev/null | grep -i 'PX4\|FMU' | head -1)"
if [[ -z "$fc" ]]; then
    fail "Pixhawk NOT present"
elif [[ "$fc" == *_BL_* ]]; then
    # A board in the bootloader enumerates and takes the same by-id glob, so it
    # looks connected while answering no MAVLink at all.
    fail "Pixhawk is in its BOOTLOADER (${fc})"
    fail "      power-cycle it; if 'BL' persists, reflash PX4 in QGroundControl"
else
    ok "Pixhawk     ${fc}"
fi

# Only worth probing when the C2 service is not already holding the port.
if [[ "$fc" == *_BL_* || -z "$fc" ]]; then
    :
elif systemctl is-active --quiet venator-c2 2>/dev/null; then
    info "heartbeat not probed — venator-c2 owns the port (that is correct)"
elif [[ -x "${REPO}/venv/bin/python" ]]; then
    "${REPO}/venv/bin/python" - <<'PY' 2>/dev/null || warn "heartbeat probe failed to run"
import sys
sys.path.insert(0, "/home/jetson/Desktop/VENATOR")
sys.path.insert(0, "/home/jetson/Desktop/VENATOR/drone")
from pymavlink import mavutil
from c2_server import find_fc_device          # reuse: survives a ttyACM0->1 replug
G, R, B = "\033[92m", "\033[91m", "\033[94m"; Z = "\033[0m"
m = mavutil.mavlink_connection(find_fc_device(), baud=115200)
m.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS,
                     mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
if m.wait_heartbeat(timeout=12) is None:
    print(f"  {R}[FAIL]{Z} no MAVLink heartbeat")
    raise SystemExit(1)
print(f"  {G}[ OK ]{Z} MAVLink heartbeat (system {m.target_system})")
s = m.recv_match(type="SYS_STATUS", blocking=True, timeout=6)
if s and s.voltage_battery != 65535:
    v = s.voltage_battery / 1000.0
    print(f"  {G}[ OK ]{Z} battery {v:.2f} V  ({v/4:.2f} V/cell on 4S)")
elif s:
    print(f"  {R}[FAIL]{Z} no battery sensed — motor tests will spin nothing")
g = m.recv_match(type="GPS_RAW_INT", blocking=True, timeout=6)
if g:
    # Informational by design: fix_type 0 is a known M10 cable/port fault. It
    # blocks outdoor flight and nothing being demonstrated, so it must not turn
    # this check red.
    names = {0: "no GPS connected", 1: "no fix", 2: "2D", 3: "3D fix"}
    print(f"  {B}[INFO]{Z} GPS fix_type={g.fix_type} "
          f"({names.get(g.fix_type, '?')}), {g.satellites_visible} sats "
          f"— blocks outdoor flight only")
PY
    [[ ${PIPESTATUS[0]:-0} -ne 0 ]] && bad=1
fi

# ---------------------------------------------------------------- network
head_ "Network and the phone URL"
bash "${HERE}/field_mode.sh" status 2>/dev/null | sed 's/^/  /'

# ---------------------------------------------------------------- verdict
echo
if (( bad )); then
    printf "  ${R}SOMETHING NEEDS FIXING — read the FAIL lines above.${Z}\n\n"
    exit 1
fi
printf "  ${G}ALL CLEAR.${Z}  Props are OFF, services are up, the camera is serving.\n"
printf "  Demo order:  RUN 7 (status) -> RUN 1 (each motor) -> RUN 2 (all) -> RUN 8 (refuses).\n\n"
