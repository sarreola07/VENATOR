#!/usr/bin/env bash
# Start the mission dashboard: the MAVLink bridge plus the page that drives it.
#
#   bash deploy/symposium_dashboard.sh
#
# TWO PROCESSES, ONE PIXHAWK
#
# python_bridge/drone_bridge.py opens the Pixhawk's serial port when you pick a
# port in the page. venator-c2.service holds that same port whenever it is
# running, and a serial port has exactly one owner -- so this stops the C2
# service first and puts it back on exit. That trade is deliberate and worth
# stating out loud: while the dashboard is up, the handheld LoRa remote is not
# being listened to. They are two ways of commanding the same aircraft, and
# only one can hold the Pixhawk.
#
# THE ACCESS POINT IS THE NETWORK
#
# The drone hosts VenatorDrone on 10.42.0.1 and the phone joins it. There is no
# router, no venue Wi-Fi and no internet in the deployed system -- that is the
# whole point of the aircraft. A client-network address works on a bench and is
# printed as such, but it is not the product and must not be what gets
# demonstrated.
#
# NO RADIO IS INVOLVED in the command path. The phone reaches the Jetson over
# the Jetson's own access point, and the Jetson reaches the Pixhawk over USB.
# The LoRa stick and the SiK radio are both free; a radio only matters when the
# browser is somewhere the drone is not.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
PLANNER="${PLANNER:-${HOME}/Desktop/drone-mission-planner-css}"
PY="${REPO}/venv/bin/python"
WEB_PORT="${WEB_PORT:-5037}"
BRIDGE_PORT="${BRIDGE_PORT:-5555}"
AP_IP="${AP_IP:-10.42.0.1}"      # the VenatorDrone access point; the deployment address

G=$'\033[92m'; R=$'\033[91m'; Y=$'\033[93m'; B=$'\033[94m'; Z=$'\033[0m'
say()  { printf "  %s\n" "$*"; }
ok()   { printf "  ${G}[ OK ]${Z} %s\n" "$*"; }
bad()  { printf "  ${R}[FAIL]${Z} %s\n" "$*"; }
warn() { printf "  ${Y}[WARN]${Z} %s\n" "$*"; }

printf "\n${B}VENATOR — mission dashboard${Z}\n\n"

# ---- preconditions --------------------------------------------------------
[[ -f "${PLANNER}/python_bridge/drone_bridge.py" ]] || {
    bad "mission planner not found at ${PLANNER}"
    say "  git clone -b venator-gui-iteration-3 \\"
    say "    https://github.com/XSilverEyeX/drone-mission-planner-css.git \\"
    say "    ${PLANNER}"
    exit 1; }
[[ -x "${PY}" ]] || { bad "no venv at ${PY} — run: bash setup.sh"; exit 1; }

fc="$(ls /dev/serial/by-id/ 2>/dev/null | grep -i 'PX4\|FMU' | head -1)"
if [[ -z "$fc" ]]; then
    bad "no Pixhawk on the bus — plug it in, then re-run"
    say "      the page will load, but there is nothing to command"
elif [[ "$fc" == *_BL_* ]]; then
    # A board in the bootloader enumerates and answers no MAVLink at all.
    bad "Pixhawk is in its BOOTLOADER (${fc})"
    say "      power-cycle it; if 'BL' persists, reflash PX4 in QGroundControl"
else
    ok "Pixhawk  ${fc}"
fi

# ---- already running? -----------------------------------------------------
# This has to come BEFORE anything is stopped or started. Clicking the icon
# twice used to end in "OSError: [Errno 98] Address already in use" from the
# bridge -- and confusingly it prints "Listening on ..." BEFORE it binds, so
# the traceback reads as if it died after starting. Worse, by then this script
# had already stopped venator-c2 on behalf of a run that then failed, leaving
# the handheld remote dead for no reason.
port_held() { ss -lnt 2>/dev/null | grep -q "127.0.0.1:${1} \|0.0.0.0:${1} "; }

if port_held "${BRIDGE_PORT}" && port_held "${WEB_PORT}"; then
    echo
    ok "already running — bridge on ${BRIDGE_PORT}, page on ${WEB_PORT}"
    say "Another terminal owns it. Open the URLs below, or close that terminal"
    say "first if you want a clean restart."
    echo
    if ip -4 -o addr show 2>/dev/null | grep -q "${AP_IP}/"; then
        printf "    ${G}http://%s:%s/${Z}   <- join the VenatorDrone Wi-Fi\n" "${AP_IP}" "${WEB_PORT}"
    else
        printf "    ${Y}http://%s:%s/${Z}   <- the real address, but the AP is DOWN\n" "${AP_IP}" "${WEB_PORT}"
    fi
    printf "    http://127.0.0.1:%s/   (on this Jetson)\n" "${WEB_PORT}"
    echo
    exit 0
