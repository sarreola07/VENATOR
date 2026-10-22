# Rebuilding on a fresh Jetson (after NVMe / JetPack reinstall)

This repo does **not** contain the camera environment or the Python virtualenvs —
they live outside it and are lost when the Jetson is wiped. Follow these steps on
the fresh install to get everything working again.

## What survives the wipe vs. what you rebuild

| Item | Survives? | Notes |
|---|---|---|
| `VENATOR` repo | ✅ on GitHub | `git clone` it back |
| PX4 parameters (`COM_CPU_MAX=-1`, `EKF2_AID_MASK=1`, airframe) | ❌ | Must be set again on the new Pixhawk 6X; airframe must be re-selected as a quadcopter in QGroundControl |
| Mission venv (`venv/`) | ❌ rebuild | `setup.sh` recreates it |
| Flight-tracker camera env (`~/oak_drone_project/`, 588 MB) | ❌ rebuild | §2 — depthai **2.32** |
| Wildlife/GUI camera env (`~/oak-venv`) | ❌ rebuild | §2b — depthai **3.10**, and `venator-gui.service` cannot start without it |
| OAK-D udev rule (`80-movidius.rules`) | ❌ rebuild | steps below |
| `hexacopter-follow/` | ✅ its own remote | re-clone (optional) — someone else's repo, named for a different aircraft |

## 1. Clone the project and build the mission venv

```bash
git clone https://github.com/sarreola07/VENATOR.git ~/Desktop/VENATOR
cd ~/Desktop/VENATOR
bash setup.sh          # venv + pymavlink + pyserial + dialout access
./venv/bin/pip install pillow   # only needed if you regenerate the icons
```

> The clone path matters. `deploy/*.in` templates bake `__REPO__` in at install
> time, so the installers must be re-run after a move — and this document used
> to clone to `~/Desktop/pixhawk-test`, the pre-rename path, which no longer
> matches anything on the machine.

## 2. Rebuild the flight-tracker camera environment (depthai 2.32)

```bash
mkdir -p ~/oak_drone_project && cd ~/oak_drone_project
git clone https://github.com/luxonis/depthai-python.git
python3 -m venv depthai-env
./depthai-env/bin/pip install --upgrade pip
./depthai-env/bin/pip install depthai==2.32.0.0 opencv-python==4.13.0.92 numpy==2.5.1

# Download the example model blobs (incl. mobilenet-ssd person detector)
cd depthai-python/examples
../../depthai-env/bin/python install_requirements.py
```

Confirm the blob `drone/camera_publisher.py` expects now exists:
`~/oak_drone_project/depthai-python/examples/models/mobilenet-ssd_openvino_2021.4_6shave.blob`

## 2b. Rebuild the wildlife / operator-GUI environment (depthai 3.10)

**Two camera venvs, on purpose.** `drone/wildlife/*` (including
`gui_server.py`, which `venator-gui.service` runs) needs depthai **3.10** in
`~/oak-venv`; the flight tracker in §2 needs depthai **2.32**. The APIs are
incompatible and neither script runs in the other's interpreter. Skipping this
section leaves a Jetson where the camera boot service can never start — and
because the unit now carries
`ConditionFileIsExecutable=/home/jetson/oak-venv/bin/python`, systemd **skips it
silently** rather than erroring, so the camera is simply absent with nothing in
`systemctl --failed` to say why.

Note `--system-site-packages`: this venv inherits JetPack's system packages, and
rebuilding it plain will break it.

```bash
python3 -m venv --system-site-packages ~/oak-venv
~/oak-venv/bin/pip install --upgrade pip
~/oak-venv/bin/pip install 'depthai==3.10.*'
mkdir -p ~/oak-venv/zoo-cache      # DEPTHAI_ZOO_CACHE_PATH; models fetch at runtime
```

Verify both, and that they really are different:

```bash
~/oak-venv/bin/python            -c 'import depthai; print("oak-venv ", depthai.__version__)'   # 3.10.x
~/oak_drone_project/depthai-env/bin/python -c 'import depthai; print("depthai-env", depthai.__version__)'  # 2.32.x
```

## 3. OAK-D udev rule (non-root USB access)

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="03e7", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/80-movidius.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Verify the camera is seen:
```bash
~/oak_drone_project/depthai-env/bin/python - <<'PY'
import depthai as dai
print([d.getMxId() for d in dai.Device.getAllAvailableDevices()])
PY
```

## 4. Desktop shortcuts

```bash
cd ~/Desktop/VENATOR && bash deploy/install_shortcuts.sh
```

Installs the Desktop icons at user level, no sudo: Venator Mission, AI Camera
(toggle / preview / web stream), Wi-Fi Hotspot (toggle), and — when the hardware
or interpreter they need is present — Wildlife Camera (needs `/dev/video0`),
Wildlife Detector and Venator Field Mode (both need `~/oak-venv`, §2b). The
conditional ones print a "skipped" line rather than installing an icon that
cannot work.

## 4b. Boot services — the part that makes it start by itself

Nothing above makes anything start at power-on. Three units do that, and they
are installed by two different scripts:

```bash
cd ~/Desktop/VENATOR
bash deploy/field_mode.sh preflight          # checks 8080, depthai, hotspot profile, nft
bash deploy/field_mode.sh install            # venator-gui + venator-net-fallback
bash deploy/install_service.sh               # venator-c2
bash deploy/flight_mode.sh off               # props OFF: motor tests only, flight refused
```

`field_mode.sh install` enables but does not start — they come up on the next
boot. All three are `After=local-fs.target`, not `multi-user.target`, because
`snapd.seeded.service` stalls that by about two minutes on this Jetson; the
camera and C2 server are live a few seconds after power-on.

The hotspot profile itself is **not** created by any of this, on purpose — a
boot unit must never invent a Wi-Fi password:

```bash
HOTSPOT_PASSWORD='<8-63 chars>' ./deploy/wifi_mode.sh on   # creates venator-hotspot, 5 GHz
```

Check it took with `systemctl is-enabled venator-gui venator-net-fallback
venator-c2` and, after a reboot, `systemctl show venator-c2 -p NRestarts
--value` — anything above `0` means something is restart-looping.

## 5. (Optional) the classmates' ArduPilot SITL project

```bash
git clone https://github.com/robertonava08/hexacopter-follow.git \
  ~/Desktop/VENATOR/hexacopter-follow
```

It is git-ignored by this repo, so it stays a separate checkout.

## Sanity check

```bash
cd ~/Desktop/VENATOR
./venv/bin/python drone/checks/check_pixhawk.py     # MAVLink link to the Pixhawk
./drone/camera.sh start && sleep 10 && ./drone/camera.sh status && ./drone/camera.sh stop
```
