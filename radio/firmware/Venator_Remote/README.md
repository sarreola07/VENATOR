# Venator handheld remote (Heltec WiFi LoRa 32 V3)

A ground station with no laptop: a Heltec **WiFi LoRa 32 (V3)** with a rotary
encoder and one button, speaking the C2 protocol ([../../../docs/PROTOCOL.md](../../../docs/PROTOCOL.md))
straight to `drone/c2_server.py` over the same 915 MHz link as the Wireless
Stick bridge on the Jetson. The Jetson side is unchanged: it cannot tell this
remote from `ground/gcs_client.py`.

```
  remote (this sketch)  ~~ 915 MHz LoRa ~~  Wireless Stick V3  --USB-->  Jetson: drone/c2_server.py  --USB-->  Pixhawk 6X
                                            (LoRa_Transceiver)
```

## Menu

| Item | Server mission | What happens | The drone refuses unless |
|---|---|---|---|
| Test each motor | `RUN 1` | each motor 3 s at 15%, one after another | props declared **OFF** |
| Test all motors | `RUN 2` | all four together, 3 s at 15% | props declared **OFF** |
| Hover 3 ft | `RUN 8` → `CONFIRM` | takeoff to 0.91 m, hold 10 s, land in place | props declared **ON**, GPS **3D fix**, PX4 pre-arm |
| Drone status | `RUN 7` | GPS / battery / sensor readout | — |

## Controls

| Control | GPIO | Menu | Confirm screens | In flight |
|---|---|---|---|---|
| Knob turn | 1, 2 | choose | — | — |
| Knob click | 3 | select | click = go | **STOP** (land now) |
| Knob **hold 3 s** | 3 | — | **launch** the hover (bar fills) | — |
| BACK button | 4 | re-link / refresh status | cancel | **ABORT** (land now) |

The encoder's `+` is on 3V3. Clockwise runs A/B `11 → 01 → 00 → 10 → 11`, four
transitions per detent. These were found with a pin scan of this remote, not a
schematic. If you rewire, change the `PIN_*` defines at the top of the sketch.

## Commissioning a newly built remote

Hold **BACK** while the board boots to get a five-step setup wizard. It exists
because these are hand-wired: it checks the controls in order and then proves
the radio, so a dead solder joint is found at the bench instead of in the field.

| Step | Asks for | Catches |
|---|---|---|
| 1/5 knob | a click | the encoder's push switch (`PIN_KNOB`) |
| 2/5 turn | three detents **clockwise** | a dead or unconnected A/B channel |
| 3/5 turn | three detents **anticlockwise** | **A and B swapped** — see below |
| 4/5 BACK | a press of BACK | `PIN_BACK` wired, and not swapped with the knob |
| 5/5 radio | nothing | sends `HELLO` until the drone answers; shows the RSSI |

Steps 2 and 3 are the point. On a hand-soldered KY-040, A and B end up swapped
about half the time, which inverts the knob — the menu scrolls the wrong way and
nothing in the code is wrong. If clockwise counts *down* and anticlockwise counts
*up*, the wizard records that in NVS (`venator/encInvert`) and `takeDetents()`
negates from then on, so the unit works without a resolder or a per-unit build.
Any other combination means a channel is stuck, which inverting would only
hide, so it says `CHECK WIRING` and changes nothing.

The wizard **cannot change the radio parameters**. `RF_FREQUENCY`, `LORA_SF` and
`LORA_SYNCWORD` must stay identical to `LoRa_Transceiver.ino` or the two ends go
deaf, so step 5 verifies the link rather than offering to edit it. BACK leaves
the wizard at any step. Booting without BACK held skips it entirely, so a remote
that is already flying behaves exactly as before.

## Safety, and where it lives

The **drone** decides. The props interlock, the GPS gate and PX4's own pre-arm
checks are all in `drone/c2_server.py` and PX4. The remote cannot get around them.
It adds three things of its own:

- a local "Spin motors?" / "Hover 3 ft?" confirm before it sends anything;
- the hover launches only on a **3 s hold**, and only after the drone has
  accepted it (`ACK confirm_required`). A cancel or 45 s of nothing sends
  `ABORT`, which drops the prepared flight on the drone. The drone also lets an
  unconfirmed flight lapse after 60 s by itself (`PENDING_CONFIRM_S`).