fi
if port_held "${BRIDGE_PORT}" || port_held "${WEB_PORT}"; then
    warn "a previous run left one half up; clearing it so this one starts clean"
    pkill -f "python_bridge/drone_bridge.py" 2>/dev/null
    pkill -f "deploy/venator_web.py"        2>/dev/null
    sleep 2
fi
ADOPTED=0

# ---- free the serial port -------------------------------------------------
if systemctl is-active --quiet venator-c2 2>/dev/null; then
    warn "venator-c2 owns the Pixhawk; stopping it so the bridge can connect"
    warn "the handheld LoRa remote will NOT work until this script exits"
    sudo systemctl stop venator-c2 || { bad "could not stop venator-c2"; exit 1; }
    STOPPED_C2=1
    ok "venator-c2 stopped"
else
    STOPPED_C2=0
fi

cleanup() {
    echo
    say "shutting down..."
    [[ -n "${BRIDGE_PID:-}" ]] && kill "${BRIDGE_PID}" 2>/dev/null
    [[ -n "${WEB_PID:-}"    ]] && kill "${WEB_PID}"    2>/dev/null
    if (( STOPPED_C2 )); then
        sudo systemctl start venator-c2 2>/dev/null \
            && ok "venator-c2 restarted — the handheld remote works again" \
            || warn "could not restart venator-c2: sudo systemctl start venator-c2"
    fi
}
trap cleanup EXIT INT TERM

# ---- start both -----------------------------------------------------------
if (( ! ADOPTED )); then
    cd "${PLANNER}"
    "${PY}" python_bridge/drone_bridge.py &
    BRIDGE_PID=$!
    sleep 3
    kill -0 "${BRIDGE_PID}" 2>/dev/null && ok "bridge up on 127.0.0.1:${BRIDGE_PORT} (pid ${BRIDGE_PID})" \
        || { bad "bridge exited immediately"; exit 1; }

    "${PY}" "${HERE}/venator_web.py" --port "${WEB_PORT}" --bridge-port "${BRIDGE_PORT}" &
    WEB_PID=$!
    sleep 2
    kill -0 "${WEB_PID}" 2>/dev/null && ok "page up (pid ${WEB_PID})" \
        || { bad "web server exited immediately"; exit 1; }
fi

# ---- where to open it -----------------------------------------------------
# The access point is THE address, not one option among several. This aircraft
# is built to work with no internet, no cellular and no ground-control
# software; a URL that only resolves on somebody's venue Wi-Fi is not the
# product. Client-network addresses are printed afterwards and labelled as
# bench-only, so they are never mistaken for the real one.
echo
printf "  ${B}OPEN THE DASHBOARD${Z}\n"
if ip -4 -o addr show 2>/dev/null | grep -q "${AP_IP}/"; then
    printf "    ${G}http://%s:%s/${Z}   <- join the VenatorDrone Wi-Fi\n" "${AP_IP}" "${WEB_PORT}"
else
    printf "    ${Y}http://%s:%s/${Z}   <- the real address, but the AP is DOWN\n" "${AP_IP}" "${WEB_PORT}"
    printf "    ${Y}bring it up:  %s/deploy/wifi_mode.sh on${Z}\n" "${REPO}"
fi
printf "    http://127.0.0.1:%s/   (on this Jetson)\n" "${WEB_PORT}"
other=""
while read -r _ dev _ cidr _; do
    ip4="${cidr%%/*}"
    [[ "$dev" == "lo" || -z "$ip4" || "$ip4" == "${AP_IP}" ]] && continue
    other+="    http://${ip4}:${WEB_PORT}/   (${dev})"$'\n'
done < <(ip -4 -o addr show 2>/dev/null)
[[ -n "$other" ]] && { printf "  bench only, not the deployment path:\n"; printf "%s" "$other"; }
echo
say "In the page: pick the Pixhawk port, 115200 baud, Connect."
say "Props OFF. The planner panel needs the C# service and stays unavailable."
echo
printf "  ${Y}Ctrl-C here stops both and restarts venator-c2.${Z}\n\n"

wait
