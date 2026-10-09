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

**`luxonis/wildlife-megadetector:mdv6-yolov10-c`** —
[MegaDetector](https://microsoft.github.io/MegaDetector/) V6 compact, Microsoft
AI for Good, 2.3 M parameters, trained on millions of camera-trap images.
Classes are **animal, person, vehicle**, and `animal` is species-agnostic.

**The conversion risk this document used to warn about is gone.** Luxonis
publishes the model precompiled for RVC2, so `getModelFromZoo` fetches it on the
Jetson with no ONNX export, no OpenVINO, no x86 host and no `pip`. The YOLOv10
NMS-free head that was the stated risk is parsed natively (`subtype=yolov10`).

**Licence.** VENATOR's own code is MIT. This model variant is reported by the
Luxonis zoo as **AGPL-3.0** (the YOLOv10/Ultralytics lineage), though
Microsoft's model card text says MIT. It is **not vendored in this repo** — it is
fetched at runtime into `~/oak-venv/zoo-cache/`, so nothing AGPL is
redistributed here and the MIT licence on this code stands. If a permissive
default matters for how this gets published, the MDV6 family also ships YOLOv9
and RT-DETR variants under MIT/Apache-2.0, and `--model` switches to one in a
single flag — but note the Luxonis zoo currently publishes only this one variant
(`versions: 1`), so another would mean going back to the conversion path.

Measured on this OAK, same pipeline as `oak_wildlife.py`, FAST_ACCURACY:

| | yolov6-nano (previous) | **MegaDetector V6** |
|---|---|---|
| Classes | 80 COCO | animal / person / vehicle |
| Input | `[1,3,288,512]` NCHW | identical, same preprocessing |
| Inference | 33.3 ms | 65.0 ms |
| Ceiling | ≥30 fps | **15.4 fps** (holds 10 fps, 53% headroom) |

Because the input shape and preprocessing are identical, `--model` switches
between them with no other change.

### Why it replaced COCO, measured on `~/Pictures/testset/`

COCO's animal vocabulary is `bird, cat, dog, horse, sheep, cow, elephant, bear,
zebra, giraffe` — no deer, hog, coyote, bobcat, javelina or armadillo. The
failure is not merely absence, it is **confident error**:

| Image | yolov6-nano (COCO) | MegaDetector V6 |
|---|---|---|
| `deer.jpg` | **nothing detected** | animal 76% |
| `hog.jpg` | **`bird` ×6 up to 86%**, `bear` 76%, `sheep` 40% | animal 87% (one box) |
| `javelina.jpg` | `sheep` 70%, `bear` 31% | animal 88% |
| `coyote.jpg` | `dog` 83% | animal 94% |
| `bobcat.jpg` | `cat` 67% | animal 91% |
| `armadillo.jpg` | `dog` 47% | animal 82%, 67% |
| `cattle.jpg` | `cow` ×4 | animal ×8 (whole herd) |
| `turkey.jpg` | `person` 77% | `person` 71% |
| **Totals** | **7/8 images, 1 miss** | **8/8 images** |

A feral hog read as `bird` six times at up to 86% confidence is the clearest
case: no confidence threshold can fix that, only a different model. Note also
that COCO found half the herd MegaDetector did, which matters for counting.

On the 89 bench frames in `~/Pictures/wildlife` at the old global 0.5 threshold,
yolov6-nano produced 26 detections of which **25 were `traffic light` at 61%
mean confidence** — warehouse ceiling lights. With MegaDetector plus the
per-class policy in `drone/wildlife/classes.py`, the same set yields **2**.

**Known false positive, both models:** a wild turkey reads as `person` at
71–77%. Deliberately not fixed by raising the `person` threshold, which would
cost real person recall; it is filtered downstream by the metric-extent gate
(a person is 1.2–2.2 m by stereo Z, a turkey ~0.6 m). See `classes.py`.

**Still unproven: recall from the air.** Everything above is ground-level
imagery. MegaDetector is trained on camera-trap photos and this is a
downward-looking drone, so these numbers say it runs and discriminates, not
that it sees from altitude. That needs field imagery at 15/25/35 m AGL. At
512×288 a javelina spans ~22 px at 15 m and ~11 px at 30 m against a YOLO
stride-8 head wanting 16–20 px, so **fly wildlife at 15–25 m** and save
altitude for person-sized targets.

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

**SHAVE budget — a knob, not a wall.** The MyriadX has 16 SHAVE cores. Stereo
depth, ImageManip and the spatial calculator claim some, and richer stereo
presets leave only 7 free, so a network compiled for 8 refuses to start:

```
Blob compiled for 8 shaves, but only 7 are available
```

**But that is a tunable, which this document previously got wrong.** The zoo
ships a **superblob**, not a blob — it recompiles host-side for any shave count.
Measured on this device at 7 W, fps at 30 fps requested, `SHAVE` = refused to
start:

| preset | default | 4 | 5 | 6 | 8 |
|---|---|---|---|---|---|
| `FAST_ACCURACY` | 15.3 | 19.7 | **22.1** | 13.4 | 15.4 |
| `FAST_DENSITY` | 15.4 | 19.6 | **22.2** | 13.4 | 15.4 |
| `DEFAULT` | `SHAVE` | 11.5 | 14.1 | 12.9 | `SHAVE` |
| `ROBOTICS` | `SHAVE` | 11.5 | 14.2 | 12.9 | `SHAVE` |

Four conclusions, all of which overturn something this document used to say:

1. **`--shaves 5` is the default now** (`DEFAULT_SHAVES` in `oak_wildlife.py`).
   22.3 fps against 15.3 for the archive default, confirmed over 18 s windows —
   **45% more throughput, 65.2 ms → 44.9 ms per inference, for one flag.**
2. **It is not monotonic.** 6 shaves is worse than 4. Stage count does not
   predict it either — 6 compiles to *fewer* stages than 5 and still runs
   slower — so this is SHAVE/CMX tiling behaviour that must be measured per
   model, not reasoned about. Re-run the sweep when the model changes.
3. **`DEFAULT` and `ROBOTICS` do work**, at 4–6 shaves. The old claim that they
   fail outright was true only at the archive's default count. They cost ~36% of
   the frame rate (14.1 vs 22.1 at 5 shaves) and still clear a 10 fps target.
4. **`FAST_ACCURACY` and `FAST_DENSITY` are identical in throughput**, so choose
   between them on depth quality alone. `FAST_ACCURACY` stays the default
   because ranging one distinct animal rewards depth accuracy over density.

The 45% headroom this buys is what makes a second network — a species
classifier on cropped tracks — plausible later.

### Power, measured

VDD_IN on the INA3221, 1 s samples, in 7 W mode (`nvpmodel -m 1`, 4 cores
online, clamped to 960 MHz):

| | mean | peak |
|---|---|---|
| Baseline, desktop session running | 6.32 W | 6.72 W |
| Detector at 10 fps on top of that | 7.11 W | 7.44 W |
| **Detector's marginal cost** | **+0.79 W** | |

**+0.79 W is the number that transfers.** The 6.32 W baseline is *not* a drone
baseline — it was measured with Xorg, GNOME Shell and a desktop app consuming
most of the CPU, so a headless airframe starts far lower. Note also that 7 W
nvpmodel mode is an SoC/clock budget, not a VDD_IN ceiling: VDD_IN includes the
OAK drawing bus power, which is why the board reads above 7 W while the mode is
honoured. Detector throughput is identical at 7 W and 15 W (15.38 vs 15.37 fps,
65.0 ms both) because inference never touches the Jetson.

**The passthrough frame is `BGR888p` — planar.** `getFrame()` returns a 2-D
`(h*3, w)` array of three stacked B/G/R planes, not `(h, w, 3)`. Indexing it as
an image raises `too many indices for array`. `to_rgb()` handles all three
layouts.

**Two depthai versions coexist on this box.** `camera_publisher.py` (the flight
person-tracker) needs **2.32** in `~/oak_drone_project/depthai-env`; the wildlife
code needs **3.10** in `~/oak-venv`. The APIs are incompatible — neither script
runs in the other's interpreter.