- in flight it pings every second. If the drone hears nothing for 4 s it
  **lands in place**. The hover never uses RTL, because on this vehicle RTL
  first climbs to `RTL_DESCEND_ALT` (10 m).

It never retries a `RUN`: the server does not dedupe them, so a resend could
run a motor test twice. "No answer from the drone" therefore means
*unknown*, not *didn't run*. Look at the drone.

**Power this remote or the Pico gateway, never both.** The Pico + RYLR998
([../Pico_Gateway/README.md](../Pico_Gateway/README.md)) needs a 5-byte header
on every packet, and `LoRa_Transceiver` adds one or not based on a single flag
set by whichever packet it heard last. With both remotes live, every reply that
follows the Pico's transmission arrives here with five binary bytes before the
`{`, fails to parse, and is dropped — with no error shown at either end. Given
the paragraph above, that is the bad case: a lost `DONE` is indistinguishable
from a motor test that never ran. Why, and the fix it would take:
[One remote at a time](../README.md#one-remote-at-a-time).

**Not authenticated.** The remote does not sign messages (`radio/auth.py`), so
the server must run without `~/.venator/key` while you use it. Anything in
radio range that speaks this protocol can command the aircraft. See
[../../../docs/SECURITY.md](../../../docs/SECURITY.md).

**3 ft on a barometer.** No downward lidar is fitted yet, and `EKF2_HGT_REF=2`
(range sensor) falls back to the baro, so expect tens of centimetres of height
drift at 0.91 m. Fly it in the open, with the RC transmitter's kill switch
(`RC_MAP_KILL_SW = 5`) in hand.

## Flash it

The sketch is for the **WiFi LoRa 32 (V3)** (128x64 OLED). It is a different
board from the Wireless Stick V3 that `LoRa_Transceiver` targets. Same Heltec
ESP32 board package and Dev-Boards library, same 230400 upload speed.

```bash
FQBN=Heltec-esp32:esp32:heltec_wifi_lora_32_V3
arduino-cli compile --fqbn $FQBN --output-dir /tmp/venator-remote radio/firmware/Venator_Remote
arduino-cli upload  --fqbn $FQBN --board-options UploadSpeed=230400 \
    --port /dev/cu.usbserial-XXXX --input-dir /tmp/venator-remote radio/firmware/Venator_Remote
```

Over USB it logs every packet as `TX {...}` / `RX {...}` at 115200 baud, which
is the quickest way to see which end went quiet. The remote does not need USB
to run: any 5 V USB supply or the Heltec's LiPo connector powers it.

## Bring-up on the Jetson

Do the steps in order. The first two need no motors.

1. **Free the stick.** The boot service holds the LoRa port, and it runs with
   props **ON** (`--real` only; the server's default), not OFF as its comment says:

   ```bash
   sudo systemctl stop venator-c2.service
   ```

2. **Radio + protocol, mock FC.** With the remote powered:

   ```bash
   ./venv/bin/python drone/c2_server.py --props-off
   ```

   The remote's header should go from `no link yet` to `LINK -NNdB`, showing
   `props OFF`. "Test all motors" should end `DONE ok (mock)`, and "Hover 3 ft"
   should be `REFUSED: props are OFF`.

3. **Real Pixhawk, props OFF, battery in.** Same, plus `--real`:

   ```bash
   ./venv/bin/python drone/c2_server.py --real --props-off
   ```

   "Test each motor" spins 1 → 4 for 3 s each, and "Test all motors" spins all
   four for 3 s. If the remote says `DONE` but nothing turned, PX4 accepted
   `MAV_CMD_DO_MOTOR_TEST` without driving the outputs. Check the server log
   for "FC says:" and try QGroundControl's motor slider, which uses
   `MAV_CMD_ACTUATOR_TEST`.

4. **Hover, props ON, outdoors.** Only with props fitted, a GPS 3D fix (the
   remote's "Drone status" says `gps 3D/…`) and the kill switch in hand:

   ```bash
   ./venv/bin/python drone/c2_server.py --real --props-on
   ```
