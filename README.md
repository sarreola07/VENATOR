<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/brand/lockup-dark.svg">
    <img alt="Venator — autonomous flight systems" src="assets/brand/lockup-light.svg" width="360">
  </picture>
</p>

<p align="center">
  <strong>Secure, long-range, off-grid autonomous flight drone platforms powered by edge compute.</strong><br>
  <sub>PX4 v1.13.3 · Jetson Orin Nano · Heltec Wireless Stick V3 · LoRa C2</sub>
</p>

<p align="center">
  <a href="https://github.com/sarreola07/VENATOR/actions/workflows/tests.yml">
    <img alt="Tests" src="https://github.com/sarreola07/VENATOR/actions/workflows/tests.yml/badge.svg">
  </a>
  <a href="https://github.com/sarreola07/VENATOR/actions/workflows/build-gcs.yml">
    <img alt="Ground station build" src="https://github.com/sarreola07/VENATOR/actions/workflows/build-gcs.yml/badge.svg">
  </a>
</p>

<p align="center">
  <a href="https://sarreola07.github.io/VENATOR/"><strong>See it running →</strong></a>
</p>

<p align="center">
  <img alt="A laptop commands the drone over 915 MHz LoRa; it takes off, follows a person at 3 m, and returns home when the link drops" src="assets/brand/conops-light.svg" width="900">
</p>

The ground station sends a command over LoRa, the Jetson runs it against the
flight controller, and the reply comes back the same way. No QGroundControl, no
GUI, no internet — a laptop, a radio and a drone.

## Current hardware setup

| Component | Details |
|---|---|
| Companion computer | NVIDIA Jetson Orin Nano Developer Kit |
| OS | Ubuntu 24.04.4 LTS (L4T R39.2, kernel 6.8 tegra) |
| Flight controller | Pixhawk 2.4.8 (FMUv2, shows as `26ac:0011 3D Robotics PX4 FMU v2.x`) |
| Firmware | PX4 v1.13.3 |
| Connection | USB → `/dev/ttyACM0` (baud rate is ignored on USB CDC) |
| Ground station | None installed (this repo replaces QGC for basic checks) |

Other serial ports available on the Jetson if you later wire TELEM2 to the
40-pin header: `/dev/ttyTHS1` and `/dev/ttyTHS2` (UARTs, typically 57600 or
921600 baud — must match the `SER_TEL2_BAUD` PX4 parameter).

> Reinstalling the Jetson (e.g. moving to NVMe)? The camera environment and
> venvs live outside this repo — see [docs/REINSTALL.md](docs/REINSTALL.md) to
> rebuild everything from a fresh clone.

> Working on the LoRa link from two computers at once (laptop on one end, Jetson
> or a stand-in on the other)? See [docs/DEV_SETUP.md](docs/DEV_SETUP.md) for the
> bring-up order, and `radio/link_test.py` for a scripted two-ended link check.

## Missions (drone/missions.py)

Interactive bench-test program:

```bash
./venv/bin/python drone/missions.py
```

It first asks whether the propellers are removed, then shows a menu that **loops
until you press `q`** — after each mission it returns to the menu so you can run
another. Press `p` to re-declare the props state (to switch between motor tests
and flight without restarting). It offers:

| Mission | What it does | Requires |
|---|---|---|
| 1 | Spins each motor one at a time, 3 s each at 15% throttle | Props **OFF** |
| 2 | Spins all motors together for 3 s at 15% throttle | Props **OFF** |
| 3 | Arms, takes off to 3 ft (0.91 m), hovers, lands, disarms | Props **ON**, GPS position fix, extra `FLY` confirmation |
| 4 | Manual RC flight: switches to Stabilized, arms, then monitors while you fly with the transmitter | Props **ON**, RC link up, extra `FLY` confirmation |
| 5 | Camera tracking display — shows the OAK-D's live person X/Y/Z. No flight. | Tracker started with `drone/camera.sh` |
| 6 | LoRa remote — runs missions from LoRa commands (see table below) | LoRa module on `/dev/ttyUSB0` |

Safety interlocks: motor tests are locked out while props are on, and flight is
locked out while props are off. Ctrl-C sends a disarm in missions 1–3; in
mission 4 it only stops the monitor — the RC pilot keeps control and disarms
with the sticks (throttle low + yaw left).

### Camera + LoRa architecture

Two processes talk over a local UDP socket, which keeps the camera's DepthAI
environment separate from the flight code's venv:

```
OAK-D  --USB-->  drone/camera_publisher.py (depthai-env)  --UDP 127.0.0.1:5005-->  drone/missions.py (venv)
                                                    --HTTP :8080 (stream)-->  laptop browser (optional)
LoRa   --/dev/ttyUSB0 serial-->                                              drone/missions.py (pyserial)
Pixhawk--/dev/ttyACM0 MAVLink-->                                             drone/missions.py (pymavlink)
```

- **`drone/camera_publisher.py`** runs the OAK-D person detector headlessly (in
  `~/oak_drone_project/depthai-env`) and broadcasts the nearest person's
  `{x, y, z, conf}` in metres. It is started/stopped **on demand** via
  `drone/camera.sh` — never at boot. See [drone/README.md](drone/README.md).
- **Option 5** subscribes to that UDP stream and prints live coordinates — pure
  telemetry, never touches the flight controller. (Autonomous *follow-flight* is
  intentionally not wired up on this PX4 vehicle yet; see Notes.)
- **Option 6** turns LoRa packets (`{"msg": "N"}`) into missions, under the **same
  props interlock** you declare at startup:

  | LoRa `msg` | Action | Allowed when |
  |---|---|---|
  | `1` | sequential motor test | props **OFF** |
  | `2` | all-motor test | props **OFF** |
  | `3` | camera display (30 s) | always |
  | `4` | flight: arm / takeoff / land | props **ON** |

  Because a LoRa sender can't type the `FLY` prompt, command `4` flies with **no
  local confirmation** — it is still gated by props-ON and the Pixhawk's own
  pre-arm checks (which currently need a GPS fix). LoRa is **not** auto-started on
  boot; it only runs after you pick option 6.

The mission menu with props off, and the interlock refusing a flight mission
without props:

![missions menu](docs/missions_menu.png)
![safety interlock](docs/safety_lockout.png)

Mission 4 verifying the RC link before flight (aborted at the FLY prompt):

![mission 4 RC check](docs/mission4_rc_check.png)

Notes for this vehicle (PX4 v1.13.3, FMUv2):

- Motor tests use `MAV_CMD_DO_MOTOR_TEST`; the safety switch must be pressed
  (solid LED) and a battery connected, or the FC rejects the command.
- Mission 3 uses PX4's AUTO.TAKEOFF/AUTO.LAND modes. PX4's own preflight and
  arm-time checks must pass before it will arm; when it refuses, the script
  prints the FC's exact reason ("FC says: ...").
- This vehicle is configured as airframe `SYS_AUTOSTART=6001` (DJI F550
  hexarotor), safety switch bypassed (`CBRK_IO_SAFETY=22027`), arming without
  GPS allowed (`COM_ARM_WO_GPS=1`).
- FMUv2 quirk: PX4 v1.13 on this board doesn't run `load_mon`, so the
  "No CPU load information" preflight check fails out of the box. We set
  `COM_CPU_MAX=-1` to disable that check.
