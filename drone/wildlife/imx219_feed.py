#!/usr/bin/env python3
"""
Camera 2: IMX219-160 IR-CUT on CAM0 of a Jetson Orin Nano, tuned for 7 W.

Day/night behaviour
-------------------
    day    normal colour   (ISP saturation 1.0, IR-CUT filter ON)
    night  black and white (ISP saturation 0.0, IR-CUT filter OFF -> IR passes)

Both are hardware paths. `saturation` is an nvarguscamerasrc property applied
inside the ISP, so greyscale costs nothing - no GRAY8 conversion, no CPU
videobalance. The 180-degree invert is `nvvidconv flip-method=2`, which runs on
the VIC, so it is also free CPU-wise.

Greyscale at night is not cosmetic. With the IR-CUT filter removed the Bayer
colour filters see infrared, which produces a strong magenta cast carrying no
real colour information. Discarding chroma gives a cleaner image and compresses
far better.

Uses python3-gi + GStreamer, so NO OpenCV is needed. numpy frames come out of
an appsink as BGR, the same layout cv2.VideoCapture would give you.

Why it is built this way at 7 W
-------------------------------
Only 4 of 6 CPU cores are online and the GPU sits at ~408 MHz. The bottleneck
is the NVMM -> CPU memory copy, not the sensor, so the hardware VIC downscales
BEFORE the copy. Measured at 7 W:

    display, zero-copy (nv3dsink):   1280x720  45.7 fps | 1920x1080 24.7 fps
    numpy via appsink:  720p->640x360  53.0 fps | 720p->720p 27.3 fps

The Orin Nano has NO hardware H.264 encoder (NVENC is fused off), so recording
must use software x264enc. Hardware JPEG (nvjpegenc) works.

Examples
--------
    ./imx219_feed.py --list
    ./imx219_feed.py --display                    # auto day/night, inverted
    ./imx219_feed.py --display --daynight night   # force B&W night mode
    ./imx219_feed.py --display --flip 0           # no rotation
    ./imx219_feed.py --frames 300                 # numpy, 640x360
    ./imx219_feed.py --mode 0 --snapshot still.jpg
"""

import argparse
import signal
import sys
import time

import numpy as np

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst  # noqa: E402

# sensor-mode index -> (width, height, max fps). Matches the five modes
# declared by tegra234-p3767-camera-p3768-imx219-A.dtbo on this board.
MODES = {
    0: (3280, 2464, 21),
    1: (3280, 1848, 28),
    2: (1920, 1080, 30),
    3: (1640, 1232, 30),
    4: (1280, 720, 60),
}
DEFAULT_MODE = 4          # 720p60 - the most headroom at 7W
DEFAULT_OUT = (640, 360)  # hardware-downscaled before the CPU copy

# nvvidconv flip-method. 2 = rotate 180, i.e. the camera is mounted upside down.
DEFAULT_FLIP = 2

# White balance. 3 = "fluorescent".
#
# With the IR-CUT filter physically removed, near-infrared passes through the
# Bayer dye filters (silicon is sensitive out to ~1000 nm) and lands unevenly
# across all three channels, producing the magenta cast. The ISP's auto white
# balance cannot correct it: measured on this camera, wbmode=auto and wbmode=off
# returned byte-identical channel means, i.e. AWB simply gives up.
#
#     wbmode             R/G    B/G
#     auto / off         1.73   1.41   strong magenta
#     fluorescent (3)    1.09   0.91   near-neutral   <- chosen
#     incandescent (2)   0.99   1.20
#     twilight (7)       1.22   0.26
#
# This is compensation, not a cure. IR still adds to every channel, so contrast
# and colour fidelity remain degraded, and the ideal correction shifts with how
# much IR the scene contains (sunlight is IR-rich, LED lighting is not).
#
# ONCE THE IR-CUT GPIO WIRE IS FITTED, set this back to 1 (auto): the optical
# filter removes IR at the source and AWB starts working properly again.
DEFAULT_WBMODE = 3

