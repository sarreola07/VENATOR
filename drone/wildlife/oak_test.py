#!/usr/bin/env python3
"""
Prove the OAK-D-S2 actually streams: grab frames from the colour camera and
optionally the stereo depth pair, report throughput, save a still.

    /home/jetson/oak-venv/bin/python drone/wildlife/oak_test.py
    /home/jetson/oak-venv/bin/python drone/wildlife/oak_test.py --depth --frames 60

This is deliberately conservative about resolution. The device negotiated
UsbSpeed.HIGH (USB 2.0, 480 Mbps), which is the real throughput ceiling here -
a 12 MP stream would not fit. Move it to the USB 3.0 hub to lift that.
"""

import argparse
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=30, help="frames to grab (default 30)")
    ap.add_argument("--size", default="640x480", help="colour output WxH (default 640x480)")
    ap.add_argument("--depth", action="store_true", help="also run the stereo depth pair")
    ap.add_argument("--out", default="/home/jetson/Pictures", help="where to save the still")
    args = ap.parse_args()

    try:
        w, h = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        print(f"error: --size must look like 640x480, got {args.size!r}", file=sys.stderr)
        return 2

    import depthai as dai
    import numpy as np

    print(f"depthai {dai.__version__}")

    with dai.Pipeline() as pipeline:
        cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        # BGR888i gives an interleaved 3-channel frame, the same layout as the
        # IMX219 path, so downstream code can be shared.
        colour = cam.requestOutput((w, h), dai.ImgFrame.Type.BGR888i)
        cq = colour.createOutputQueue()

        dq = None
        if args.depth:
            left = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_B)
            right = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_C)
            stereo = pipeline.create(dai.node.StereoDepth)
            left.requestOutput((640, 400)).link(stereo.left)
            right.requestOutput((640, 400)).link(stereo.right)
            dq = stereo.depth.createOutputQueue()

        pipeline.start()
        print(f"streaming {w}x{h} BGR"
              f"{' + stereo depth 640x400' if args.depth else ''} ...")

        n, t0, first = 0, time.monotonic(), None
        while n < args.frames and pipeline.isRunning():
            pkt = cq.get()
            if pkt is None:
                continue
            frame = pkt.getFrame()
            if first is None:
                first = frame
            n += 1
            if n % 10 == 0:
                print(f"  {n:4d} frames  {n/(time.monotonic()-t0):5.1f} fps  "
                      f"shape={frame.shape}  mean={frame.mean():5.1f}")

        el = time.monotonic() - t0
        print(f"\ncolour: {n} frames in {el:.2f}s -> {n/el:.1f} fps")

        if dq is not None:
            d = dq.tryGet()
            if d is not None:
                dm = d.getFrame()
                valid = dm[dm > 0]
                print(f"depth:  {dm.shape} uint16 mm, {valid.size} valid px")
                if valid.size:
                    print(f"        range {valid.min()} - {valid.max()} mm, "
                          f"median {int(np.median(valid))} mm")
            else:
                print("depth:  no packet yet (stereo needs a moment to converge)")

        if first is not None:
            import os
            os.makedirs(args.out, exist_ok=True)
            path = os.path.join(args.out, f"oak-{time.strftime('%Y%m%d-%H%M%S')}.jpg")
            try:
                from PIL import Image
                Image.fromarray(first[:, :, ::-1]).save(path)   # BGR -> RGB
                print(f"saved {path}")
            except ModuleNotFoundError:
                print("Pillow not available; skipping the still")

    return 0


if __name__ == "__main__":
    sys.exit(main())
