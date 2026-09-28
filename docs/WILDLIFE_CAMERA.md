# Wildlife cameras — hardware, setup and troubleshooting

Deep reference for [`drone/wildlife/`](../drone/wildlife/README.md). Everyday
commands live in that module README; this covers how the hardware is wired, what
was measured, and how to diagnose it when it breaks.

Verified working **2026-09-27** on L4T R39.2.0.

## Hardware

| | |
|---|---|
| Board | Jetson Orin Nano Developer Kit — module `p3767-0005`, carrier `p3768-0000` |
| L4T / OS | R39.2.0 · kernel `6.8.12-1021-tegra` · Ubuntu 24.04 |
| **Camera 1** | Luxonis **OAK-D-S2-FF**, MxID `194430107164191300`, RVC2 (MyriadX) |
| **Camera 2** | Waveshare **IMX219-160 IR-CUT**, 8 MP, 162° FOV, on **CAM0** |

### Camera 1 — OAK-D-S2

| Socket | Sensor | Resolution | Role |
|---|---|---|---|
| `CAM_A` | IMX378 | 4056×3040 (12 MP) | colour, fixed focus |
| `CAM_B` / `CAM_C` | OV9282 | 1280×800 | stereo pair |

Plus a BMI270 IMU. **No IR illumination** — the flood LED and dot projector are
OAK-D-**Pro** features, and the device reports `getIrDrivers() == []`. It has a
fixed IR-cut filter, so it is a **daytime sensor** and sees nothing in darkness.
That is why camera 2 exists.

Measured: colour 640×480 at **20.5 fps**, depth 640×400 valid **0.31–56 m**,
detection at a steady **10 fps**.

It negotiated `UsbSpeed.HIGH` — **USB 2.0, 480 Mbps**. Move it to a USB 3.0 port;
that cap was limiting throughput before a network was even added.

### Camera 2 — IMX219-160 IR-CUT

Connected to **CAM0** with the 22-pin FFC ribbon, contacts toward the heatsink.

## Verified device-tree configuration

Do not "fix" these. Every value is cross-checked against the silicon.

```
DEFAULT  JetsonIO
FDT      /boot/dtb/tegra234-p3768-0000+p3767-0005-nv.dtb
OVERLAYS /boot/tegra234-p3767-camera-p3768-imx219-A.dtbo
```

| Device tree | Value | Cross-check |
|---|---|---|
| node | `rbpcv2_imx219_a` | `_a` = position A = CAM0 |
| `port-index` | `1` | RCE log: `csi_port: PORT B`, `CIL B`, `PP 1` |
| `bus-width` | `2` | sensor `CSI_LANE_MODE=0x01`; receiver `Lanes: 2` |
| `mclk_khz` | `24000` | PLL: 24/3×57 = **456 MHz**, ×114 = **912 Mbps** |
| `pix_clk_hz` | `182400000` | receiver `Physical rate: 912000 Kbps` |
| badge | `jakku_front_RBP194` | Orin Nano + RPi cam v2 |

`setup_cam0.sh` applies the overlay. It is dry-run by default and works around
an R39 regression where `jetson-io` globs `/boot/dtb/*.dtb` but R39 installs the
DTBs flat in `/boot/`.

## Performance at 7 W

The rig is required to run in the **7 W** power mode (`nvpmodel` ID 1, 4 of 6
cores). Optimise inside the budget; do not raise it.

The bottleneck is the NVMM→CPU copy, not the sensor, so the hardware VIC
(`nvvidconv`) downscales **before** the copy and the display path stays
zero-copy.

| Path | Resolution | fps |
|---|---|---|
| `nv3dsink` (zero copy) | 1280×720 | **45.7** |
| `nv3dsink` (zero copy) | 1920×1080 | 24.7 |
| numpy appsink, flip + metering | 720p → 640×360 | **55.0** |
| numpy appsink | 720p → 1280×720 | 27.3 |
| OAK spatial detection | 512×288 | 10.0 |

Board draw with the CSI feed running: **~6.8 W** of 7 W.

> The Orin Nano has **no NVENC** — the H.264 encoder is fused off. Recording must
> use software `x264enc` (~21 fps at 1080p). Hardware JPEG (`nvjpegenc`) works.

`pip install opencv-python` gives a build **without** GStreamer support and
cannot open this camera. `imx219_feed.py` avoids OpenCV entirely and hands back
the same BGR numpy arrays `cv2.VideoCapture` would.

## Night vision: what actually works

Two things were measured on this rig and both are worth knowing before trusting
a night image.

**Image metering cannot detect darkness here.** In a pitch-dark room the meter
branch reported a mean luma of **101.5** against a night threshold of 40. Argus
auto-exposure raises analog gain (1.0–10.625×) until the scene averages to a
correct exposure, so the mean sits near mid-grey regardless of real brightness.
`--daynight auto` is therefore test-only; **`--daynight schedule`** (NOAA solar
position at `--lat`/`--lon`, −6° civil twilight) is the default and the one to
trust. It needs no light source and cannot be fooled by headlights or by the
camera pointing at the ground.

