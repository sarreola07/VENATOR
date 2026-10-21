#!/usr/bin/env bash
# Field mode: the drone hosts its own Wi-Fi and serves the camera, with nobody
# at the keyboard.
#
#   ./deploy/field_mode.sh              # status
#   ./deploy/field_mode.sh on           # access point + camera GUI, now
#   ./deploy/field_mode.sh off          # stop the GUI, rejoin the previous Wi-Fi
#   ./deploy/field_mode.sh toggle       # what the Desktop icon calls
#   ./deploy/field_mode.sh url          # the address to open on a phone
#   ./deploy/field_mode.sh install      # install + enable the boot units
#   ./deploy/field_mode.sh install --dry-run
#   ./deploy/field_mode.sh uninstall
#
# WHAT "AT BOOT" MEANS HERE
# Two units are installed. venator-net-fallback waits up to 45 s for
# NetworkManager to join a Wi-Fi network it already knows; if none appears - a
# field - it brings up the VenatorDrone access point instead. venator-gui runs
# the camera server either way, so the feed is there whether the drone is
# hosting or joined to the lab.
#
# A phone that joins VenatorDrone is sent to the camera automatically, by the
# captive-portal machinery in deploy/dnsmasq/venator-portal.conf and the routes
# in drone/wildlife/gui_server.py. See docs/FIELD_MODE.md.
#
# WHY EVERYTHING GOES THROUGH systemd
# `on` starts the same units the boot path starts, so running it by hand and
# booting are one code path with one place to look when it misbehaves:
#   journalctl -u venator-gui -u venator-net-fallback
# The alternative - a pidfile and nohup, as drone/camera.sh does - would mean
# two mechanisms that can disagree, and a stale pidfile next to a live unit is
# a worse failure than no pidfile at all.
set -uo pipefail

SELF="$(readlink -f "$0")"
HERE="$(cd "$(dirname "${SELF}")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"

CON="venator-hotspot"
HOTSPOT_IP="10.42.0.1"
PORTAL_HOST="venatordrone.com"
OAK_PY="${OAK_PY:-/home/jetson/oak-venv/bin/python}"

GUI_UNIT="venator-gui.service"
NET_UNIT="venator-net-fallback.service"

DNSMASQ_DST="/etc/NetworkManager/dnsmasq-shared.d/venator-portal.conf"
NFT_DST="/etc/venator/portal.nft"
DISPATCH_DST="/etc/NetworkManager/dispatcher.d/90-venator-portal"

STATE_DIR="${XDG_STATE_HOME:-${HOME:-/root}/.local/state}/venator"
LOG="${STATE_DIR}/field_mode.log"

DRY=0
ARGS=()
for arg in "$@"; do
    case "${arg}" in
        --dry-run) DRY=1 ;;
        --pause)   trap 'echo; read -r -n1 -p "Press any key to close..."' EXIT ;;
        *)         ARGS+=("${arg}") ;;
    esac
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

say() {
    echo "$*"
    { mkdir -p "${STATE_DIR}" && echo "$(date '+%F %T') field_mode: $*" >> "${LOG}"; } 2>/dev/null || true
}
die() { say "$*"; exit 1; }
run() { if (( DRY )); then echo "  [dry-run] $*"; else "$@"; fi; }

# --- the token ---------------------------------------------------------------
# Derived from radio/auth.py's key by gui_server.make_token(). Asked of Python
# rather than recomputed in bash: one definition of the HMAC, in one place.
token() {
    # $REPO rather than a literal path: deploy/README.md's whole contract is
    # that the installers are re-run after the repo moves, and a hardcoded
    # path here would survive that and then silently report no token.
    REPO="${REPO}" "${OAK_PY}" - <<'PY' 2>/dev/null
import os, sys
repo = os.environ["REPO"]
sys.path.insert(0, repo)
sys.path.insert(0, os.path.join(repo, "drone", "wildlife"))
from radio import auth
import gui_server
print(gui_server.make_token(auth.load_key()) or "")
PY
}

# Called by venator-gui.service's ExecStartPre. Without a key file the server
# binds loopback only and the phone cannot see it, which looks like a working
# system from the Jetson and a dead one from the field.
require_key() {
    if [[ -n "$(token)" ]]; then
        return 0
    fi
    say "no C2 key file yet — creating one so the GUI can be reached"
    "${OAK_PY}" "${REPO}/radio/auth.py" --init >/dev/null 2>&1 \
        || python3 "${REPO}/radio/auth.py" --init >/dev/null 2>&1 \
        || die "could not create a key (tried ${OAK_PY} and python3)"
    say "GUI token is now $(token)"
}

url() {
    local t; t="$(token)"
    if [[ -n "${t}" ]]; then
        echo "http://${PORTAL_HOST}/?k=${t}"
    else
        echo "http://${PORTAL_HOST}/   (no key yet — run: ${SELF} _require_key)"
    fi
}

