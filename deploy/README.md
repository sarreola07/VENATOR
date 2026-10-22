# deploy/ — putting it on the Jetson

Installing the **three** boot services and the desktop launchers, and switching
the modes that change how the drone behaves.

| File | What it is |
|---|---|
| `install_service.sh` | Installs `venator-c2` — the LoRa command link — as a boot service. |
| `field_mode.sh` | Installs `venator-gui` (camera) + `venator-net-fallback` (hotspot), and the captive portal. Also `on`/`off`/`status`/`url`/`preflight`. |
| `net_fallback.sh` | Run *by* `venator-net-fallback`: waits for a known Wi-Fi, hosts the AP if none appears. Not run by hand. |
| `install_shortcuts.sh` | Installs the Desktop icons. No sudo. |
| `flight_mode.sh` | Props ON (flight allowed) or props OFF (motor tests only). **Props OFF is a drop-in, not the default** — see below. |
| `wifi_mode.sh` | School Wi-Fi, or the Jetson's own `VenatorDrone` hotspot at 10.42.0.1. |
| `systemd/venator-c2.service.in` | Template — the C2 link. |
| `systemd/venator-gui.service.in` | Template — the operator camera GUI (needs `~/oak-venv`). |
| `systemd/venator-net-fallback.service.in` | Template — the boot network decision. |
| `dnsmasq/`, `nft/`, `dispatcher/` | Captive-portal pieces, installed by `field_mode.sh install`. |
| `desktop/*.desktop.in` | Templates for the Desktop icons. |

## Install

```bash
bash deploy/field_mode.sh preflight        # checks 8080, depthai, hotspot profile, nft
bash deploy/field_mode.sh install --dry-run
bash deploy/field_mode.sh install          # camera + hotspot units, enabled for next boot
bash deploy/install_service.sh --dry-run   # see the unit first, changes nothing
bash deploy/install_service.sh             # install + start (asks for sudo)
bash deploy/flight_mode.sh off             # props OFF before anything spins
bash deploy/install_shortcuts.sh           # Desktop icons (no sudo)
```

All three units are `After=local-fs.target`, deliberately **not**
`multi-user.target`: `snapd.seeded.service` stalls that by about two minutes on
this Jetson, so ordering on it would delay the camera and the command link by
the same. They are live a few seconds after power-on instead.

**Two key files, deliberately.** Each unit sets its own `VENATOR_KEY_FILE` —
`~/.venator/gui-key` for the camera, `~/.venator/c2-key` for C2. They used to
share one, which silently muted the handheld remote: creating a key so a phone
could reach the camera also made `radio/serial_link.py` start verifying, and the
remote does not sign. `field_mode.sh preflight` checks the two paths differ.

**Props OFF is not the server's default.** `c2_server.py` defaults to props ON
(`--props-on` is documented in `--help` as "(default)"), and the unit template
passes `--real` alone. `flight_mode.sh off` adds a drop-in that overrides
`ExecStart`; `flight_mode.sh on` works by *deleting* that drop-in, which is why
`--props-off` is not baked into the template. Always check with
`flight_mode.sh status`.

The `.in` files are templates: `__REPO__` and `__USER__` are filled in with
wherever this clone actually lives and who is installing it. That is why the
repo works from any folder on any machine — **and why you must re-run both
installers after moving or re-cloning it**, otherwise the launchers and the
service still point at the old path.

## Day-to-day

```bash
sudo systemctl stop venator-c2       # frees the Pixhawk and the LoRa stick
sudo systemctl stop venator-gui      # frees the OAK and port 8080
journalctl -u venator-c2 -u venator-gui -u venator-net-fallback -f   # live logs
./deploy/flight_mode.sh status       # BENCH (props off) or FLIGHT (props on)
./deploy/field_mode.sh status        # camera + portal + which network it chose
./deploy/field_mode.sh url           # the phone's URL, token included
./deploy/wifi_mode.sh on             # hotspot; off = rejoin the previous network

# After a reboot, the one number that matters: anything above 0 is a restart loop
systemctl show venator-c2  -p NRestarts --value
systemctl show venator-gui -p NRestarts --value
```

The hotspot uses the Jetson's only Wi-Fi card, so while it is on the Jetson has
no internet unless Ethernet is plugged in. It defaults to 5 GHz to stay clear of
2.4 GHz RC radios.
