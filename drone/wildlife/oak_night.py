#!/usr/bin/env python3
"""
Night-vision live view from the OAK-D-S2's mono cameras.

    /home/jetson/oak-venv/bin/python oak_night.py            # both monos, side by side
    /home/jetson/oak-venv/bin/python oak_night.py --cam B    # just the left one
    /home/jetson/oak-venv/bin/python oak_night.py --iso 1600 --exposure-us 30000
    /home/jetson/oak-venv/bin/python oak_night.py --stats    # numbers, no window

WHY THE MONO CAMERAS
--------------------
The OAK-D-S2 has three sensors and they are not equally useful in the dark.
Measured on this unit at an identical locked exposure (1500 us, ISO 200) in a
dark room:

    CAM_A  IMX378 colour     22
    CAM_B  OV9282 mono      132
    CAM_C  OV9282 mono      131

Roughly 6x more signal from the monos. Two reasons: no Bayer colour filter
throwing away two thirds of the light, and OmniVision rate the OV9282 as
"best-in-class near-infrared quantum efficiency". The colour camera also
carries an IR-cut filter; the monos, on the evidence of the OAK-D-PRO
illuminating these same sensors at 940 nm, do not.

WHAT THIS CANNOT DO
-------------------
There are no IR emitters on the S2 - the device reports getIrDrivers() == [].
This makes the OAK far more sensitive in low light, but it is still a passive
sensor: it needs *some* light. In a sealed, truly black room it will show
amplified noise, exactly as any camera would. Add an IR illuminator and the
mono pair becomes genuinely useful.

Rendering goes through GStreamer rather than OpenCV, matching the CSI camera
path, so nothing extra has to be installed.
"""

import argparse
import sys
import time

CAMS = {"B": "CAM_B", "C": "CAM_C"}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cam", choices=("B", "C", "both"), default="both",
                    help="which mono camera to show (default both, side by side)")
    ap.add_argument("--width", type=int, default=640, help="per-camera width (default 640)")
    ap.add_argument("--height", type=int, default=400, help="per-camera height (default 400)")
    ap.add_argument("--fps", type=float, default=25.0, help="display rate (default 25)")
    ap.add_argument("--iso", type=int, default=0,
                    help="fixed sensitivity 100-1600; 0 = auto-exposure (default 0)")
    ap.add_argument("--exposure-us", type=int, default=0,
                    help="fixed exposure us; 0 = auto (default 0). Long exposures "
                         "brighten a dark scene but smear anything moving.")
    ap.add_argument("--sink", default="nv3dsink",
                    choices=("nv3dsink", "xvimagesink", "ximagesink"),
                    help="video sink (default nv3dsink)")
    ap.add_argument("--stats", action="store_true",
                    help="print brightness numbers instead of opening a window")
    args = ap.parse_args()

    import depthai as dai
    import numpy as np

    socks = list(CAMS.values()) if args.cam == "both" else [CAMS[args.cam]]
    w, h = args.width, args.height
    out_w = w * len(socks)

    pipe = None
    appsrc = None
    if not args.stats:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        # GRAY8 in. nv3dsink needs NVMM, so nvvidconv does that hop - but the
        # format between videoconvert and nvvidconv must be pinned explicitly.
        # Left to negotiate freely it picks something nvvidconv rejects with
        # "gst_nvvconv_transform: Transform not supported".
        if args.sink == "nv3dsink":
            tail = ("videoconvert ! video/x-raw,format=I420 "
                    "! nvvidconv ! video/x-raw(memory:NVMM) ! nv3dsink sync=false")
        else:
            tail = f"videoconvert ! {args.sink} sync=false"
        desc = (f"appsrc name=src is-live=true format=time "
                f"caps=video/x-raw,format=GRAY8,width={out_w},height={h},"
                f"framerate={int(args.fps)}/1 "
                f"! {tail}")
        print(f"pipeline: {desc}\n")
        pipe = Gst.parse_launch(desc)
        appsrc = pipe.get_by_name("src")
        if pipe.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            print("error: display pipeline failed to start", file=sys.stderr)
            return 1

    with dai.Pipeline() as pipeline:
        queues = {}
        for sock in socks:
            cam = pipeline.create(dai.node.Camera).build(
                getattr(dai.CameraBoardSocket, sock))
            if args.iso and args.exposure_us:
                cam.initialControl.setManualExposure(args.exposure_us, args.iso)
            queues[sock] = cam.requestOutput(
                (w, h), dai.ImgFrame.Type.GRAY8).createOutputQueue()

        pipeline.start()
        mode = (f"manual {args.exposure_us} us ISO {args.iso}"
                if (args.iso and args.exposure_us) else "auto-exposure")
        print(f"night view: {', '.join(socks)}  {w}x{h}  {mode}")
        print("Ctrl+C to stop\n")

        import signal
        stop = {"f": False}
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(s, lambda *_: stop.__setitem__("f", True))

        n, t0, last = 0, time.monotonic(), 0.0
        try:
            while not stop["f"]:
                frames = []
                for sock in socks:
                    pkt = queues[sock].get()
                    if pkt is None:
                        break
                    frames.append(pkt.getFrame())
                if len(frames) != len(socks):
                    continue
                # Frames arrive as (h, w) GRAY8; hstack puts the pair side by side.
                canvas = np.hstack(frames) if len(frames) > 1 else frames[0]
                canvas = np.ascontiguousarray(canvas)
                n += 1

                if args.stats:
                    now = time.monotonic()
                    if now - last >= 1.0:
                        last = now
                        parts = "  ".join(
                            f"{s}: mean {f.mean():6.1f} std {f.std():5.1f} "
                            f"max {f.max():3d}" for s, f in zip(socks, frames))
                        print(f"{n:5d}  {n/(now-t0):4.1f} fps   {parts}", flush=True)
                    continue

                from gi.repository import Gst
                buf = Gst.Buffer.new_wrapped(canvas.tobytes())
                if appsrc.emit("push-buffer", buf) != Gst.FlowReturn.OK:
                    print("display pipeline closed", file=sys.stderr)
                    break
        finally:
            el = time.monotonic() - t0
            if n:
                print(f"\n{n} frames in {el:.1f}s -> {n/el:.1f} fps")
            if pipe is not None:
                from gi.repository import Gst
                pipe.set_state(Gst.State.NULL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
