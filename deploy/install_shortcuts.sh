#!/usr/bin/env bash
# Install the desktop shortcuts (no sudo, no systemd — user level only):
#   * Venator Mission         — opens the mission menu in a terminal
#   * AI Camera (toggle)      — starts/stops the OAK-D tracker on demand
#   * AI Camera (preview)     — live camera window on the Jetson's screen
#   * AI Camera (web stream)  — tracker + video for laptop browsers
#   * Wi-Fi Hotspot (toggle)  — school Wi-Fi <-> the Jetson's own hotspot
#   * Wildlife Camera         — camera 2, the CSI day/night feed (if CAM0 fitted)
#   * Wildlife Detector       — camera 1, OAK-D animal/person detection
#
# The AI camera is intentionally NOT a boot service: it is optional and toggled
# by hand, fully decoupled from the core MAVLink/telemetry background services.
#
# The launchers in desktop/ are templates: __REPO__ is replaced with wherever
# this clone actually lives, so the same repo works on the Jetson, a laptop or
# any folder name. Re-run this after moving or re-cloning the repo.
#
# Run from your desktop terminal:  bash deploy/install_shortcuts.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APPS="${HOME}/.local/share/applications"
DESKTOP_DIR="${HOME}/Desktop"
mkdir -p "${APPS}" "${DESKTOP_DIR}"

chmod +x "${REPO}/drone/run_missions.sh" "${REPO}/drone/camera.sh" \
         "${REPO}/drone/camera_publisher.py" "${REPO}/deploy/wifi_mode.sh"

install_launcher() {
    local file="$1"          # basename of the .desktop this produces
    local into="${2:-${DESKTOP_DIR}}"
    local template="${REPO}/deploy/desktop/${file}.in"
    local dest="${into}/${file}"
    local rendered
    rendered="$(mktemp)"
    sed "s|__REPO__|${REPO}|g" "${template}" > "${rendered}"
    install -m 755 "${rendered}" "${dest}"
    # Only the Desktop copies belong in the applications menu; the Symposium
    # folder is a place to click, not a second set of menu entries.
    [[ "${into}" == "${DESKTOP_DIR}" ]] && install -m 644 "${rendered}" "${APPS}/${file}"
    rm -f "${rendered}"
    # GNOME requires desktop launchers to be marked trusted before they run.
    gio set "${dest}" metadata::trusted true 2>/dev/null || true
    echo "    installed $(basename "${into}")/${file}"
}

# --symposium: the demo-day folder only. Four numbered icons in the order they
# get used, kept off the main Desktop so a cluttered background cannot hide the
# one you need while an audience watches.
install_symposium() {
    local dir="${DESKTOP_DIR}/Symposium"
    mkdir -p "${dir}"
    echo "==> Installing the Symposium folder (${dir}) ..."
    chmod +x "${REPO}/deploy/symposium_check.sh" "${REPO}/deploy/symposium_camera.sh"
    install_launcher "symposium-1-check.desktop"    "${dir}"
    install_launcher "symposium-2-feed.desktop"     "${dir}"
    install_launcher "symposium-3-hotspot.desktop"  "${dir}"
    install_launcher "symposium-4-missions.desktop" "${dir}"
    install_launcher "symposium-5-camera.desktop"   "${dir}"
    sed "s|__REPO__|${REPO}|g" "${REPO}/deploy/desktop/symposium-README.md.in" \
        > "${dir}/README.md"
    gio set "${dir}" metadata::trusted true 2>/dev/null || true
    echo
    echo "Done. Open Desktop/Symposium and click '1 · Check everything' first."
    exit 0
}
[[ "${1:-}" == "--symposium" ]] && install_symposium

echo "==> Installing desktop shortcuts for ${REPO} ..."
install_launcher "venator-mission.desktop"
install_launcher "ai-camera-toggle.desktop"
install_launcher "ai-camera-preview.desktop"
install_launcher "ai-camera-stream.desktop"
install_launcher "wifi-hotspot-toggle.desktop"
# Camera 2 (CSI) — only when it is actually fitted: on a laptop, or a Jetson
# with nothing on CAM0, the launcher would be dead weight.
if [[ -e /dev/video0 ]]; then
    install_launcher "wildlife-camera.desktop"
else
    echo "    skipped wildlife-camera.desktop (no /dev/video0 — no CSI camera)"
fi
# Camera 1 (OAK wildlife detector) — needs its own depthai 3.x venv, which is
# separate from the flight tracker's. Skip rather than install a launcher that
# would fail the moment it is clicked.
if [[ -x "${OAK_PY:-/home/jetson/oak-venv/bin/python}" ]]; then
    install_launcher "wildlife-oak.desktop"
    # Field mode drives the same camera, so it shares the depthai requirement.
    # This icon is the manual escape hatch from the boot services: the drone
    # hosts its own Wi-Fi whenever no known network is in range, and this is
    # how an operator gets back to the lab network without a terminal.
    install_launcher "venator-field-mode.desktop"
else
    echo "    skipped wildlife-oak.desktop (no depthai venv at /home/jetson/oak-venv)"
    echo "    skipped venator-field-mode.desktop (same reason)"
fi

# A launcher from before drone/wildlife/ existed; its Exec paths are all dead.
for stale in "${APPS}/imx219-camera.desktop" "${DESKTOP_DIR}/imx219-camera.desktop"; do
    [[ -e "${stale}" ]] && { rm -f "${stale}"; echo "    removed stale $(basename "${stale}")"; }
done
update-desktop-database "${APPS}" 2>/dev/null || true

echo
echo "Done. On your Desktop:"
echo "  - 'Venator Mission' opens the mission menu (loops until you quit)."
echo "  - 'AI Camera (toggle)'  starts/stops the OAK-D tracker (headless)."
echo "  - 'AI Camera (preview)' opens a live window to visually check the camera."
echo "  - 'AI Camera (web stream)' starts the tracker with video for laptop browsers."
echo "  - 'Wi-Fi Hotspot (toggle)' switches between school Wi-Fi and the VenatorDrone hotspot."
[[ -e /dev/video0 ]] && \
echo "  - 'Wildlife Camera (IMX219)' opens the CSI feed; right-click for day/night/snapshot."
[[ -x "${OAK_PY:-/home/jetson/oak-venv/bin/python}" ]] && \
echo "  - 'Wildlife Detector (OAK-D)' detects animals/people with distance; right-click for info/test."
echo
echo "All can also be driven from a terminal:"
echo "  ./drone/camera.sh start | stream | stop | status | restart | preview"
echo "  ./drone/wildlife/imx219_camera.sh 720p | day | night | snapshot   # camera 2"
echo "  ./drone/wildlife/oak_camera.sh detect | info | test | status      # camera 1"
echo "  ./deploy/wifi_mode.sh on | off | toggle | status"
