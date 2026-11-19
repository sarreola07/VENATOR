# Venator roadmap

End goal: command the drone from any laptop over LoRa, with **zero interaction on
the Jetson**, including a "fly to these coordinates" mission.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../assets/brand/avoid-dark.svg">
    <img alt="Forward obstacle avoidance: the depth camera finds a wall, PX4 brakes at CP_DIST, the aircraft routes around and rejoins" src="../assets/brand/avoid-light.svg" width="900">
  </picture>
</p>

The furthest thing on this list, and it works: the aircraft deviates around
what the OAK-D sees ahead and rejoins its line. The code that does it runs on
the Jetson and is **not in this repo yet** (see the note under the Status
table), so `run_mission2` here still steers toward a person and otherwise hovers
in place.

The plan was to join two ends that already existed. `drone/camera_publisher.py`
runs a `MobileNetSpatialDetectionNetwork` on the OAK-D's stereo depth, so
forward distance is a matter of reading the depth map rather than the
detections, and PX4 accepts `OBSTACLE_DISTANCE` from a companion computer and
brakes against it with `CP_DIST`.

Mission 2 as designed — the goal this is all pointed at — is on the
[landing page](https://sarreola07.github.io/VENATOR/).

## Status

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../assets/brand/phases-dark.svg">
    <img alt="Phase status: all seven phases, 0 to 6, done" src="../assets/brand/phases-light.svg" width="900">
  </picture>
</p>

| Phase | What | State |
|---|---|---|
| 0 | NVMe install + restore project (see [REINSTALL.md](REINSTALL.md)) | ✅ done |
| 1 | C2 protocol ([PROTOCOL.md](PROTOCOL.md), `radio/protocol.py`) | ✅ done |
| 2 | Portable laptop client + mock + CI to build `.exe`/`.app` | ✅ done |
| 3 | Bidirectional Heltec firmware (half-duplex transceiver) | ✅ flashed + validated on real radios; OLED status on both sticks. Also strips/adds the RYLR998's 5-byte header so the Pico gateway interoperates |
| 3b | Handheld LoRa remote (`radio/firmware/Venator_Remote`) | ✅ motor tests + props refusal verified on the real aircraft; setup wizard compiles, not yet flashed |
| 3c | Pico + RYLR998 gateway (`radio/firmware/Pico_Gateway`) | 🔵 talks to the drone; framing is last-peer-wins, so do not power it alongside the Heltec remote |
| 4 | Jetson C2 server + systemd boot service (zero-touch) | ✅ **motors spun on the real aircraft from the handheld remote, 2026-10-21** — this needed `MAV_CMD_ACTUATOR_TEST`; `DO_MOTOR_TEST` is ArduPilot-only and PX4 answered it UNSUPPORTED, so nothing had ever actually turned through this path |
| 4b | Boot services for camera + hotspot + C2 (`field_mode.sh`) | ✅ units, key split and crash-loop guards; **verified across a reboot with hardware attached** |
| 5 | GPS + waypoint flight | ✅ **the M10 has a fix and the waypoint mission has flown outdoors**: upload + flight trigger + two-step arm + link-loss RTL. The M10 fault behind PX4's `fix_type 0`, 0 sats (with `GPS_1_CONFIG=201`) is fixed |
| — | Mission 1: hover + detect people + land | ✅ flown outdoors: hover at a true 3 ft on the downward lidar (`EKF2_HGT_REF=2`), person detection over LoRa, land |
| — | Vest search: find the person in the yellow construction vest, ignore the decoys (`drone/wildlife/vest.py`) | ✅ colour check, vote and lock, switched on, calibrated and recorded from the operator's page; run on the real OAK-D and Jetson. Nothing in this repo commands the aircraft from it, and a yellow shirt fools it: it matches a description |
| — | Mission 2: follow the person until LoRa STOP | ✅ flown on the real aircraft; OFFBOARD velocity follow (keep 3 m), STOP->land, camera-loss->hover, link-loss->RTL |
| 6 | Polish: auto-launch agents, saved "places", browser GUI, OFFBOARD follow | ✅ done |
| 6 | Forward obstacle avoidance — deviate around what the OAK-D sees | ✅ done |

> **The site shows the finished system, and as of 2026-11-18 this table agrees
> with it.** The search and rescue banner on [how-it-works][site] — fence,
> coverage path, a real-time reroute around a tree, a deer logged, a casualty
> found and an emergency sent — is what the aircraft does. The one row still in
> progress, the Pico gateway (3c), is not on the site. What still differs is
> **this repo**: forward obstacle avoidance, posture detection (here
> `camera_publisher.py` still finds people by depth), saved places, the launch
> agents and Mission 1's 3 ft hover (here `drone/c2_server.py` still has
> `HOVER_ALT_M = 2.0`) run on the aircraft, but their code has not been pushed.
> Until it is, this table describes the aircraft, not the code in this repo.

[site]: https://sarreola07.github.io/VENATOR/how-it-works.html

## Phase details

- **1 — Protocol** *(done):* versioned, newline-JSON messages; handshake, menu,
  run, waypoint upload, ACK/retransmit. Shared by client and Jetson server.
- **2 — Client** *(done):* `ground/gcs_client.py` auto-detects the Heltec
  (CP210x VID), handshakes, renders the Jetson's menu, uploads waypoints. Runs
  today with `--mock` (no hardware). The GitHub Actions workflow builds
  `VenatorGCS.exe` and `.app` — download from the run's Artifacts.
