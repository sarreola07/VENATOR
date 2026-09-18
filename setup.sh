#!/usr/bin/env bash
# One-time setup for the Pixhawk connection test.
# Run with:  bash setup.sh
set -e
cd "$(dirname "$0")"

echo "==> Adding $USER to the 'dialout' group (needed for the serial ports)..."
# Covers the Pixhawk (/dev/ttyACM*) and the LoRa stick (/dev/ttyUSB*) alike,
# once the new group membership takes effect at the next login.
sudo usermod -aG dialout "$USER"

# Grant access right now, before the group takes effect -- but only to ports
# that exist. A bench box or a ground station has no flight controller plugged
# in, and under `set -e` a chmod against a missing device used to abort setup
# before the venv was ever created.
for dev in /dev/ttyACM* /dev/ttyUSB*; do
    [ -e "$dev" ] || continue
    echo "==> Granting immediate access to $dev for this session..."
    sudo setfacl -m "u:$USER:rw" "$dev" 2>/dev/null || sudo chmod a+rw "$dev" || true
done

echo "==> Creating Python virtual environment..."
python3 -m venv venv

echo "==> Installing pymavlink..."
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install -r requirements.txt -q

echo
echo "Done. Run the test with:"
echo "    ./venv/bin/python drone/checks/check_pixhawk.py"
echo
echo "Note: the 'dialout' group membership becomes permanent after you log out"
echo "and back in (or reboot). Until then the setfacl above covers this session."
