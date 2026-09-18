#!/usr/bin/env bash
# Install the Venator C2 server as a boot service — the Jetson then starts the
# LoRa command link automatically on power-on (zero-touch). Asks for sudo once.
#
#   bash deploy/install_service.sh              # install and start it
#   bash deploy/install_service.sh --dry-run    # print the unit, change nothing
#
# systemd/venator-c2.service.in is a template: __REPO__ and __USER__ are filled
# in from this clone's location and the user running it, so the repo works from
# any folder on any machine. Re-run this after moving or re-cloning the repo.
#
# The service runs the server with --real (connects the Pixhawk) and props OFF,
# so remotely only motor tests / camera run; flight stays gated. Nothing arms on
# boot. Stop it (below) when you want to use drone/missions.py interactively,
# since both want the Pixhawk serial port.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SVC="venator-c2.service"
UNIT="$(mktemp)"
trap 'rm -f "${UNIT}"' EXIT

sed -e "s|__REPO__|${REPO}|g" -e "s|__USER__|${USER}|g" \
    "${REPO}/deploy/systemd/${SVC}.in" > "${UNIT}"

if [[ "${1:-}" == "--dry-run" ]]; then
    echo "==> ${SVC} as it would be installed (nothing was changed):"
    echo
    cat "${UNIT}"
    exit 0
fi

[[ -x "${REPO}/venv/bin/python" ]] || { echo "Missing venv — run: bash setup.sh"; exit 1; }

echo "==> Installing ${SVC} for ${REPO} (user ${USER}) ..."
sudo install -m 644 "${UNIT}" "/etc/systemd/system/${SVC}"
sudo systemctl daemon-reload
sudo systemctl enable "${SVC}"
sudo systemctl restart "${SVC}"
sleep 2
echo
sudo systemctl --no-pager --lines=8 status "${SVC}" || true

echo
echo "Done — the C2 server starts on every boot."
echo "  live logs : journalctl -u ${SVC} -f"
echo "  stop      : sudo systemctl stop ${SVC}      (frees the Pixhawk and the LoRa stick)"
echo "  start     : sudo systemctl start ${SVC}"
echo "  disable   : sudo systemctl disable ${SVC}"
