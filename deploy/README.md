# deploy/ — putting it on the Jetson

Installing the boot service and the desktop launchers, and switching the two
modes that change how the drone behaves.

| File | What it is |
|---|---|
| `install_service.sh` | Installs the C2 server as a boot service, so the link comes up on power-on. |
| `install_shortcuts.sh` | Installs the Desktop icons (missions, camera, Wi-Fi hotspot). No sudo. |
| `flight_mode.sh` | Props ON (flight allowed) or props OFF (motor tests only, the default). |
| `wifi_mode.sh` | School Wi-Fi, or the Jetson's own `VenatorDrone` hotspot at 10.42.0.1. |
| `systemd/venator-c2.service.in` | Template for the boot service. |
| `desktop/*.desktop.in` | Templates for the Desktop icons. |

## Install

```bash
bash deploy/install_service.sh --dry-run   # see the unit first, changes nothing
bash deploy/install_service.sh             # install + start (asks for sudo)
bash deploy/install_shortcuts.sh           # Desktop icons (no sudo)
```

The `.in` files are templates: `__REPO__` and `__USER__` are filled in with
wherever this clone actually lives and who is installing it. That is why the
repo works from any folder on any machine — **and why you must re-run both
installers after moving or re-cloning it**, otherwise the launchers and the
service still point at the old path.

## Day-to-day

```bash
sudo systemctl stop venator-c2       # frees the Pixhawk and the LoRa stick
journalctl -u venator-c2 -f          # live logs
./deploy/flight_mode.sh status       # BENCH (props off) or FLIGHT (props on)
./deploy/wifi_mode.sh on             # hotspot; off = rejoin the previous network
```

The hotspot uses the Jetson's only Wi-Fi card, so while it is on the Jetson has
no internet unless Ethernet is plugged in. It defaults to 5 GHz to stay clear of
2.4 GHz RC radios.
