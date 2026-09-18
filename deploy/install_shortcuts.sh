#!/usr/bin/env bash
# Install the desktop shortcuts (no sudo, no systemd — user level only):
#   * Hexacopter Mission      — opens the mission menu in a terminal
#   * AI Camera (toggle)      — starts/stops the OAK-D tracker on demand
#   * AI Camera (preview)     — live camera window on the Jetson's screen
#   * AI Camera (web stream)  — tracker + video for laptop browsers
#   * Wi-Fi Hotspot (toggle)  — school Wi-Fi <-> the Jetson's own hotspot
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
    local template="${REPO}/deploy/desktop/${file}.in"
    local dest="${DESKTOP_DIR}/${file}"
    local rendered
    rendered="$(mktemp)"
    sed "s|__REPO__|${REPO}|g" "${template}" > "${rendered}"
    install -m 755 "${rendered}" "${dest}"
    install -m 644 "${rendered}" "${APPS}/${file}"
    rm -f "${rendered}"
    # GNOME requires desktop launchers to be marked trusted before they run.
    gio set "${dest}" metadata::trusted true 2>/dev/null || true
    echo "    installed ${file}"
}

echo "==> Installing desktop shortcuts for ${REPO} ..."
install_launcher "hexacopter-mission.desktop"
install_launcher "ai-camera-toggle.desktop"
install_launcher "ai-camera-preview.desktop"
install_launcher "ai-camera-stream.desktop"
install_launcher "wifi-hotspot-toggle.desktop"
update-desktop-database "${APPS}" 2>/dev/null || true

echo
echo "Done. On your Desktop:"
echo "  - 'Hexacopter Mission' opens the mission menu (loops until you quit)."
echo "  - 'AI Camera (toggle)'  starts/stops the OAK-D tracker (headless)."
echo "  - 'AI Camera (preview)' opens a live window to visually check the camera."
echo "  - 'AI Camera (web stream)' starts the tracker with video for laptop browsers."
echo "  - 'Wi-Fi Hotspot (toggle)' switches between school Wi-Fi and the VenatorDrone hotspot."
echo
echo "Both can also be driven from a terminal:"
echo "  ./drone/camera.sh start | stream | stop | status | restart | preview"
echo "  ./deploy/wifi_mode.sh on | off | toggle | status"