# --- preflight ---------------------------------------------------------------
# Each failure names its own fix. The port check matters most: gui_server.py
# cannot bind a taken port, main() returns non-zero, and Restart=always with
# StartLimitIntervalSec=0 would then retry every 5 s forever.
preflight() {
    local bad=0
    if ss -lnt 2>/dev/null | grep -q ':8080 '; then
        local who; who="$(ss -lntp 2>/dev/null | awk '/:8080 /{print $NF}' | head -1)"
        say "FAIL  port 8080 is already in use ${who}"
        say "      a boot unit would retry against it every 5 s forever"
        say "      fix:  ${REPO}/drone/camera.sh stop"
        bad=1
    else
        say "ok    port 8080 free"
    fi

    if [[ -x "${OAK_PY}" ]] && "${OAK_PY}" -c 'import depthai' 2>/dev/null; then
        say "ok    depthai available in ${OAK_PY}"
    else
        say "FAIL  ${OAK_PY} missing or cannot import depthai"
        say "      fix:  see docs/REINSTALL.md"
        bad=1
    fi

    if nmcli connection show "${CON}" >/dev/null 2>&1; then
        say "ok    '${CON}' profile exists"
    else
        say "FAIL  no '${CON}' Wi-Fi profile — a boot unit must not invent a password"
        say "      fix:  HOTSPOT_PASSWORD='<8-63 chars>' ${HERE}/wifi_mode.sh on"
        bad=1
    fi

    if dpkg -l dnsmasq-base 2>/dev/null | grep -q '^ii'; then
        say "ok    dnsmasq-base configured (the AP needs it for DHCP)"
    else
        say "FAIL  dnsmasq-base is not configured — a phone would join and get no IP"
        say "      fix:  sudo dpkg --configure -a"
        bad=1
    fi

    if command -v nft >/dev/null 2>&1; then
        say "ok    nft present (port 80 redirect)"
    else
        say "FAIL  nft missing — captive-portal probes on port 80 cannot be redirected"
        bad=1
    fi

    return "${bad}"
}

# --- install -----------------------------------------------------------------
render() {
    local name="$1" out
    out="$(mktemp)"
    sed -e "s|__REPO__|${REPO}|g" \
        -e "s|__USER__|${USER}|g" \
        -e "s|__OAK_PY__|${OAK_PY}|g" \
        "${HERE}/systemd/${name}.in" > "${out}"
    echo "${out}"
}

install_all() {
    local iface unit_gui unit_net nft_tmp
    preflight || die "preflight failed — fix the items above first"

    iface="$(nmcli -t -f DEVICE,TYPE device status | awk -F: '$2=="wifi"{print $1; exit}')"
    [[ -n "${iface}" ]] || die "no Wi-Fi interface found"
    say "Wi-Fi interface: ${iface}"

    unit_gui="$(render "${GUI_UNIT}")"
    unit_net="$(render "${NET_UNIT}")"
    nft_tmp="$(mktemp)"
    sed "s|__IFACE__|${iface}|g" "${HERE}/nft/venator-portal.nft" > "${nft_tmp}"
    # Double-quoted so the paths are baked in now. Single quotes would defer
    # expansion to exit time, when these locals are out of scope - which under
    # `set -u` makes the cleanup itself fail and leaks the temp files.
    trap "rm -f '${unit_gui}' '${unit_net}' '${nft_tmp}'" EXIT

    if (( DRY )); then
        echo; echo "=== ${GUI_UNIT} ==="; cat "${unit_gui}"
        echo; echo "=== ${NET_UNIT} ==="; cat "${unit_net}"
        echo; echo "=== ${NFT_DST} (interface substituted) ==="; cat "${nft_tmp}"
        echo; echo "=== would also install ==="
        echo "  ${HERE}/dnsmasq/venator-portal.conf -> ${DNSMASQ_DST}"
        echo "  ${HERE}/dispatcher/90-venator-portal -> ${DISPATCH_DST}"
        echo "  then: systemctl daemon-reload && systemctl enable ${NET_UNIT} ${GUI_UNIT}"
        return 0
    fi

    say "installing units and portal files (sudo)..."
    sudo install -m 644 "${unit_gui}" "/etc/systemd/system/${GUI_UNIT}" || die "install failed"
    sudo install -m 644 "${unit_net}" "/etc/systemd/system/${NET_UNIT}" || die "install failed"
    sudo install -m 644 "${HERE}/dnsmasq/venator-portal.conf" "${DNSMASQ_DST}" || die "install failed"
    sudo install -D -m 644 "${nft_tmp}" "${NFT_DST}" || die "install failed"
    sudo install -m 755 "${HERE}/dispatcher/90-venator-portal" "${DISPATCH_DST}" || die "install failed"
    sudo systemctl daemon-reload
    sudo systemctl enable "${NET_UNIT}" "${GUI_UNIT}" >/dev/null 2>&1 \
        || die "could not enable the units"
    say "installed and enabled. They will start on the next boot."
    say "Start them now with:  ${SELF} on"
}

uninstall_all() {
    say "removing units and portal files (sudo)..."
    run sudo systemctl disable --now "${GUI_UNIT}" "${NET_UNIT}" 2>/dev/null
    run sudo rm -f "/etc/systemd/system/${GUI_UNIT}" "/etc/systemd/system/${NET_UNIT}" \
                   "${DNSMASQ_DST}" "${NFT_DST}" "${DISPATCH_DST}"
    run sudo systemctl daemon-reload
    run sudo nft delete table ip venator-portal 2>/dev/null
    say "removed. The venator-hotspot Wi-Fi profile is left alone."
}

