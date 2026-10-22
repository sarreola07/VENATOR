#!/usr/bin/env python3
"""
OAK-D-S2 with automatic day/night switching.

    day    CAM_A  IMX378 colour   - full colour, detail
    night  CAM_B  OV9282 mono     - ~6x more light, greyscale

    /home/jetson/oak-venv/bin/python oak_daynight.py
    /home/jetson/oak-venv/bin/python oak_daynight.py --force night
    /home/jetson/oak-venv/bin/python oak_daynight.py --calibrate
    /home/jetson/oak-venv/bin/python oak_daynight.py --stats

HOW IT DECIDES, AND WHY NOT BY BRIGHTNESS
-----------------------------------------
Measuring how bright the picture looks does not work: auto-exposure drives
every scene toward mid-grey, so a pitch-dark room and a lit one report almost
the same mean. That mistake cost real debugging time on the CSI camera, where
the meter read 101/255 in a blacked-out room against a "night" threshold of 40.

So this reads what auto-exposure *chose* instead, which is a direct measure of
how much light actually arrived. Measured on this unit in a dark room:

    CAM_A colour   30008 us (max)  ISO 1599 (max)   -> completely pinned
    CAM_B mono     29992 us (max)  ISO  424         -> still has headroom

The colour camera runs out of both exposure time and gain long before the mono
does. "AE load" here is exposure x ISO expressed as a fraction of the maximum
the sensor will allow, so 1.0 means the camera has given up.

    load >= --night-load (default 0.80)  -> night, switch to mono
    load <= --day-load   (default 0.45)  -> day,   switch to colour

The gap between the two is hysteresis: without it, dusk would flap between
modes every few seconds.

BOTH SENSORS STAY STREAMING
---------------------------
Switching selects which frame to draw rather than rebuilding the pipeline, so
the change is instant and the AE reading from CAM_A stays available as the
light meter even while the mono is on screen. Output is a constant 640x400 BGR
either way; mono frames are replicated across the three channels so the display
pipeline never renegotiates.

The OAK-D-S2 has no IR emitters (getIrDrivers() == []). Night mode makes the
most of available light; it does not create any.
"""

import argparse
import signal
import sys
import time

# Ceilings the sensor will not exceed. Exposure is capped by the frame rate
# (30 fps -> ~30 ms) and ISO by the sensor itself; both were observed pinned at
# these values in the dark, which is what makes them a usable denominator.
MAX_EXPOSURE_US = 30000.0
MAX_ISO = 1600.0


