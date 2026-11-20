# ARK Flow Sensor Setup for Indoor Hovering

## Overview

VENATOR can hover indoors using the ARK Flow sensor (optical flow + distance measurement) for position control without GPS. This document explains how to validate and use this capability.

## Hardware Requirements

- **ARK Flow sensor** (DroneCAN/UAVCAN interface on Pixhawk)
- **Optical textured surface** (matte floor or patterned surface)
- **Adequate lighting** (the sensor needs to see texture)

## PX4 Configuration

The following parameters must be set on the Pixhawk for ARK to work:

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `UAVCAN_ENABLE` | 2+ | Enable DroneCAN |
| `UAVCAN_SUB_FLOW` | 1 | Subscribe to ARK optical flow |
| `UAVCAN_SUB_RNG` | 1 | Subscribe to ARK distance sensor |
| `EKF2_OF_CTRL` | 1 | Use optical flow for position |
| `EKF2_RNG_CTRL` | 1+ | Use distance sensor for height |
| `EKF2_HGT_REF` | 2 | Height reference = distance sensor |
| `EKF2_GPS_CTRL` | 0 | Disable GPS (indoor) |
| `COM_ARM_WO_GPS` | 1 | Allow arming without GPS fix |

## Validating ARK Sensor

### Option 1: Standalone Validation (Jetson)

Stop the C2 server, then run the validator:

```bash
sudo systemctl stop venator-c2
cd /home/jetson/Desktop/VENATOR
./venv/bin/python drone/ark_setup.py
```

**During the check:**
- Keep props OFF
- When prompted (~5 seconds in), lift the drone about 0.5 m over a textured floor
- Hold it there for about 5 seconds, then lower it
- The validator will report ARK readiness

**Expected output:** All checks should show `[OK]` or `[INFO]`

After validation, restart the C2 server:

```bash
sudo systemctl start venator-c2
```

### Option 2: Remote Validation via LoRa (Ground Station)

From your ground station laptop:

```bash
cd path/to/VENATOR
python ground/ark_ground_app.py --check --port /dev/ttyUSB0
```

This will:
1. Connect to the drone via LoRa
2. Run the ARK validation on the Jetson
3. Display results showing sensor health and position tracking

### Option 3: Through the C2 Menu

Pick **ARK check** on the handheld remote, or send `RUN 9` over the LoRa
protocol. The ground app does this with `--check`. Mission ids are ints: the
remote's menu is `struct Item { int id; ... }`, so a string id could never be
sent from it.

## Triggering the Hover Mission

Once ARK is validated as ready:

```bash
python ground/ark_ground_app.py --hover --port /dev/ttyUSB0
```

This will:
1. Validate ARK sensor
2. If ready, trigger the hover mission
3. Ask **you** to type `FLY` before it sends CONFIRM (two-step arm safety — the
   script will not confirm its own RUN, and a piped/non-interactive run never
   launches)
4. Monitor the flight (takeoff → 4 ft → hold 10s → land)

## Troubleshooting

### "OPTICAL_FLOW_RAD: quality 0"
- Lens is covered or dirty → clean the sensor
- Lighting is too dim → add light or move to brighter area
- Floor is too shiny with no texture → use a mat or add tape pattern

### "OPTICAL_FLOW_RAD: quality < 100"
- Floor texture is too subtle → add tape pattern or use a mat
- Not enough light → turn on overhead lights or move to window

### "DISTANCE_SENSOR: flat"
- Drone was not lifted during validation → run again and lift it ~0.5 m

### "LOCAL_POSITION_NED: nothing"
- EKF2_OF_CTRL might be 0 → check parameters
- ARK sensor not connected → check DroneCAN wiring
- PX4 not talking to ARK → check UAVCAN_SUB_FLOW and UAVCAN_SUB_RNG

### "Horizontal position: not trusted by EKF"
- EKF2 is still initializing → wait a few seconds
- Drone was stationary during check → move it sideways while validating

## Flight Notes

- Hover altitude: **4 feet (1.22 m)** — `HOVER4_ALT_M` in `drone/c2_server.py`
- Hold time: **10 seconds** — plenty for initial testing
- Failsafe: **LAND in place** — not RTL (on this vehicle RTL first climbs to
  `RTL_DESCEND_ALT`, 10 m, which is the opposite of what a 4 ft test wants)
- Link loss: **4 seconds** → auto-land in place
- Climb timeout: **20 seconds** → lands rather than waiting
- Optical flow quality varies with floor texture and lighting

## Mission Details

**Mission ID: 8** ("Hover 4 ft, then land")
- Requires props ON
- Requires a **position estimate**, which is either a GPS 3D fix or a local
  position PX4 trusts (`POS_HORIZ_REL` and `POS_VERT_AGL` in
  `ESTIMATOR_STATUS`). Indoors on the ARK Flow the second is the only one
  available — a GPS fix is never coming. Missions that fly to a *coordinate*
  (3, 4, 5) still demand satellites.
- Takes off to 4 feet
- Holds altitude for 10 seconds
- Lands in place (not RTL)
- STOP command lands early
- ABORT lands immediately

**Mission ID: 9** ("ARK sensor check")
- Requires props **OFF** — you handle the aircraft during it
- Reads the parameters above, then watches the sensor for 10 s. Wait for the
  `LIFT the drone` message before picking it up: the parameter reads come first.
- Runs on the C2 server's own MAVLink connection, so `venator-c2` stays up

