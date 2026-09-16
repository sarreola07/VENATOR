#!/usr/bin/env bash
# Switch the Jetson's Wi-Fi between two modes:
#   CLIENT  — joins a normal network (e.g. school Wi-Fi) for internet
#   HOTSPOT — broadcasts its own network "VenatorDrone"; laptops join it and
#             reach the Jetson at 10.42.0.1 (SSH, camera web stream), with no
#             school firewall in between
#
#   ./wifi_mode.sh on       # HOTSPOT
#   ./wifi_mode.sh off      # CLIENT: rejoin the Wi-Fi network used before
#   ./wifi_mode.sh toggle   # flip between the two
#   ./wifi_mode.sh status   # current mode, address, joined laptops
#
# The Jetson has ONE Wi-Fi card, so while the hotspot is on it is off the school
# Wi-Fi (no internet, unless Ethernet is plugged in — the hotspot then shares it).
#
# Safe to run over SSH: the switch runs as a system job that finishes even when
# your session drops, and if the new network fails to come up it switches back
# to the old one. Results are logged to ~/.local/state/venator/wifi_mode.log.
#
# Hotspot settings — asked for / defaulted the first time, then saved in
# NetworkManager. Set one again on the command line to change it:
#   HOTSPOT_SSID=VenatorDrone   HOTSPOT_PASSWORD=...   (8-63 characters)
#   HOTSPOT_BAND=a  (5 GHz, default — keeps clear of 2.4 GHz RC radios) | bg (2.4 GHz)
#   HOTSPOT_CHANNEL=36          HOTSPOT_IFACE=wlP1p1s0 (auto-detected)
set -uo pipefail
trap '' HUP   # keep going if the SSH session carrying us drops mid-switch

SELF="$(readlink -f "$0")"
CON="venator-hotspot"                 # NetworkManager profile this script owns
HOTSPOT_IP="10.42.0.1"
STREAM_PORT="${CAMERA_STREAM_PORT:-8080}"
STATE_DIR="${XDG_STATE_HOME:-${HOME:-/root}/.local/state}/venator"   # HOME is unset under systemd-run
PREV_FILE="${STATE_DIR}/wifi-previous-network"
LOG="${STATE_DIR}/wifi_mode.log"

say() {
    echo "$*"
    { mkdir -p "${STATE_DIR}" && echo "$(date '+%F %T') $*" >> "${LOG}"; } 2>/dev/null || true
}

die() { say "$*"; exit 1; }

# Name of the Wi-Fi card, e.g. wlP1p1s0.
wifi_iface() {
    if [[ -n "${HOTSPOT_IFACE:-}" ]]; then
        echo "${HOTSPOT_IFACE}"
        return
    fi
    nmcli -t -f DEVICE,TYPE device status 2>/dev/null | awk -F: '$2 == "wifi" { print $1; exit }'
}

# Connection currently active on the Wi-Fi card, or nothing.
active_con() {
    local con; con="$(nmcli -e no -g GENERAL.CONNECTION device show "$1" 2>/dev/null)"
    [[ "${con}" == "--" ]] && con=""
    echo "${con}"
}

is_ap_profile() {
    [[ "$(nmcli -e no -g 802-11-wireless.mode connection show "$1" 2>/dev/null)" == "ap" ]]
}

ap_supported() {
    command -v iw >/dev/null 2>&1 || return 0   # can't check; let NetworkManager decide
    iw list 2>/dev/null | awk '
        /Supported interface modes/ { f = 1; next }
        f && $1 == "*"              { if ($2 == "AP") ok = 1; next }
        f                           { f = 0 }
        END                         { exit ok ? 0 : 1 }'
}

# The client network to return to: the one we left, else the most recently
# used saved Wi-Fi network that isn't a hotspot.
previous_network() {
    local name=""
    [[ -f "${PREV_FILE}" ]] && name="$(cat "${PREV_FILE}")"
    if [[ -n "${name}" ]] && nmcli connection show "${name}" >/dev/null 2>&1 \
       && ! is_ap_profile "${name}"; then
        echo "${name}"
        return
    fi
    while IFS= read -r name; do
        is_ap_profile "${name}" && continue
        echo "${name}"
        return
    done < <(nmcli -e no -t -f TIMESTAMP,TYPE,NAME connection show 2>/dev/null \
             | awk -F: '$2 == "802-11-wireless" || $2 == "wifi"' | sort -t: -k1,1 -nr | cut -d: -f3-)
}