# Light metering. The meter branch is a 160x90 GRAY8 appsink: ~14 kB per sample,
# negligible even at 7 W.
#
# WARNING: mean luma is a POOR darkness signal on this camera, and "auto" is no
# longer the default because of it. Measured in a pitch-dark room:
#
#     meter mean = 101.5  (min 36, max 225, std 3.6)
#
# Argus auto-exposure raises analog gain (1.0 - 10.625x) until the scene
# averages to a "correct" exposure, so the mean sits near mid-grey no matter
# how dark the room is. No threshold can separate day from night through AE.
# Raising DARK_BELOW above 101 would just make it read night in daylight too.
#
# Use --daynight schedule (sunrise/sunset) for anything that matters. It is
# deterministic, needs no light source, and is what a fixed or airborne
# installation actually wants. --daynight auto is kept for hand testing only.
METER_SIZE = (160, 90)
METER_INTERVAL = 5.0   # seconds between decisions
DARK_BELOW = 40.0      # mean luma 0-255 below this => night
HYSTERESIS = 15.0      # must exceed DARK_BELOW + this to go back to day


def is_night_by_clock(lat, lon, when=None):
    """
    True when the sun is below the horizon at (lat, lon) right now.

    NOAA low-precision solar position algorithm - accurate to about a minute,
    which is far better than needed to decide between colour and monochrome.
    No dependencies and no light source required, which is exactly why this is
    the switching method to trust: unlike metering the image, it cannot be
    fooled by auto-exposure, headlights, or a camera pointed at the ground.
    """
    import calendar
    import datetime as _dt
    import math

    now = when or _dt.datetime.now(_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    ts = calendar.timegm(now.utctimetuple())

    # Julian centuries since J2000.0
    jd = ts / 86400.0 + 2440587.5
    t = (jd - 2451545.0) / 36525.0

    # Geometric mean longitude and anomaly of the sun (degrees)
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    mrad = math.radians(m)

    # Equation of centre -> true longitude -> apparent longitude
    c = (math.sin(mrad) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mrad) * (0.019993 - 0.000101 * t)
         + math.sin(3 * mrad) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))

    # Obliquity of the ecliptic, then declination
    eps0 = (23.0 + (26.0 + ((21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))))
                    / 60.0) / 60.0)
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(app_long)))

    # Equation of time (minutes)
    y = math.tan(math.radians(eps / 2.0)) ** 2
    l0r = math.radians(l0)
    eot = 4 * math.degrees(
        y * math.sin(2 * l0r)
        - 2 * 0.016708634 * math.sin(mrad)
        + 4 * 0.016708634 * y * math.sin(mrad) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r)
        - 1.25 * 0.016708634 ** 2 * math.sin(2 * mrad))

    # True solar time -> hour angle -> solar elevation
    minutes = now.hour * 60 + now.minute + now.second / 60.0
    tst = (minutes + eot + 4 * lon) % 1440
    ha = tst / 4.0 - 180.0
    latr = math.radians(lat)
    elev = math.degrees(math.asin(
        math.sin(latr) * math.sin(decl)
        + math.cos(latr) * math.cos(decl) * math.cos(math.radians(ha))))

    # -6 deg = civil twilight: the point where usable colour really is gone.
    return elev < -6.0


class IrCut:
    """
    IR-CUT filter control for the Waveshare IMX219-160 IR-CUT module.

    HIGH (3.3 V) = filter OFF = night vision. LOW (GND) = filter ON = daytime.

    The 22-pin CAM0 connector carries no spare GPIO, so this needs a wire from
    a 40-pin header pin to the camera board's IR-CUT pad. If that wire is not
    fitted this degrades to a no-op with one warning rather than failing: the
    saturation switch still works, you just do not get the optical filter.
    """

    NIGHT, DAY = 1, 0

    def __init__(self, pin=7, enabled=True):
        self.pin = pin
        self.gpio = None
        self.warned = False
        if not enabled:
            return
        try:
            import Jetson.GPIO as GPIO
            GPIO.setmode(GPIO.BOARD)
            GPIO.setwarnings(False)
            GPIO.setup(pin, GPIO.OUT)
            self.gpio = GPIO
        except Exception as e:                            # noqa: BLE001
            print(f"note: IR-CUT GPIO unavailable ({e}); "
                  f"continuing without optical filter control", file=sys.stderr)

    def set(self, night):
        if self.gpio is None:
            if not self.warned:
                print("note: IR-CUT filter not switched - no GPIO. Wire the "
                      f"camera's IR-CUT pad to 40-pin BOARD pin {self.pin}.",
                      file=sys.stderr)
                self.warned = True
            return
        self.gpio.output(self.pin, self.NIGHT if night else self.DAY)

    def close(self):
        # Deliberately no GPIO.cleanup(): releasing the line lets it float and
        # would drop the filter out of whatever mode we just selected.
        pass