# --- on / off ----------------------------------------------------------------
field_on() {
    [[ -f "/etc/systemd/system/${GUI_UNIT}" ]] \
        || die "not installed yet — run:  ${SELF} install"
    require_key
    say "bringing up the access point..."
    run sudo systemctl start "${NET_UNIT}"
    say "starting the camera GUI..."
    run sudo systemctl start "${GUI_UNIT}"
    (( DRY )) || sleep 3
    status
}

field_off() {
    say "stopping the camera GUI..."
    run sudo systemctl stop "${GUI_UNIT}" 2>/dev/null
    # wifi_mode.sh off already knows which network to go back to, and refuses
    # when that would strand an SSH session with no route home.
    say "rejoining the previous Wi-Fi..."
    if (( DRY )); then
        echo "  [dry-run] ${HERE}/wifi_mode.sh off"
    else
        bash "${HERE}/wifi_mode.sh" off
    fi
}

# --- status ------------------------------------------------------------------
status() {
    local iface active gui_state gui_pid clients
    iface="$(nmcli -t -f DEVICE,TYPE device status | awk -F: '$2=="wifi"{print $1; exit}')"
    active="$(nmcli -e no -g GENERAL.CONNECTION device show "${iface}" 2>/dev/null)"
    [[ "${active}" == "--" ]] && active=""

    echo "Field mode"

    if [[ "${active}" == "${CON}" ]]; then
        clients="$(iw dev "${iface}" station dump 2>/dev/null | grep -c '^Station')"
        printf "  Wi-Fi         : AP '%s' on %s, %s phone(s) joined\n" \
            "$(nmcli -e no -g 802-11-wireless.ssid connection show "${CON}")" \
            "${iface}" "${clients}"
    elif [[ -n "${active}" ]]; then
        printf "  Wi-Fi         : joined '%s' (client) — AP is off\n" "${active}"
    else
        printf "  Wi-Fi         : not connected\n"
    fi

    gui_state="$(systemctl is-active "${GUI_UNIT}" 2>/dev/null || true)"
    gui_pid="$(systemctl show "${GUI_UNIT}" -p MainPID --value 2>/dev/null || true)"
    if [[ "${gui_state}" == "active" ]]; then
        printf "  Camera GUI    : %s (pid %s)\n" "${gui_state}" "${gui_pid}"
    else
        printf "  Camera GUI    : %s\n" "${gui_state:-not installed}"
    fi

    local portal="" dns_ok=0 nft_ok=0
    [[ -e "${DNSMASQ_DST}" ]] && dns_ok=1
    sudo -n nft list table ip venator-portal >/dev/null 2>&1 && nft_ok=1
    (( dns_ok )) && portal="dns ok" || portal="dns MISSING"
    (( nft_ok )) && portal="${portal}, port-80 redirect loaded" \
                 || portal="${portal}, port-80 redirect not loaded"
    printf "  Captive portal: %s\n" "${portal}"

    # dnsmasq reads its conf-dir once at startup, so a fragment newer than the
    # running dnsmasq is installed but not in effect - a genuinely confusing
    # state worth calling out rather than leaving to be discovered.
    if (( dns_ok )) && pgrep -f nm-dnsmasq >/dev/null 2>&1; then
        local dpid dstart
        dpid="$(pgrep -f nm-dnsmasq | head -1)"
        dstart="$(stat -c %Y "/proc/${dpid}" 2>/dev/null || echo 0)"
        if (( dstart > 0 )) && (( $(stat -c %Y "${DNSMASQ_DST}" 2>/dev/null || echo 0) > dstart )); then
            printf "                  ! config is newer than the running dnsmasq — cycle the AP:\n"
            printf "                    sudo nmcli con down %s && sudo nmcli con up %s\n" "${CON}" "${CON}"
        fi
    fi

    printf "  Phone URL     : %s\n" "$(url)"
    printf "  At boot       : %s / %s\n" \
        "$(systemctl is-enabled "${NET_UNIT}" 2>/dev/null || echo 'not installed')" \
        "$(systemctl is-enabled "${GUI_UNIT}" 2>/dev/null || echo 'not installed')"
}

case "${1:-status}" in
    on)        field_on ;;
    off)       field_off ;;
    toggle)    iface="$(nmcli -t -f DEVICE,TYPE device status | awk -F: '$2=="wifi"{print $1; exit}')"
               if [[ "$(nmcli -e no -g GENERAL.CONNECTION device show "${iface}" 2>/dev/null)" == "${CON}" ]]; then
                   field_off
               else
                   field_on
               fi ;;
    status)    status ;;
    url)       url ;;
    install)   install_all ;;
    uninstall) uninstall_all ;;
    preflight) preflight ;;
    _require_key) require_key ;;
    *) echo "Usage: $0 [on|off|toggle|status|url|install|uninstall|preflight] [--dry-run] [--pause]"; exit 2 ;;
esac