create_hotspot() {
    local iface="$1" ssid="${HOTSPOT_SSID:-VenatorDrone}" band="${HOTSPOT_BAND:-a}"
    local pass="${HOTSPOT_PASSWORD:-}" pass2 chan="${HOTSPOT_CHANNEL:-}"
    [[ -z "${chan}" && "${band}" == "a" ]] && chan=36
    if [[ -z "${pass}" ]]; then
        [[ -t 0 ]] || die "Set HOTSPOT_PASSWORD (8-63 characters) the first time."
        echo "First-time setup: choose a password for the '${ssid}' network (8-63 characters)."
        while true; do
            read -rsp "  Password: " pass; echo
            read -rsp "  Again:    " pass2; echo
            [[ "${pass}" == "${pass2}" ]] || { echo "  Passwords don't match."; continue; }
            (( ${#pass} >= 8 && ${#pass} <= 63 )) || { echo "  Must be 8-63 characters."; continue; }
            break
        done
    fi
    (( ${#pass} >= 8 && ${#pass} <= 63 )) || die "Hotspot password must be 8-63 characters."
    say "Creating hotspot '${ssid}' on ${iface} ($( [[ "${band}" == a ]] && echo 5 || echo 2.4 ) GHz)..."
    # WPA2-PSK/CCMP only: the most compatible choice for Windows and Mac laptops.
    sudo nmcli connection add type wifi ifname "${iface}" con-name "${CON}" autoconnect no \
        ssid "${ssid}" 802-11-wireless.mode ap 802-11-wireless.band "${band}" \
        802-11-wireless.channel "${chan:-0}" \
        ipv4.method shared ipv4.addresses "${HOTSPOT_IP}/24" ipv6.method disabled \
        wifi-sec.key-mgmt wpa-psk wifi-sec.proto rsn wifi-sec.pairwise ccmp \
        wifi-sec.group ccmp wifi-sec.psk "${pass}" >/dev/null
}

# Apply only the settings given on the command line to the saved hotspot.
update_hotspot() {
    local changes=""
    if [[ -n "${HOTSPOT_SSID:-}" ]]; then
        sudo nmcli connection modify "${CON}" 802-11-wireless.ssid "${HOTSPOT_SSID}" || return 1
        changes+=" ssid"
    fi
    if [[ -n "${HOTSPOT_BAND:-}" || -n "${HOTSPOT_CHANNEL:-}" ]]; then
        local band="${HOTSPOT_BAND:-$(nmcli -e no -g 802-11-wireless.band connection show "${CON}")}"
        local chan="${HOTSPOT_CHANNEL:-}"
        [[ -z "${chan}" && "${band}" == "a" ]] && chan=36
        # band and channel must agree, so set them together (channel 0 = automatic)
        sudo nmcli connection modify "${CON}" 802-11-wireless.band "${band}" \
            802-11-wireless.channel "${chan:-0}" || return 1
        changes+=" band/channel"
    fi
    if [[ -n "${HOTSPOT_PASSWORD:-}" ]]; then
        (( ${#HOTSPOT_PASSWORD} >= 8 && ${#HOTSPOT_PASSWORD} <= 63 )) \
            || die "Hotspot password must be 8-63 characters."
        sudo nmcli connection modify "${CON}" wifi-sec.psk "${HOTSPOT_PASSWORD}" || return 1
        changes+=" password"
    fi
    [[ -n "${changes}" ]] && say "Updated hotspot settings:${changes}"
    return 0
}

# Activate connection $1; if that fails and $2 is given, bring $2 back up.
# Runs as a transient systemd job so it completes even if this SSH session
# dies the moment the Wi-Fi changes. Returns non-zero if $1 didn't come up.
switch_to() {
    local unit; unit="venator-wifi-$(date +%s)"
    if sudo systemd-run --quiet --wait --collect --unit "${unit}" \
            /bin/bash "${SELF}" _switch "$1" "${2:-}"; then
        return 0
    fi
    local why; why="$(sudo journalctl -u "${unit}" -o cat --no-pager 2>/dev/null | tail -n 4)"
    [[ -n "${why}" ]] && say "${why}"
    if grep -qi "secrets were required" <<< "${why}"; then
        say "Hint: that network's password is saved only in your desktop keyring. In Settings > Wi-Fi,"
        say "      edit the network and save the password for all users, then try again."
    elif grep -qi "dnsmasq" <<< "${why}"; then
        say "Hint: the hotspot needs dnsmasq-base:  sudo apt install dnsmasq-base"
    fi
    return 1
}

_switch() {   # internal: runs as root under systemd-run
    nmcli --wait 60 connection up "$1" && exit 0
    [[ -n "${2:-}" ]] && nmcli --wait 60 connection up "$2"
    exit 1
}

warn_ssh() {
    [[ -n "${SSH_CONNECTION:-}" ]] || return 0
    say "Note: if this SSH session runs over Wi-Fi it will drop now. The switch still"
    say "      finishes; $1"
}

hotspot_on() {
    local iface current
    iface="$(wifi_iface)"
    [[ -n "${iface}" ]] || die "No Wi-Fi card found (check: nmcli device status)."
    current="$(active_con "${iface}")"
    if [[ "${current}" == "${CON}" ]]; then
        echo "Hotspot is already on."
        status
        return 0
    fi
    ap_supported || die "This Wi-Fi card doesn't support hotspot (access point) mode."
    sudo -v || die "sudo is needed to change Wi-Fi settings."

    if nmcli connection show "${CON}" >/dev/null 2>&1; then
        update_hotspot || die "Could not update the hotspot settings."
    else
        create_hotspot "${iface}" || die "Could not create the hotspot."
    fi
    if [[ -n "${current}" ]] && ! is_ap_profile "${current}"; then
        mkdir -p "${STATE_DIR}" && printf '%s\n' "${current}" > "${PREV_FILE}"
    fi

    local ssid; ssid="$(nmcli -e no -g 802-11-wireless.ssid connection show "${CON}")"
    warn_ssh "join '${ssid}' on your laptop, then: ssh ${USER:-$(id -un)}@${HOTSPOT_IP}"
    say "Starting hotspot '${ssid}'${current:+ (leaving '${current}')}..."
    if switch_to "${CON}" "${current}"; then
        say "Hotspot ON."
        status
        return 0
    fi
    say "Hotspot failed to start.${current:+ Went back to '${current}'.}"
    if [[ "$(nmcli -e no -g 802-11-wireless.band connection show "${CON}")" == "a" ]]; then
        say "5 GHz hotspots aren't allowed on every card or country setting:"
        say "  - 'iw reg get' should show your country (e.g. country US), not 00"
        say "  - or use 2.4 GHz:  HOTSPOT_BAND=bg ./wifi_mode.sh on"
        say "    (if your RC transmitter is 2.4 GHz, turn the hotspot off before flying)"
    fi
    return 1
}

hotspot_off() {
    local iface current prev
    iface="$(wifi_iface)"
    [[ -n "${iface}" ]] || die "No Wi-Fi card found (check: nmcli device status)."
    current="$(active_con "${iface}")"
    if [[ "${current}" != "${CON}" ]]; then
        echo "Hotspot is already off."
        status
        return 0
    fi
    sudo -v || die "sudo is needed to change Wi-Fi settings."
    prev="$(previous_network)"

    if [[ -z "${prev}" ]]; then
        # Nothing to switch to. Over SSH through the hotspot that would strand the Jetson.
        if [[ "${SSH_CONNECTION:-}" == *" ${HOTSPOT_IP} "* ]]; then
            die "No saved Wi-Fi network to switch to — turning the hotspot off would cut this SSH session with no way back. Run it at the Jetson instead."
        fi
        say "No saved Wi-Fi network to rejoin — turning the hotspot off."
        sudo nmcli connection down "${CON}" >/dev/null && say "Hotspot OFF."
        return
    fi

    warn_ssh "reconnect over the school network (e.g. Tailscale) once it's back."
    say "Switching from the hotspot to '${prev}'..."
    if switch_to "${prev}" "${CON}"; then
        say "Hotspot OFF — back on '${prev}'."
        status
        return 0
    fi
    say "Could not join '${prev}' (out of range?). The hotspot is back on so the Jetson stays reachable."
    return 1
}

status() {
    local iface con ip
    iface="$(wifi_iface)"
    if [[ -z "${iface}" ]]; then
        echo "Wi-Fi: no Wi-Fi card found"
        return 1
    fi
    con="$(active_con "${iface}")"
    ip="$(nmcli -e no -g IP4.ADDRESS device show "${iface}" 2>/dev/null | head -n1 | cut -d/ -f1)"
    if [[ "${con}" == "${CON}" ]]; then
        local ssid band clients
        ssid="$(nmcli -e no -g 802-11-wireless.ssid connection show "${CON}")"
        band="$(nmcli -e no -g 802-11-wireless.band connection show "${CON}")"
        clients="$(iw dev "${iface}" station dump 2>/dev/null | grep -c '^Station')"
        ip="${ip:-${HOTSPOT_IP}}"
        echo "Wi-Fi mode: HOTSPOT — network '${ssid}' ($( [[ "${band}" == bg ]] && echo 2.4 || echo 5 ) GHz)"
        echo "  Jetson address : ${ip}"
        echo "  Laptops joined : ${clients:-0}"
        echo "  SSH            : ssh ${USER:-$(id -un)}@${ip}"
        echo "  Camera stream  : http://${ip}:${STREAM_PORT}   (after ./ai_camera.sh stream)"
    elif [[ -n "${con}" ]]; then
        echo "Wi-Fi mode: CLIENT — connected to '${con}' (IP ${ip:-none})"
    else
        echo "Wi-Fi mode: CLIENT — not connected"
    fi
}

# --pause (used by the Desktop shortcut) keeps the terminal window open at the end.
for arg in "$@"; do
    [[ "${arg}" == "--pause" ]] && trap 'echo; read -r -n1 -p "Press any key to close..."' EXIT
done

case "${1:-status}" in
    on)      hotspot_on ;;
    off)     hotspot_off ;;
    toggle)  iface="$(wifi_iface)"
             if [[ -n "${iface}" && "$(active_con "${iface}")" == "${CON}" ]]; then
                 hotspot_off
             else
                 hotspot_on
             fi ;;
    status)  status ;;
    _switch) _switch "${2:-}" "${3:-}" ;;
    *) echo "Usage: $0 [on|off|toggle|status]"; exit 2 ;;
esac