def build_pipeline(mode, out_wh, display, sensor_id, sink, flip, night, meter,
                   wbmode=DEFAULT_WBMODE):
    """Assemble the pipeline description for one day/night state."""
    w, h, fps = MODES[mode]
    # saturation is applied by the ISP, so night mode costs nothing downstream.
    saturation = 0.0 if night else 1.0
    src = (
        f"nvarguscamerasrc sensor-id={sensor_id} sensor-mode={mode} "
        f"saturation={saturation} wbmode={wbmode} "
        f"! video/x-raw(memory:NVMM),width={w},height={h},framerate={fps}/1"
    )
    if flip:
        # Stays in NVMM: the VIC does the rotation, no CPU copy.
        src += f" ! nvvidconv flip-method={flip} ! video/x-raw(memory:NVMM)"

    if display:
        if sink == "nv3dsink":
            branch = "nv3dsink sync=false"
        else:
            # Fallback sinks cannot read NVMM, so pay one VIC conversion.
            branch = (f"nvvidconv ! video/x-raw,format=BGRx ! {sink} sync=false")
    else:
        ow, oh = out_wh
        branch = (f"nvvidconv ! video/x-raw,format=BGRx,width={ow},height={oh} "
                  f"! appsink name=sink max-buffers=1 drop=true sync=false")

    if not meter:
        return f"{src} ! {branch}"

    mw, mh = METER_SIZE
    return (
        f"{src} ! tee name=t "
        f"t. ! queue max-size-buffers=2 leaky=downstream ! {branch} "
        f"t. ! queue max-size-buffers=2 leaky=downstream "
        f"! nvvidconv ! video/x-raw,format=GRAY8,width={mw},height={mh} "
        f"! appsink name=meter max-buffers=1 drop=true sync=false"
    )


def explain_failure(text):
    """Turn the two failure modes we have actually hit into plain guidance."""
    t = (text or "").lower()
    if "nvbufsurfacefromfd" in t or "dmabuf_fd -1" in t:
        print(
            "\n"
            "This is the Argus 'no frames arrived' signature, not a sink bug.\n"
            "The sensor is configured over I2C but the MIPI CSI-2 data lanes\n"
            "delivered nothing, so the buffer handed to the sink was invalid.\n"
            "\n"
            "Check, in order:\n"
            "  1. sudo systemctl restart nvargus-daemon   (the error state latches)\n"
            "  2. journalctl -u nvargus-daemon -n 50 | grep -i timeout\n"
            "  3. journalctl -k -b | grep -iE 'nvcsi|imx219|vi5'\n"
            "  4. MIPI CSI is NOT hot-swappable. Power off, unplug for 10s,\n"
            "     reseat the ribbon at both ends, contacts toward the heatsink.\n",
            file=sys.stderr)


