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
# NO RADIO IS INVOLVED. The browser reaches the Jetson over Wi-Fi and the
# Jetson reaches the Pixhawk over USB. The LoRa stick and the SiK radio are
# both free; the radio only matters when the browser is somewhere the drone
# is not.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
PLANNER="${PLANNER:-${HOME}/Desktop/drone-mission-planner-css}"
PY="${REPO}/venv/bin/python"
WEB_PORT="${WEB_PORT:-5037}"
BRIDGE_PORT="${BRIDGE_PORT:-5555}"

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

# ---- where to open it -----------------------------------------------------
echo
printf "  ${B}OPEN THE DASHBOARD${Z}\n"
printf "    on this Jetson : ${G}http://127.0.0.1:%s/${Z}\n" "${WEB_PORT}"
while read -r _ dev _ cidr _; do
    ip="${cidr%%/*}"
    [[ "$dev" == "lo" || -z "$ip" ]] && continue
    printf "    from a phone   : ${G}http://%s:%s/${Z}  (%s)\n" "$ip" "${WEB_PORT}" "$dev"
done < <(ip -4 -o addr show 2>/dev/null)
echo
say "In the page: pick the Pixhawk port, 115200 baud, Connect."
say "Props OFF. The planner panel needs the C# service and stays unavailable."
echo
printf "  ${Y}Ctrl-C here stops both and restarts venator-c2.${Z}\n\n"

wait