- **3 — Firmware:** merge the two working sketches into one half-duplex
  transceiver (transparent line bridge, same 915 MHz/SF7/syncword). Flash both
  sticks.
- **4 — Jetson server** *(done):* `drone/c2_server.py` owns the LoRa
  serial and the Pixhawk; serves the menu, runs missions (reusing `drone/missions.py`),
  streams ACK/DONE. Defaults to a **mock FC** (`--real` connects the Pixhawk) but props default **ON**; `--real`
  connects the Pixhawk, `--props-on` enables flight. Tested end-to-end against the
  real client over a loopback — props + GPS gates verified.
  `deploy/systemd/venator-c2.service.in` is the template for the zero-touch boot
  unit (enable deliberately). The two-step arm confirm, the link-loss failsafe
  (`LINK_LOSS_S = 4.0` → RTL) and mid-mission `ABORT` are all in place: the
  mission loops poll the link while flying instead of blocking, so aborts and
  heartbeats are handled promptly. Since 2026-10-21 `confirm()` also **re-checks**
  props and GPS at launch time, not just when the flight was prepared — props can
  be toggled inside the 60 s confirm window, and on an unauthenticated link
  anything in radio range can inject that toggle.
  **The one exception is closed (2026-11-06):** a RUN for menu id 3 ("Fly to
  waypoints") used to skip `_prepare`/`CONFIRM` and go straight to
  `missions.mission_3(..., require_confirm=False)`, arming after a 3 s sleep. It
  is now refused: the waypoint flight goes upload → `FLY_REQ` → `CONFIRM`, as the
  laptop client always sent it, and `mission_3` always asks for FLY at the
  keyboard. The same change made an error mid-flight trigger that flight's
  failsafe (it used to kill the server), and made STOP land an armed drone the
  server isn't flying, as after a restart mid-flight.
- **5 — Waypoint flight** *(done):* flown outdoors on the Holybro M10
  (`GPS_1_CONFIG=201`): upload via `MISSION_ITEM_INT` → `AUTO.MISSION`, altitude
  cap + RTL-last. It was blocked for a while on PX4 reporting `fix_type 0` with
  0 satellites and `XY_POSITION_CONTROL` unhealthy, an M10 hardware fault rather
  than configuration; that is fixed.
- **6 — Polish** *(done):* zero-click launch agents on your own Win/Mac, a saved
  places library, a browser GUI, and the OFFBOARD-mode camera-follow port. The
  browser GUI ([OPERATOR_GUI.md](OPERATOR_GUI.md)) and the OFFBOARD follow
  (Mission 2) are in this repo; the launch agents and saved places are not yet.
- **6 — Obstacle avoidance** *(done):* the aircraft deviates around what the
  OAK-D sees ahead, which is the real-time reroute the how-it-works banner
  shows. The code is on the Jetson and not in this repo yet. The plan it started
  from: forward distance from the OAK-D's stereo depth map, which
  `drone/camera_publisher.py` already computes for its
  `MobileNetSpatialDetectionNetwork`, sent to PX4 as `OBSTACLE_DISTANCE` /
  `DISTANCE_SENSOR` and braked against with `CP_DIST`.

## Open decisions (needed by Phase 4/5)

1. Link-loss during flight: RTL or land-in-place? (default: RTL)
2. Geofence radius + altitude cap.
3. Coordinates: free-typed, saved "places", or both?
4. Client UI: CLI now, browser GUI later.
5. **Message addressing** — see below. Blocks putting a third radio on the link,
   and is the same gap that leaves the command link unauthenticated. See
   [SECURITY.md](SECURITY.md).

## A third radio: what it takes

LoRa is a broadcast medium, so a third stick on 915 MHz / SF7 / syncword 0x12
hears every packet with no firmware change at all. The radio layer is free. What
is not free is that nothing in the protocol says who a message is *from* or *to*.
Two consequences, the second of which matters before the drone flies.

**Delivery confirmation stops being honest.** `radio/phone_relay.py` ACKs every LOG it
hears, unconditionally, before its own dedup check. With two peers instead of
one, both hear a message at the same instant and both transmit an ACK
immediately -- those two ACKs collide on air and cancel each other out. The
`MIN_SEND_GAP_S` pacing in `radio.link_test.Link` is per-node and knows nothing about
what other nodes are doing. The likely result is that both peers display the
message correctly while the sender shows "not confirmed", i.e. the confirmation
gets less trustworthy as the network grows. And an ACK that does survive only
proves *someone* received it: the second ACK for the same id hits
`pending.pop(...) -> None` and is silently discarded.

Fix shape, roughly 30 lines: carry a `from` (node name) on LOG and ACK; have the
sender wait for ACKs from N-1 distinct peers before reporting delivered, showing
partial state ("1 of 2") rather than a bare tick; and give each node a
deterministic ACK delay derived from its name so the replies do not overlap.

**Command authority is not divisible today.** `drone/c2_server.py` keeps a
single server-level `self._pending` -- it is not per-client. RUN sets it and
CONFIRM consumes it, with no record of which station sent either. On a
broadcast channel with three radios and no sender identity, one station's RUN
can be completed by a *different* station's CONFIRM, and neither operator would
see that the two halves came from different people. The two-step arm gate exists
precisely so nobody launches a quadcopter by accident, and with a third radio
present it quietly stops being a two-step gate.

So: chat is the safe place to get addressing right. Add `from` before a third
radio goes anywhere near the flight link, and make the arm gate remember which
station armed it.
