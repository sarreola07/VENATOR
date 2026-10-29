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

# ---------------------------------------------------------------- dashboard
#
# The QR sheet advertises :5037, but unlike the camera this is NOT a systemd
# unit -- symposium_dashboard.sh starts it by hand, because it has to stop
# venator-c2 first (one owner per serial port) and give the port back on exit.
# So a reboot leaves the dashboard QR pointing at a dead port while every other
# check still reads green. Checking it here is the only thing standing between
# that and finding out in front of an audience.
head_ "Mission dashboard"
WEB_PORT="${WEB_PORT:-5037}"
dash="$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "http://127.0.0.1:${WEB_PORT}/" 2>/dev/null)"
if [[ "${dash}" == "200" ]]; then
    ok "answering on :${WEB_PORT} (reminder: it does NOT start at boot)"
else
    # WARN, not FAIL: the dashboard is optional to the camera demo, and turning
    # the whole run red for a tool you chose not to start is how a check stops
    # being read -- the same reasoning as the GPS case at the top of this file.
    warn "not answering on :${WEB_PORT} — it is NOT a service, so a reboot stops it"
    warn "      start it:  click '7 · Mission dashboard', or"
    warn "                 bash ${REPO}/deploy/symposium_dashboard.sh"
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
#
# SKIP_FC=1 drops the probe. Worst case it costs 12 s in wait_heartbeat plus
# two 6 s recv_match timeouts -- that is the board enumerating but not
# answering, not the common case, and when the FC is simply absent the branch
# below is not taken at all. So this is for re-testing the phone path outside
# while the aircraft is powered down or out of reach, not a general speed-up.
#
# The absent/bootloader test comes FIRST: saying "probe skipped" when there was
# no device to probe reads as though a healthy board was ignored.
if [[ "$fc" == *_BL_* || -z "$fc" ]]; then
    :
elif [[ -n "${SKIP_FC:-}" ]]; then
    info "heartbeat probe skipped (SKIP_FC=1)"
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

# ---------------------------------------------------------------- portal
#
# The phone path, end to end, from the Jetson alone. This section exists
# because the port-80 redirect failed silently on every boot for six days: the
# dispatcher logged four words with nft's reason discarded, and every check
# anyone ran from this machine bypassed the rule entirely, since locally
# originated traffic does not traverse prerouting. The `output` chain in
# deploy/nft/venator-portal.nft is what makes the curl below mean anything.
head_ "Captive portal — the phone path"
AP_IP="${AP_IP:-10.42.0.1}"
PORTAL_HOST="${PORTAL_HOST:-venator.com}"

if ip -4 -o addr show 2>/dev/null | grep -q "${AP_IP}/"; then
    ok "access point is UP — ${AP_IP} is assigned"

    # nft. `sudo -n` never prompts; distinguish "rule missing" from "could not
    # look", because reporting a missing rule you simply failed to read would
    # send you chasing a bug that is not there.
    if sudo -n nft list table ip venator-portal >/dev/null 2>&1; then
        ok "nft table venator-portal is loaded"
    elif sudo -n true >/dev/null 2>&1; then
        fail "nft table venator-portal NOT loaded — port 80 goes nowhere"
        fail "      journalctl -t venator-portal -b | tail -3   (it now prints nft's reason)"
    else
        info "nft table not read (needs sudo) — the HTTP checks below still prove it"
    fi

    ans="$(dig +short +time=2 +tries=1 "${PORTAL_HOST}" @"${AP_IP}" 2>/dev/null | head -1)"
    if [[ "${ans}" == "${AP_IP}" ]]; then
        ok "DNS  ${PORTAL_HOST} -> ${AP_IP}"
    else
        fail "DNS  ${PORTAL_HOST} -> '${ans:-no answer}'  (want ${AP_IP})"
        fail "      sudo nmcli con down venator-hotspot && sudo nmcli con up venator-hotspot"
    fi

    # 403 is a PASS: it is gui_server refusing an untokened request, which it
    # can only do if the packet reached 8080. Reaching the server is the thing
    # under test here, not being authorised by it.
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "http://${AP_IP}/" 2>/dev/null)"
    case "${code}" in
        200|302|403) ok "port 80 -> 8080 reached the camera server (HTTP ${code})" ;;
        000)
            # Do NOT blame the nft rule here. curl reports 000 for a refusal and
            # for a timeout alike, and the two have opposite causes: no rule
            # versus a rule pointing at a server that is not accepting. Saying
            # "the dnat rule did not load" directly under a line reporting the
            # table as loaded sent us hunting the firewall while the real fault
            # was gui_server wedged with a full accept queue. Name the suspect
            # by what else is true.
            if curl -s -o /dev/null --max-time 6 "http://127.0.0.1:8080/healthz" 2>/dev/null; then
                fail "port 80 did not answer, but :8080 is healthy — the redirect is the problem"
                fail "      journalctl -t venator-portal -b | tail -3"
            else
                fail "port 80 did not answer, and :8080 is not answering either"
                fail "      the redirect is probably fine — the camera server is down or wedged"
                fail "      check:  ss -lntp | grep 8080   (Recv-Q at the backlog = wedged, not dead)"
                fail "      then:   sudo systemctl restart venator-gui"
            fi
            ;;
        *)           warn "port 80 answered HTTP ${code} — unexpected, but something is there" ;;
    esac

    loc="$(curl -s -o /dev/null -w '%{redirect_url}' --max-time 6 \
           -H "Host: captive.apple.com" "http://${AP_IP}/hotspot-detect.html" 2>/dev/null)"
    if [[ "${loc}" == *"${PORTAL_HOST}"* ]]; then
        ok "iOS captive probe -> ${loc}"
    else
        fail "iOS captive probe did not redirect (got '${loc:-nothing}')"
        fail "      the phone will show no sign-in sheet; use the QR code instead"
    fi
else
    # Not a failure. The Jetson has one radio, so being a client is the normal
    # state while developing -- and turning this red would train you to ignore it.
    info "access point is DOWN — this Jetson is a Wi-Fi client right now"
    info "      the phone path cannot be tested from here"
    info "      bring it up with:  bash deploy/wifi_mode.sh on"
fi

# ---------------------------------------------------------------- QR sheet
head_ "QR sheet"
QR_HTML="${QR_HTML:-${HOME}/Desktop/Symposium/venator-qr.html}"
QR_PNG="${QR_PNG:-${HOME}/Desktop/Symposium/venator-qr-camera.png}"
live_tok="$(bash "${HERE}/field_mode.sh" url 2>/dev/null)"; live_tok="${live_tok##*k=}"
if [[ ! -f "${QR_HTML}" || ! -f "${QR_PNG}" ]]; then
    warn "no QR sheet yet — bash deploy/symposium_qr.sh"
elif [[ -n "${live_tok}" ]] && grep -q "${live_tok}" "${QR_HTML}" 2>/dev/null; then
    ok "QR sheet matches the running token"
else
    # A printed sheet with a rotated token fails exactly when you point at it.
    fail "QR sheet is STALE — it does not carry the current token"
    fail "      regenerate:  bash deploy/symposium_qr.sh"
fi

# ---------------------------------------------------------------- verdict
echo
if (( bad )); then
    printf "  ${R}SOMETHING NEEDS FIXING — read the FAIL lines above.${Z}\n\n"
    exit 1
fi
printf "  ${G}ALL CLEAR.${Z}  Props are OFF, services are up, the camera is serving.\n"
printf "  Demo order:  RUN 7 (status) -> RUN 1 (each motor) -> RUN 2 (all) -> RUN 8 (refuses).\n\n"
