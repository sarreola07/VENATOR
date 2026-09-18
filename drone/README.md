# drone/ — what runs on the Jetson

The aircraft side: the command link to the ground, the missions that talk to
the Pixhawk, the camera tracker, and the health checks.

| File | What it is |
|---|---|
| `c2_server.py` | The drone end of the LoRa command link. Serves the mission menu, runs what the ground station asks for, and relays PX4's replies. Started at boot by the service in [../deploy/](../deploy/README.md). |
| `missions.py` | The interactive mission menu: motor tests, Mission 1/2, waypoints. |
| `run_missions.sh` | Launcher used by the desktop icon: runs the menu in the repo's venv and holds the terminal open. |
| `camera_publisher.py` | OAK-D person tracker; publishes tracks over UDP and can serve video to a browser. |
| `camera.sh` | Start/stop/preview/stream the tracker. Deliberately not a boot service. |
| `checks/` | Read-only hardware checks: `check_pixhawk.py`, `check_rc.py`, `preflight_audit.py`. |

## Everyday commands

```bash
./venv/bin/python drone/missions.py           # the mission menu
./drone/camera.sh toggle                      # start/stop the tracker
./drone/camera.sh stream                      # tracker + video for a laptop browser
./venv/bin/python drone/checks/check_pixhawk.py   # is the flight controller talking?
```

## Two things want the same ports

The C2 service and `missions.py` both open the Pixhawk, and the C2 service also
holds the LoRa stick. Stop it before running missions or a radio tool by hand:

```bash
sudo systemctl stop venator-c2      # and: sudo systemctl start venator-c2
```

## Safety

Props-off is the default, so motor tests are allowed and flight is refused
until someone deliberately switches mode with
[`../deploy/flight_mode.sh`](../deploy/flight_mode.sh). Nothing arms at boot:
arming only follows a confirmed command that also passes PX4's own pre-arm
checks.