**Removing the IR-CUT filter does not create infrared.** It makes the sensor
*able* to see IR. Measured in the dark, day and night modes produced identical
blank frames — mean luma 37.6 vs 36.6, **std dev 0.5 in both**, 4 KB JPEGs. A
std of 0.5/255 is amplified sensor noise, not an image.

For a usable night picture the Waveshare kit's **IR illuminator boards must be
connected to the 3.3 V pads** on the camera PCB. They are not software
controllable (see the module README), and they reach roughly 5–10 m.

> That range is the crux for this project. Passive IR is fine for a fixed camera
> trap and useless from a drone at altitude. Feral hogs — the species most Texas
> landowners care about — are largely nocturnal, so if night hogs are a target,
> **thermal is the honest answer**, not an IR-illuminated RGB sensor.

## Detection model

Currently **`luxonis/yolov6-nano:r2-coco-512x288`** — pre-compiled for RVC2, so
zero conversion risk. It exists to prove the pipeline, **not** as the final model.

COCO's entire animal vocabulary is `bird, cat, dog, horse, sheep, cow, elephant,
bear, zebra, giraffe`. **No deer, fox, raccoon, boar, wolf, coyote, bobcat or
moose.** For real wildlife it is structurally blind to most subjects, and it
calls warehouse ceiling lights "traffic light" at ~20% confidence.

**Target: [MegaDetector](https://microsoft.github.io/MegaDetector/) V6 compact
(`MDV6-yolov10-c`)** — MIT licensed, Microsoft AI for Good, used in 80+
conservation programs. 2.3 M parameters (~2% of v5's 139.9 M) at comparable
accuracy, explicitly aimed at edge and solar field units. Classes are **animal,
person, vehicle**, and `animal` is species-agnostic. It is trained on real
camera-trap imagery, so it survives night/IR, motion blur, occlusion and
distance, where COCO models fall apart.

Conversion (ONNX → OpenVINO IR → `.blob`) is the open risk: RVC2 runs an older
OpenVINO than YOLOv10 targets. Fallback order: `MDV6-yolov10-c` →
`MDV6-yolov9-c` → MegaDetector v5 (YOLOv5-based, the best-trodden path to blob).

## Troubleshooting

Run `checks/check_camera.sh` first. If capture fails but I²C is healthy, the
fault is in the MIPI physical layer, not software.

### MIPI CSI is not hot-swappable

This cost hours. Swapping the ribbon on a live board leaves the sensor with no
power-on reset and the CSI receiver with stale D-PHY calibration. Symptom: I²C
works perfectly, `/dev/video0` exists, all 5 modes enumerate — and **zero frames
with zero CSI errors**.

> Always `sudo shutdown -h now`, then **unplug the barrel jack for 10 s**, before
> touching the ribbon. A soft reboot does not reset the sensor's rails.

### Reading the evidence correctly

- **`UU` in `i2cdetect` does *not* mean the sensor answered.** It means "a driver
  claimed this address, so I skipped probing it." Use the model-ID read:
  ```bash
  i2ctransfer -y -f 9 w2@0x10 0x00 0x00 r2    # must return 0x02 0x19
  ```
  `-f` is required because `nv_imx219` owns the address. **No answer while idle
  is normal** — the driver powers the sensor down between captures.
- **The 5 enumerated modes come from the driver's static table**, not the chip.
  They prove nothing about the hardware.
- **Silence ≠ noise.** A marginal lane floods the log with ECC/CRC errors. *Zero*
  errors plus zero frames means no signal at all — suspect the 24 MHz MCLK or an
  open/swapped CSI pair.
- Read the kernel log with `journalctl -k -b` (works unprivileged via the `adm`
  group). Do not relax `kernel.dmesg_restrict` just to read it.

### Argus allows only one consumer

A second capture fails with `Failed to create CaptureSession`. That is expected,
and is itself proof the running feed owns the sensor.

If Argus times out (`waitCsiFrameStart`, `Sensor GUID 1 is in error state`), the
error **latches** — no retry succeeds until:

```bash
sudo systemctl restart nvargus-daemon
```

Kill feeds with `SIGTERM`, never `SIGKILL`: `imx219_feed.py` traps it and unwinds
the pipeline to `NULL`, which is what gives Argus a clean stream-off.

### OAK gotchas

**SHAVE budget.** The MyriadX has 16 SHAVE cores; the zoo `yolov6-nano` blob is
compiled for 8. Stereo depth, ImageManip and the spatial calculator claim the
rest, so richer stereo presets leave only 7 free and the pipeline refuses to
start:

```
Blob compiled for 8 shaves, but only 7 are available
```

Measured on this device: `DEFAULT` and `ROBOTICS` **fail**; `FAST_ACCURACY` and
`FAST_DENSITY` **work**. `FAST_ACCURACY` is the default.

**The passthrough frame is `BGR888p` — planar.** `getFrame()` returns a 2-D
`(h*3, w)` array of three stacked B/G/R planes, not `(h, w, 3)`. Indexing it as
an image raises `too many indices for array`. `to_rgb()` handles all three
layouts.

**Two depthai versions coexist on this box.** `camera_publisher.py` (the flight
person-tracker) needs **2.32** in `~/oak_drone_project/depthai-env`; the wildlife
code needs **3.10** in `~/oak-venv`. The APIs are incompatible — neither script
runs in the other's interpreter.
