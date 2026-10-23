#!/usr/bin/env bash
# The camera, for demo day. Prints every working address and opens the feed.
#
#   bash deploy/symposium_camera.sh          # show the addresses
#   bash deploy/symposium_camera.sh --open   # ...and open it on this Jetson
#
# WHY THIS DOES NOT START A CAMERA
#
# The OAK allows exactly ONE host process. venator-gui.service already owns it
# and is already serving the feed, so anything that opens the device a second
# time -- drone/camera.sh preview, oak_camera.sh detect, a stray script -- gets
# X_LINK_DEVICE_ALREADY_IN_USE and fails. That error is the arbitration working,
# not a fault. This script therefore shows you the feed that is running rather
# than competing for the device.
#
# WHY IT LEADS WITH :8080 AND NOT venatordrone.com
#
# The pretty name needs two things: dnsmasq answering venatordrone.com with
# 10.42.0.1, and an nft rule redirecting port 80 to 8080, loaded by the
# NetworkManager dispatcher when the hotspot comes up. The DNS half is reliable;
# the redirect is one more moving part, and when it fails the phone gets a dead
# connection with no clue why. Port 8080 is where the server actually listens,
# so it works whether or not the redirect loaded. Lead with what cannot fail.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
AP_IP="${AP_IP:-10.42.0.1}"
PORT="${PORT:-8080}"

G=$'\033[92m'; R=$'\033[91m'; Y=$'\033[93m'; B=$'\033[94m'; Z=$'\033[0m'

# The token the RUNNING service is serving. field_mode.sh resolves it through
# the same VENATOR_KEY_FILE the unit sets, so the two cannot disagree.
url_line="$(bash "${HERE}/field_mode.sh" url 2>/dev/null)"
token="${url_line##*k=}"
[[ "$token" == "$url_line" ]] && token=""        # no ?k= in the output

printf "\n${B}VENATOR — camera feed${Z}\n\n"

if ! curl -sf --max-time 5 "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
    printf "  ${R}The camera server is not answering on :${PORT}.${Z}\n"
    printf "  Start it:   sudo systemctl start venator-gui\n"
    printf "  Then check: bash deploy/symposium_check.sh\n\n"
    exit 1
fi
printf "  ${G}Server is up on :${PORT}.${Z}\n\n"

if [[ -z "$token" ]]; then
    printf "  ${R}No token found.${Z} The GUI binds 127.0.0.1 only without a key,\n"
    printf "  so a phone cannot reach it. Fix: bash deploy/field_mode.sh _require_key\n\n"
    exit 1
fi

# --- the one to read out ---------------------------------------------------
ap_up=0
ip -4 -o addr show 2>/dev/null | grep -q "${AP_IP}/" && ap_up=1

printf "  ${B}FOR A PHONE ON THE VenatorDrone WI-FI${Z}\n"
if (( ap_up )); then
    printf "    ${G}http://%s:%s/?k=%s${Z}\n\n" "$AP_IP" "$PORT" "$token"
else
    printf "    ${Y}http://%s:%s/?k=%s${Z}\n" "$AP_IP" "$PORT" "$token"
    printf "    ${Y}(the hotspot is not up yet — icon '3 · Wi-Fi hotspot' starts it)${Z}\n\n"
fi

# --- every other address it is reachable on --------------------------------
printf "  ${B}OTHER ADDRESSES${Z}\n"
while read -r _ dev _ cidr _; do
    ipaddr="${cidr%%/*}"
    [[ "$dev" == "lo" || -z "$ipaddr" || "$ipaddr" == "$AP_IP" ]] && continue
    printf "    http://%s:%s/?k=%s   (%s)\n" "$ipaddr" "$PORT" "$token" "$dev"
done < <(ip -4 -o addr show 2>/dev/null)
printf "    http://jetson.local:%s/?k=%s   (mDNS)\n\n" "$PORT" "$token"

# --- the pretty name, honestly labelled ------------------------------------
printf "  ${B}CAPTIVE PORTAL${Z}  (convenience — the addresses above always work)\n"
if sudo -n nft list table ip venator-portal >/dev/null 2>&1; then
    printf "    ${G}http://venatordrone.com/${Z}   redirect is loaded\n\n"
else
    printf "    ${Y}http://venatordrone.com/${Z}   needs the port 80 -> %s redirect,\n" "$PORT"
    printf "    ${Y}which loads when the hotspot comes up. Check it with:${Z}\n"
    printf "      sudo nft -c -f /etc/venator/portal.nft      # syntax only\n"
    printf "      sudo nft list table ip venator-portal       # is it loaded\n"
    printf "      journalctl -t venator-portal -b             # what the hook did\n\n"
fi

printf "  ${Y}Do not run 'camera.sh preview' or 'oak_camera.sh detect' now.${Z}\n"
printf "  The OAK takes one process at a time and venator-gui has it; a second\n"
printf "  one gets X_LINK_DEVICE_ALREADY_IN_USE. To preview locally, use the\n"
printf "  address above in a browser on this Jetson.\n\n"

if [[ "${1:-}" == "--open" ]]; then
    printf "  Opening http://127.0.0.1:%s/?k=%s ...\n\n" "$PORT" "$token"
    xdg-open "http://127.0.0.1:${PORT}/?k=${token}" >/dev/null 2>&1 &
fi