def sample_to_bgr(sample):
    """Pull a BGRx sample into an (h, w, 3) BGR uint8 array, stride-safe."""
    buf = sample.get_buffer()
    caps = sample.get_caps().get_structure(0)
    w = caps.get_value("width")
    h = caps.get_value("height")

    ok, info = buf.map(Gst.MapFlags.READ)
    if not ok:
        raise RuntimeError("failed to map GStreamer buffer")
    try:
        # nvvidconv may pad rows, so derive the real stride from the size
        # rather than assuming w * 4.
        stride = info.size // h
        arr = np.ndarray((h, stride // 4, 4), dtype=np.uint8, buffer=info.data)
        return arr[:, :w, :3].copy()  # copy before unmap; drop the X channel
    finally:
        buf.unmap(info)


def read_meter(appsink):
    """Mean luma 0-255 from the metering branch, or None if no sample yet."""
    sample = appsink.emit("try-pull-sample", 0)
    if sample is None:
        return None
    buf = sample.get_buffer()
    caps = sample.get_caps().get_structure(0)
    w, h = caps.get_value("width"), caps.get_value("height")
    ok, info = buf.map(Gst.MapFlags.READ)
    if not ok:
        return None
    try:
        stride = info.size // h
        arr = np.ndarray((h, stride), dtype=np.uint8, buffer=info.data)
        return float(arr[:, :w].mean())
    finally:
        buf.unmap(info)


def should_switch(night, luma, dark_below):
    """
    Decide whether to leave the current day/night state.

    Hysteresis matters: without it, a scene hovering at the threshold would
    rebuild the pipeline every few seconds at dusk.

    Caveat worth knowing: Argus auto-exposure brightens a dark scene, so mean
    luma is a softer darkness signal than it looks. Tune --dark-below for the
    actual site, or force the mode with --daynight day|night. For a fixed
    installation, driving this off local sunrise/sunset is more reliable.
    """
    if luma is None:
        return False
    if night:
        return luma > dark_below + HYSTERESIS
    return luma < dark_below


def run_session(args, night, stopping):
    """
    Run one pipeline until it ends or the day/night state should change.

    Returns (reason, frames) where reason is 'switch', 'stop', 'done' or 'error'.
    """
    auto = args.daynight == "auto"
    sched = args.daynight == "schedule"
    desc = build_pipeline(args.mode, args.out_wh, args.display, args.sensor_id,
                          args.sink, args.flip, night, meter=auto,
                          wbmode=args.wbmode)
    label = "night (B&W)" if night else "day (colour)"
    print(f"\n[{label}] pipeline: {desc}\n", flush=True)

    pipeline = Gst.parse_launch(desc)
    if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
        print("error: pipeline failed to start", file=sys.stderr)
        return "error", 0

    meter = pipeline.get_by_name("meter") if auto else None
    sink = None if args.display else pipeline.get_by_name("sink")
    bus = pipeline.get_bus()

    n = 0
    t0 = t_report = t_meter = time.monotonic()
    reason = "done"
    try:
        if args.display:
            print("live window open - press Ctrl+C to stop", flush=True)
        while not stopping["flag"]:
            if args.display:
                msg = bus.timed_pop_filtered(
                    100 * Gst.MSECOND,
                    Gst.MessageType.ERROR | Gst.MessageType.EOS)
                if msg is not None:
                    if msg.type == Gst.MessageType.ERROR:
                        err, dbg = msg.parse_error()
                        print(f"error: {err} ({dbg})", file=sys.stderr)
                        explain_failure(dbg or str(err))
                        reason = "error"
                    break
            else:
                sample = sink.emit("try-pull-sample", Gst.SECOND)
                if sample is None:
                    print("warning: no frame within 1s", file=sys.stderr)
                    continue
                frame = sample_to_bgr(sample)
                n += 1

                if args.snapshot:
                    from PIL import Image
                    Image.fromarray(frame[:, :, ::-1]).save(args.snapshot)
                    print(f"saved {args.snapshot}  "
                          f"{frame.shape[1]}x{frame.shape[0]}  [{label}]")
                    reason = "done"
                    break

                # ---- your processing goes here; `frame` is BGR uint8 ----

                now = time.monotonic()
                if now - t_report >= 2.0:
                    print(f"{n:6d} frames  {n/(now-t0):5.1f} fps avg  "
                          f"shape={frame.shape}  mean={frame.mean():5.1f}",
                          flush=True)
                    t_report = now
                if args.frames and n >= args.frames:
                    reason = "done"
                    break

            now = time.monotonic()
            if (meter is not None or sched) and now - t_meter >= METER_INTERVAL:
                t_meter = now
                if sched:
                    if is_night_by_clock(args.lat, args.lon) != night:
                        print(f"\n-- sun crossed civil twilight -> switching to "
                              f"{'day' if night else 'night'} mode", flush=True)
                        reason = "switch"
                        break
                else:
                    luma = read_meter(meter)
                    if should_switch(night, luma, args.dark_below):
                        print(f"\n-- light level {luma:.1f} -> switching to "
                              f"{'day' if night else 'night'} mode", flush=True)
                        reason = "switch"
                        break
        else:
            reason = "stop"
        if stopping["flag"]:
            reason = "stop"
        return reason, n
    finally:
        pipeline.set_state(Gst.State.NULL)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="list sensor modes and exit")
    p.add_argument("--mode", type=int, default=DEFAULT_MODE, choices=sorted(MODES),
                   help=f"sensor mode index (default {DEFAULT_MODE})")
    p.add_argument("--sensor-id", type=int, default=0, help="0=CAM0, 1=CAM1")
    p.add_argument("--out", default=f"{DEFAULT_OUT[0]}x{DEFAULT_OUT[1]}",
                   help="appsink output WxH, hardware-downscaled (default 640x360)")
    p.add_argument("--display", action="store_true",
                   help="show a live window via nv3dsink (zero copy, fastest)")
    p.add_argument("--sink", default="nv3dsink",
                   choices=("nv3dsink", "xvimagesink", "ximagesink", "nveglglessink"),
                   help="video sink for --display; use xvimagesink if the "
                        "GL/EGL path fails (default nv3dsink)")
    p.add_argument("--frames", type=int, default=0,
                   help="grab N numpy frames then stop (0 = run until Ctrl+C)")
    p.add_argument("--snapshot", metavar="FILE",
                   help="save one frame as PNG/JPEG (needs Pillow) and exit")
    p.add_argument("--flip", type=int, default=DEFAULT_FLIP, choices=range(0, 8),
                   metavar="0-7",
                   help="nvvidconv flip-method: 0 none, 2 rotate-180, "
                        "4 horizontal, 6 vertical (default 2 = inverted)")
    p.add_argument("--wbmode", type=int, default=DEFAULT_WBMODE, choices=range(0, 10),
                   metavar="0-9",
                   help="nvarguscamerasrc white balance. 3 (fluorescent) "
                        "compensates for the missing IR-CUT filter; set 1 "
                        "(auto) once the IR-CUT wire is fitted (default 3)")
    p.add_argument("--daynight", default="schedule",
                   choices=("schedule", "auto", "day", "night"),
                   help="schedule uses sunrise/sunset at --lat/--lon "
                        "(default, and the only reliable one); auto meters the "
                        "image but auto-exposure defeats it; day/night force a mode")
    p.add_argument("--lat", type=float, default=30.2672, metavar="DEG",
                   help="latitude for --daynight schedule (default 30.2672, Austin TX)")
    p.add_argument("--lon", type=float, default=-97.7431, metavar="DEG",
                   help="longitude for --daynight schedule (default -97.7431, Austin TX)")
    p.add_argument("--dark-below", type=float, default=DARK_BELOW,
                   metavar="LUMA",
                   help=f"mean luma 0-255 below which it is night "
                        f"(default {DARK_BELOW:g})")
    p.add_argument("--ircut-pin", type=int, default=7, metavar="BOARD_PIN",
                   help="40-pin header pin driving the IR-CUT filter (default 7)")
    p.add_argument("--no-ircut", action="store_true",
                   help="do not touch the IR-CUT GPIO at all")
    args = p.parse_args()

    if args.list:
        print("sensor-mode  resolution    max fps")
        for i, (w, h, f) in sorted(MODES.items()):
            star = "  <- default" if i == DEFAULT_MODE else ""
            print(f"    {i}        {w}x{h}".ljust(27) + f"{f}{star}")
        return 0

    try:
        ow, oh = (int(v) for v in args.out.lower().split("x"))
    except ValueError:
        print(f"error: --out must look like 640x360, got {args.out!r}", file=sys.stderr)
        return 2
    args.out_wh = (ow, oh)

    Gst.init(None)
    stopping = {"flag": False}
    # Trap SIGTERM as well as SIGINT. If the process dies without reaching the
    # set_state(NULL) below, Argus never issues a clean stream-off and the
    # IMX219 can be left mid-frame, which needs an nvargus-daemon restart.
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stopping.__setitem__("flag", True))

    ircut = IrCut(args.ircut_pin, enabled=not args.no_ircut)
    if args.daynight == "schedule":
        night = is_night_by_clock(args.lat, args.lon)
        print(f"schedule: {args.lat:.4f},{args.lon:.4f} -> "
              f"{'night' if night else 'day'} right now")
    else:
        night = args.daynight == "night"
    total, rc = 0, 0
    t0 = time.monotonic()
    try:
        while not stopping["flag"]:
            ircut.set(night)
            reason, n = run_session(args, night, stopping)
            total += n
            if reason == "switch":
                night = not night
                continue
            if reason == "error":
                rc = 1
            break
    finally:
        ircut.close()

    el = time.monotonic() - t0
    if total:
        print(f"\n{total} frames in {el:.2f}s -> {total/el:.1f} fps average")
    return rc


if __name__ == "__main__":
    sys.exit(main())
