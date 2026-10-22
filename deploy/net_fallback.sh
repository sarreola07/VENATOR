#!/usr/bin/env bash
# Decide, at boot, whether this Jetson joins a network or becomes one.
#
#   ./deploy/net_fallback.sh              # decide now (what the boot unit runs)
#   ./deploy/net_fallback.sh --dry-run    # say what it would do, change nothing
#
# THE PROBLEM THIS SOLVES
# On a bench the Jetson should join the Wi-Fi it knows, so apt and git work. In
# a field there is no such network, and an operator cannot type anything into
# an airframe - so it has to host its own access point and the camera GUI with
# no intervention at all.
#
# So: wait a short while for NetworkManager to join something it already knows.
# If it does, leave well alone. If nothing turns up, bring up the hotspot.
#
# WHY WAIT RATHER THAN SET autoconnect ON THE HOTSPOT
# Giving venator-hotspot a high autoconnect priority would also work, and is
# simpler, but it takes the Jetson off the lab Wi-Fi on every single reboot -
# and with no Ethernet carrier that is its only route. This way the bench keeps
# its internet and the field still self-hosts.
#
# WHY IT DOES NOT SWITCH BACK
# NetworkManager keeps scanning while the AP is up. A rule like "a known
# network appeared, go back to it" would drop the hotspot - and the operator's
# video link - the moment the aircraft drifted within range of the lab. The
# decision is made once per boot, on purpose. deploy/field_mode.sh off is the
# way back.
set -uo pipefail

SELF="$(readlink -f "$0")"
HERE="$(cd "$(dirname "${SELF}")" && pwd)"
WIFI_MODE="${HERE}/wifi_mode.sh"
CON="venator-hotspot"

# How long to give NetworkManager to join something it knows. Its own
# autoconnect retries run for longer than this, so the number is a judgement
# about how long an operator should wait for a camera, not a technical limit.
# 45 s covers a cold Realtek bring-up plus a DHCP round trip with margin.
WAIT_S="${NET_FALLBACK_WAIT_S:-45}"

STATE_DIR="${XDG_STATE_HOME:-${HOME:-/root}/.local/state}/venator"
MODE_FILE="${STATE_DIR}/net-mode"
LOG="${STATE_DIR}/field_mode.log"

DRY=0
for arg in "$@"; do [[ "${arg}" == "--dry-run" ]] && DRY=1; done

say() {
    echo "$*"
    { mkdir -p "${STATE_DIR}" && echo "$(date '+%F %T') net_fallback: $*" >> "${LOG}"; } 2>/dev/null || true
}

record() {
    # --dry-run must not touch anything, including this breadcrumb. The first
    # version wrote it unconditionally, which a dry run then left behind as a
    # misleading record of a decision that was never acted on.
    (( DRY )) && { say "[dry-run] would record: $1"; return 0; }
    { mkdir -p "${STATE_DIR}" && printf '%s %s\n' "$(date '+%F %T')" "$1" > "${MODE_FILE}"; } 2>/dev/null || true
}

# A Wi-Fi connection that is NOT our own access point. Reuses wifi_mode.sh's
# definition so the two scripts cannot drift on what counts as an AP.
joined_client_network() {
    local name
    name="$(nmcli -e no -t -f TYPE,STATE,CONNECTION device status 2>/dev/null \
            | awk -F: '$1 == "wifi" && $2 == "connected" { print $3; exit }')"
    [[ -n "${name}" ]] || return 1
    [[ "${name}" == "${CON}" ]] && return 1
    # 802-11-wireless.mode == ap means it is a hotspot, not a network we joined.
    [[ "$(nmcli -e no -g 802-11-wireless.mode connection show "${name}" 2>/dev/null)" == "ap" ]] \
        && return 1
    echo "${name}"
}

main() {
    if [[ ! -x "${WIFI_MODE}" ]]; then
        say "cannot find wifi_mode.sh at ${WIFI_MODE}"
        return 1
    fi

    # Already hosting? Nothing to decide. Makes the script idempotent, which
    # matters because systemd may re-run it and an operator may run it by hand.
    local active
    active="$(nmcli -e no -t -f TYPE,STATE,CONNECTION device status 2>/dev/null \
              | awk -F: '$1 == "wifi" && $2 == "connected" { print $3; exit }')"
    if [[ "${active}" == "${CON}" ]]; then
        say "hotspot already up — nothing to do"
        record "ap (already up)"
        return 0
    fi

    local waited=0 found
    while (( waited < WAIT_S )); do
        if found="$(joined_client_network)"; then
            say "joined '${found}' — staying a client, no hotspot needed"
            record "client (${found})"
            return 0
        fi
        sleep 3
        waited=$(( waited + 3 ))
    done

    say "no known Wi-Fi within ${WAIT_S}s — starting the hotspot"
    if (( DRY )); then
        say "[dry-run] would run: ${WIFI_MODE} _boot_ap"
        record "ap (dry-run)"
        return 0
    fi

    # _boot_ap is the non-interactive path: no sudo prompt, no TTY password
    # prompt, no nested systemd-run. See the comment above boot_ap() in
    # wifi_mode.sh for why hotspot_on() cannot be used here.
    if [[ "$(id -u)" == "0" ]]; then
        bash "${WIFI_MODE}" _boot_ap
    else
        sudo -n bash "${WIFI_MODE}" _boot_ap 2>/dev/null \
            || { say "needs root to bring up the AP (run via the boot unit, or with sudo)"; return 1; }
    fi
    local rc=$?
    record "$( (( rc == 0 )) && echo 'ap' || echo 'ap (FAILED)' )"
    return "${rc}"
}

main "$@"