def ae_load(frame):
    """How hard auto-exposure is working, 0.0 (bright) to ~1.0 (given up)."""
    us = frame.getExposureTime().total_seconds() * 1e6
    iso = frame.getSensitivity()
    return (us * iso) / (MAX_EXPOSURE_US * MAX_ISO)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", choices=("day", "night"),
                    help="pin a mode instead of switching automatically")
    ap.add_argument("--night-load", type=float, default=0.80,
                    help="AE load at or above which it is night (default 0.80)")
    ap.add_argument("--day-load", type=float, default=0.45,
                    help="AE load at or below which it is day (default 0.45)")
    ap.add_argument("--settle", type=float, default=3.0,
                    help="seconds to let auto-exposure converge before any "
                         "switch decision (default 3)")
    ap.add_argument("--dwell", type=float, default=3.0,
                    help="the threshold must hold continuously for this long "
                         "before switching (default 3)")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=400)
    ap.add_argument("--sink", default="nv3dsink",
                    choices=("nv3dsink", "xvimagesink", "ximagesink"))
    ap.add_argument("--stats", action="store_true",
                    help="print the decision numbers instead of opening a window")
    ap.add_argument("--calibrate", action="store_true",
                    help="print AE load from both sensors and exit; use it to "
                         "pick thresholds for your own site")
    args = ap.parse_args()

    if args.day_load >= args.night_load:
        print("error: --day-load must be below --night-load (that gap is the "
              "hysteresis that stops it flapping at dusk)", file=sys.stderr)
        return 2

    import depthai as dai
    import numpy as np

    w, h = args.width, args.height
    headless = args.stats or args.calibrate

    pipe = appsrc = Gst = None
    if not headless:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        # The format between videoconvert and nvvidconv must be pinned: left to
        # negotiate freely nvvidconv rejects it with "Transform not supported".
        if args.sink == "nv3dsink":
            tail = ("videoconvert ! video/x-raw,format=I420 "
                    "! nvvidconv ! video/x-raw(memory:NVMM) ! nv3dsink sync=false")
        else:
            tail = f"videoconvert ! {args.sink} sync=false"
        desc = (f"appsrc name=src is-live=true format=time "
                f"caps=video/x-raw,format=BGR,width={w},height={h},framerate=20/1 "
                f"! {tail}")
        print(f"pipeline: {desc}\n")
        pipe = Gst.parse_launch(desc)
        appsrc = pipe.get_by_name("src")
        if pipe.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            print("error: display pipeline failed to start", file=sys.stderr)
            return 1

    with dai.Pipeline() as pipeline:
        colour = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        mono = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_B)
        q_colour = colour.requestOutput(
            (w, h), dai.ImgFrame.Type.BGR888i).createOutputQueue()
        q_mono = mono.requestOutput(
            (w, h), dai.ImgFrame.Type.GRAY8).createOutputQueue()

        pipeline.start()

        if args.calibrate:
            print("AE load from both sensors. 1.0 means the camera has given up.\n")
            print(f"{'t':>6} {'CAM_A load':>11} {'us':>7} {'iso':>5}   "
                  f"{'CAM_B load':>11} {'us':>7} {'iso':>5}")
            t0 = time.monotonic()
            while time.monotonic() - t0 < 20:
                fa, fb = q_colour.get(), q_mono.get()
                if fa is None or fb is None:
                    continue
                time.sleep(1.5)
                print(f"{time.monotonic()-t0:6.1f} {ae_load(fa):11.3f} "
                      f"{fa.getExposureTime().total_seconds()*1e6:7.0f} "
                      f"{fa.getSensitivity():5d}   {ae_load(fb):11.3f} "
                      f"{fb.getExposureTime().total_seconds()*1e6:7.0f} "
                      f"{fb.getSensitivity():5d}", flush=True)
            print("\nPick --night-load just under the dark reading for CAM_A,\n"
                  "and --day-load comfortably above your lit reading.")
            return 0

        night = args.force == "night"
        stop = {"f": False}
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(s, lambda *_: stop.__setitem__("f", True))

        print(f"day/night: {'FORCED ' + args.force if args.force else 'automatic'}"
              f"   night>={args.night_load:.2f}  day<={args.day_load:.2f}")
        print(f"starting in {'night (mono)' if night else 'day (colour)'} mode")
        print("Ctrl+C to stop\n")

        n = switches = 0
        t0 = last = time.monotonic()
        load = 0.0
        pending = None   # (wanted_mode, since_when) while a change is proving itself
        try:
            while not stop["f"]:
                fa = q_colour.get()
                fb = q_mono.get()
                if fa is None or fb is None:
                    continue
                n += 1

                # CAM_A is always the light meter, even while mono is on screen:
                # it is the one with the IR-cut filter, so it measures visible
                # light rather than whatever infrared happens to be around.
                load = ae_load(fa)
                now_s = time.monotonic()

                # Ignore everything until AE has converged. The first frames
                # carry whatever exposure the sensor booted with: measured here,
                # a dark room reported load 0.07 for a moment before settling to
                # 1.00, which flipped the mode three times in two seconds.
                if now_s - t0 < args.settle:
                    pass
                elif args.force is None:
                    want = None
                    if not night and load >= args.night_load:
                        want = True
                    elif night and load <= args.day_load:
                        want = False

                    if want is None:
                        pending = None          # condition no longer met
                    else:
                        # Require the condition to hold continuously. A drone
                        # panning across the sky or a passing headlight should
                        # not flip the mode; a real sunset will hold easily.
                        if pending is None or pending[0] is not want:
                            pending = (want, now_s)
                        elif now_s - pending[1] >= args.dwell:
                            night, switches = want, switches + 1
                            pending = None
                            print(f"\n-- AE load {load:.2f} held {args.dwell:g}s "
                                  f"-> {'NIGHT (mono)' if night else 'DAY (colour)'}",
                                  flush=True)

                if night:
                    # Replicate the single channel so the display caps never
                    # change when the mode flips.
                    frame = np.repeat(fb.getFrame()[:, :, None], 3, axis=2)
                else:
                    frame = fa.getFrame()
                frame = np.ascontiguousarray(frame)

                now = time.monotonic()
                if args.stats:
                    if now - last >= 1.0:
                        last = now
                        print(f"{n:6d} {n/(now-t0):5.1f} fps  load {load:5.3f}  "
                              f"mode {'night' if night else 'day  '}  "
                              f"mean {frame.mean():6.1f}", flush=True)
                    continue

                buf = Gst.Buffer.new_wrapped(frame.tobytes())
                if appsrc.emit("push-buffer", buf) != Gst.FlowReturn.OK:
                    print("display pipeline closed", file=sys.stderr)
                    break
        finally:
            el = time.monotonic() - t0
            if n:
                print(f"\n{n} frames in {el:.1f}s -> {n/el:.1f} fps, "
                      f"{switches} mode change(s), final AE load {load:.2f}")
            if pipe is not None:
                pipe.set_state(Gst.State.NULL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
