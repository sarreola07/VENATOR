# drone/wildlife/ — the two wildlife cameras

Animal and human detection for field work. Two cameras that cover for each
other: the OAK-D-S2 sees in daylight and measures distance, the CSI camera sees
in the dark.

| Camera | Sensor | Role |
|---|---|---|
| **Camera 1** — OAK-D-S2 | IMX378 + 2× OV9282 | Daytime detection with stereo depth. Inference runs on its own VPU. |
| **Camera 2** — IMX219-160 IR-CUT | IMX219 on CAM0 | 160° FOV, colour by day, black and white at night, IR-sensitive. |

This is separate from [`../camera_publisher.py`](../README.md), the flight
person-tracker. That one stays on depthai 2.32 in
`~/oak_drone_project/depthai-env`; the wildlife code here uses depthai 3.10 in
`~/oak-venv`. The two APIs are incompatible, so keep the interpreters straight.

| File | What it is |
|---|---|
| `imx219_feed.py` | Camera 2. Live window or numpy frames, with day/night switching and the 180° invert. No OpenCV needed. |
| `ircut.py` | Day/night control of the IR-CUT optical filter over GPIO. |
| `imx219_camera.sh` | Launcher used by the desktop icon: `720p`, `1080p`, `day`, `night`, `snapshot`. Refuses to open a second capture. |
| `oak_camera.sh` | Launcher for camera 1: `detect`, `info`, `test`, `images`, `classes`, `status`. Refuses to start if something else owns the OAK. |
| `oak_wildlife.py` | Camera 1. Spatial animal/person detection with a distance per hit; saves annotated evidence frames. |
| `oak_info.py` | Identifies the OAK, its fitted sensors and whether it has IR illumination. |
| `oak_test.py` | Proves the OAK streams colour and stereo depth. |
| `test_detector.py` | Runs the detector over image files, so you can check what it sees before flying it. |
| `setup_cam0.sh` | One-time device-tree overlay enable for CAM0. Needs sudo; dry-run by default. |
| `checks/` | `check_camera.sh` (8-point camera health), `system_check.sh` (whole box), `diagnose.sh` (GUI wrapper). |
| `config/` | Known-good boot config and checksums — see [Recovery](#recovery). |

## Everyday commands

Each camera has one executable; neither needs you to remember which interpreter
to use.

```bash
# camera 2 — CSI
./drone/wildlife/imx219_camera.sh            # feed, auto day/night
./drone/wildlife/imx219_camera.sh night      # force black and white
./drone/wildlife/imx219_camera.sh snapshot   # full-res still into ~/Pictures

# camera 1 — OAK-D
./drone/wildlife/oak_camera.sh               # detect, with distance
./drone/wildlife/oak_camera.sh info          # what OAK is this?
./drone/wildlife/oak_camera.sh status        # who currently owns the device?
./drone/wildlife/oak_camera.sh images ~/Pictures/testset/   # test on photos

# health
./drone/wildlife/checks/check_camera.sh      # is camera 2 healthy?
./drone/wildlife/checks/system_check.sh      # is anything else wrong?
```

Desktop icons for both are installed by `bash deploy/install_shortcuts.sh`:
**Wildlife Camera (IMX219)** and **Wildlife Detector (OAK-D)**. Right-click
either for day/night, snapshot, device info and health actions.

The OAK allows exactly one host process, and the flight person-tracker wants it
too. `oak_camera.sh` checks first and tells you who has it, rather than failing
with a device error twenty seconds in.

## Day and night

| | Colour | ISP saturation | IR-CUT filter |
|---|---|---|---|
| **day** | normal colour | 1.0 | ON — blocks IR |
| **night** | black and white | 0.0 | OFF — IR passes |

Both are hardware paths. `saturation` is an `nvarguscamerasrc` property applied
inside the ISP, so greyscale is free — no GRAY8 conversion, no CPU
`videobalance`. The 180° invert is `nvvidconv flip-method=2`, which runs on the
VIC. Measured cost of all of it: **55 fps at 640×360**, slightly *faster* than
before the flip and metering branch were added.

Greyscale at night is not cosmetic. With the IR-CUT filter removed the Bayer
colour filters see infrared, producing a heavy magenta cast that carries no real
colour information. Dropping chroma gives a cleaner image that compresses better.

### Switching is on a clock, not on the image

`--daynight schedule` is the default: sunrise/sunset at `--lat`/`--lon`
(defaults to Austin), using −6° civil twilight. It cannot be fooled by
auto-exposure, headlights, or a camera pointed at the ground.

`--daynight auto` (metering the image) **does not work on this camera** and is
kept only for hand testing. Measured in a pitch-dark room:

```
meter mean = 101.5      night threshold was 40
```

Argus auto-exposure raises analog gain up to 10.6× until the scene averages to
a "correct" exposure, so mean luma sits near mid-grey however dark it really is.
No threshold separates day from night through AE — raising it above 101 would
just report night at midday.

### Night mode needs an IR light source

Removing the IR-CUT filter makes the sensor **able to see** infrared. It does
not **produce** infrared. In a dark room with no IR source, an IR-sensitive
camera sees exactly what a normal one does: nothing. Measured:

| Mode | mean luma | std dev | JPEG |
|---|---|---|---|
| day (colour) | 37.6 | 0.5 | 4 KB |
| night (B&W) | 36.6 | 0.5 | 4 KB |

Identical blank frames — a std of 0.5/255 is amplified sensor noise, not an
image. The Waveshare kit's **IR illuminator boards must be connected to the
3.3 V pads** on the camera PCB for night vision to mean anything. IR is
invisible; point a phone camera at them to confirm they are lit.

Those illuminators reach perhaps 5–10 m. That is fine for a fixed camera trap
and useless from a drone at altitude — see the thermal note in
[../../docs/WILDLIFE_CAMERA.md](../../docs/WILDLIFE_CAMERA.md).

### The IR-CUT filter needs one wire

The 22-pin CAM0 connector carries no spare GPIO, so the filter is switched from
the 40-pin header:

```
camera "IR-CUT" / IO pad  ->  40-pin BOARD pin 7
camera GND                ->  40-pin pin 6 (or 9/14/20/25/30/34/39)
```

3.3 V logic both ends. **Never drive that pad from a 5 V pin.** Without the wire
everything still runs — you get the colour/greyscale switch but not the optical
filter, and the feed prints one warning saying so.

The infrared **illuminator LEDs are not software-controllable at all**. They are
wired to the camera board's 3.3 V pads and lit whenever it has power; switching
them would need a MOSFET in that supply. IR is invisible — point a phone camera
at them to check.

## Recovery

`config/STATE.txt` holds the verified device-tree values and SHA-256 sums of the
boot DTB and overlay. If the camera ever stops working, `sha256sum` against it
says in one command whether the boot files changed or whether it is hardware.

Full hardware setup, performance numbers, model choice and troubleshooting:
[../../docs/WILDLIFE_CAMERA.md](../../docs/WILDLIFE_CAMERA.md).
