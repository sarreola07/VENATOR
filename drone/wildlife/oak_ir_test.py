#!/usr/bin/env python3
"""
Can the OAK see infrared? Test all three sensors at once.

    /home/jetson/oak-venv/bin/python oak_ir_test.py
    /home/jetson/oak-venv/bin/python oak_ir_test.py --seconds 20 --save-dir /tmp/ir

WHY THIS EXISTS
---------------
The OAK-D-S2 has three sensors with different spectral behaviour:

    CAM_A  IMX378  colour   - almost certainly has a fixed IR-cut filter
    CAM_B  OV9282  mono     - OmniVision rate it "best-in-class NIR QE"
    CAM_C  OV9282  mono     - same

The mono pair is the interesting part. The OAK-D-PRO illuminates these exact
sensors with its 940 nm flood LED and dot projector, which only works if they
have no IR-cut filter. If that holds for the S2 too, the mono cameras can see
an 850/940 nm laser even though the colour camera cannot.

HOW TO RUN IT
-------------
Grab any TV / set-top-box remote. Point it at the OAK from ~20 cm and hold a
button down. Watch the live numbers:

    * mono brightness jumps, colour does not  -> monos see IR, colour is filtered
    * all three jump                          -> nothing is filtered
    * nothing moves                           -> remote is dead, or aim is off

A remote emits 940 nm, the same band as the OAK-D-Pro's flood LED and close
enough to an 850 nm laser to answer the question. IR is invisible to you, so
trust the numbers, not your eyes.
"""

import argparse
import os
import sys
import time

SOCKETS = ("CAM_A", "CAM_B", "CAM_C")
LABEL = {"CAM_A": "IMX378 colour", "CAM_B": "OV9282 mono L", "CAM_C": "OV9282 mono R"}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=25.0,
                    help="how long to sample (default 25)")
    ap.add_argument("--exposure-us", type=int, default=1500,
                    help="fixed exposure in microseconds (default 1500)")
    ap.add_argument("--iso", type=int, default=200,
                    help="fixed sensitivity (default 200)")
    ap.add_argument("--settle", type=float, default=3.0,
                    help="seconds to discard before taking the baseline (default 3)")
    ap.add_argument("--save-dir", default="/home/jetson/Pictures/ir-test",
                    help="where the brightest and darkest frames are written")
    args = ap.parse_args()

    import depthai as dai
    import numpy as np

    with dai.Pipeline() as pipeline:
        queues = {}
        for sock in SOCKETS:
            cam = pipeline.create(dai.node.Camera).build(
                getattr(dai.CameraBoardSocket, sock))
            # LOCK EXPOSURE AND GAIN. With auto-exposure running, every sensor
            # drives itself toward mid-grey and a brightness reading says
            # nothing about how much light actually arrived - the first version
            # of this test reported the monos pinned at 254 and the colour
            # camera "rising" 110 counts with no IR in the room at all.
            # Fixed exposure is what makes the comparison mean something.
            cam.initialControl.setManualExposure(args.exposure_us, args.iso)
            # Ask every sensor for the same interleaved BGR so one code path
            # handles all three; the monos simply come back grey.
            out = cam.requestOutput((640, 400), dai.ImgFrame.Type.BGR888i)
            queues[sock] = out.createOutputQueue()

        pipeline.start()
        print(f"exposure locked at {args.exposure_us} us, ISO {args.iso}")
        print("Point a TV remote at the OAK and hold a button down.\n")
        print(f"{'time':>6}  " + "  ".join(f"{LABEL[s]:>14}" for s in SOCKETS))
        print(f"{'':>6}  " + "  ".join(f"{'mean bright':>14}" for _ in SOCKETS))
        print("-" * 60)

        settling = {s: [] for s in SOCKETS}
        base = {s: None for s in SOCKETS}
        peak = {s: 0.0 for s in SOCKETS}
        best = {s: None for s in SOCKETS}
        t0 = time.monotonic()
        last = 0.0

        while time.monotonic() - t0 < args.seconds:
            row = {}
            elapsed = time.monotonic() - t0
            for sock, q in queues.items():
                pkt = q.tryGet()
                if pkt is None:
                    continue
                f = pkt.getFrame()
                m = float(f.mean())
                row[sock] = m
                # Collect a settling window first, then take the baseline as
                # its median. A single first frame is not a baseline: the
                # pipeline is still starting and the numbers are garbage.
                if elapsed < args.settle:
                    settling[sock].append(m)
                    continue
                if base[sock] is None:
                    base[sock] = (float(np.median(settling[sock]))
                                  if settling[sock] else m)
                if m > peak[sock]:
                    peak[sock] = m
                    best[sock] = f.copy()
            now = elapsed
            if row and now - last >= 0.5:
                last = now
                cells = []
                for s in SOCKETS:
                    v = row.get(s)
                    cells.append(f"{v:14.1f}" if v is not None else f"{'-':>14}")
                print(f"{now:6.1f}  " + "  ".join(cells), flush=True)

        print("\n" + "=" * 60)
        print(f"{'sensor':<16} {'baseline':>9} {'peak':>9} {'rise':>9}   verdict")
        print("-" * 60)
        verdicts = {}
        for s in SOCKETS:
            b, p = base[s], peak[s]
            if b is None:
                print(f"{LABEL[s]:<16} {'no data':>9}")
                continue
            rise = p - b
            # A 5-count rise on a 0-255 scale is well clear of sensor noise,
            # which sat around 0.5 counts when this was characterised.
            saw = rise > 5.0
            verdicts[s] = saw
            print(f"{LABEL[s]:<16} {b:9.1f} {p:9.1f} {rise:+9.1f}   "
                  f"{'SEES IR' if saw else 'no response'}")

        print()
        mono = [verdicts.get("CAM_B"), verdicts.get("CAM_C")]
        colour = verdicts.get("CAM_A")
        if any(mono) and not colour:
            print("The mono pair sees infrared and the colour camera does not.")
            print("That is the expected result: the OV9282s have no IR-cut")
            print("filter, the IMX378 does. Your OAK CAN see an IR laser, but")
            print("only on CAM_B/CAM_C, and only in grayscale.")
        elif any(mono) and colour:
            print("All three responded. Nothing is IR-filtered on this unit.")
        elif not any(mono) and not colour:
            print("Nothing responded. Either the remote is flat, it was not")
            print("aimed at the lenses, or it was too far away. Retry at 10-20 cm.")
        else:
            print("Only the colour camera responded, which is unexpected.")
            print("Re-run before drawing any conclusion from it.")

        if args.save_dir:
            os.makedirs(args.save_dir, exist_ok=True)
            from PIL import Image
            for s in SOCKETS:
                if best[s] is None:
                    continue
                p = os.path.join(args.save_dir, f"{s}-brightest.jpg")
                Image.fromarray(best[s][:, :, ::-1]).save(p)
            print(f"\nBrightest frame from each sensor saved to {args.save_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
