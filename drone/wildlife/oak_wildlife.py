#!/usr/bin/env python3
"""
Wildlife animal/person detection on the OAK-D-S2, with distance per detection.

Step 1 of the wildlife pipeline: a working spatial detector using the
pre-compiled YOLOv6-nano from the Luxonis zoo. Inference runs entirely on the
OAK's MyriadX VPU, so the Jetson SoC stays free - which is what keeps this
inside the 7 W budget.

    # list what the model can actually see
    /home/jetson/oak-venv/bin/python drone/wildlife/oak_wildlife.py --list-classes

    # detect, print distances, save annotated evidence frames
    /home/jetson/oak-venv/bin/python drone/wildlife/oak_wildlife.py

    # only care about things 2-30 m away, higher confidence
    /home/jetson/oak-venv/bin/python drone/wildlife/oak_wildlife.py --min-dist 2 --max-dist 30 --conf 0.6

    # everything the model knows, not just animals/people
    /home/jetson/oak-venv/bin/python drone/wildlife/oak_wildlife.py --all-classes

IMPORTANT LIMITATION
--------------------
YOLOv6-nano is COCO-trained. COCO's entire animal vocabulary is:
    bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe
There is no deer, fox, raccoon, boar, wolf, coyote, bobcat or moose. For real
wildlife work this is a stopgap to prove the pipeline; the target model is
MegaDetector V6 compact (MDV6-yolov10-c), whose species-agnostic "animal"
class fires on any animal. See README.md.

Also: the OAK-D-S2 has a fixed IR-cut filter and no IR illumination, so it is
a daytime sensor. Night coverage needs the IMX219-160 IR-CUT on CAM0.
"""

import argparse
import os
import signal
import sys
import time

MODEL = "luxonis/yolov6-nano:r2-coco-512x288"

# COCO classes that matter for "animals and humans in wildlife".
WILDLIFE = {
    "person",
    "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe",
}


def to_rgb(msg):
    """
    ImgFrame -> (h, w, 3) RGB uint8, without OpenCV.

    The network passthrough is BGR888p, i.e. *planar*: getFrame() hands back a
    2-D (h*3, w) array holding three stacked single-channel planes in B, G, R
    order, not an interleaved image. Indexing it as if it were (h, w, 3) raises
    "too many indices for array". Handle the interleaved and grayscale cases
    too, so this keeps working if the passthrough type ever changes.
    """
    import numpy as np
    a = msg.getFrame()
    w, h = msg.getWidth(), msg.getHeight()
    if a.ndim == 3:                                  # interleaved BGR
        return a[:, :, ::-1]
    if a.shape == (h * 3, w):                        # planar BGR888p
        p = a.reshape(3, h, w)
        return np.stack([p[2], p[1], p[0]], axis=-1)
    if a.shape == (h, w):                            # single channel
        return np.stack([a] * 3, axis=-1)
    raise ValueError(f"unexpected frame {a.shape} for {w}x{h} {msg.getType()}")


def draw(msg, dets, path, labels):
    """Save an annotated evidence frame. Uses PIL; no OpenCV needed."""
    from PIL import Image, ImageDraw
    img = Image.fromarray(to_rgb(msg))
    d = ImageDraw.Draw(img)
    w, h = img.size
    for det in dets:
        x1, y1 = int(det.xmin * w), int(det.ymin * h)
        x2, y2 = int(det.xmax * w), int(det.ymax * h)
        z = det.spatialCoordinates.z / 1000.0
        name = labels[det.label] if det.label < len(labels) else str(det.label)
        d.rectangle([x1, y1, x2, y2], outline=(255, 64, 64), width=2)
        d.text((x1 + 3, max(0, y1 - 11)),
               f"{name} {det.confidence:.0%} {z:.1f}m", fill=(255, 255, 0))
    img.save(path, quality=90)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conf", type=float, default=0.5, help="confidence threshold (default 0.5)")
    ap.add_argument("--fps", type=float, default=10.0,
                    help="inference fps; keep modest on USB 2.0 (default 10)")
    ap.add_argument("--min-dist", type=float, default=0.3, help="metres, range gate low (default 0.3)")
    ap.add_argument("--max-dist", type=float, default=35.0, help="metres, range gate high (default 35)")
    ap.add_argument("--all-classes", action="store_true",
                    help="report every COCO class, not just animals/people")
    ap.add_argument("--frames", type=int, default=0, help="stop after N frames (0 = until Ctrl+C)")
    ap.add_argument("--save-dir", default="/home/jetson/Pictures/wildlife",
                    help="where annotated detections are written")
    ap.add_argument("--no-save", action="store_true", help="console only, save nothing")
    ap.add_argument("--list-classes", action="store_true", help="print model classes and exit")
    ap.add_argument("--preset", default="FAST_ACCURACY",
                    choices=("FAST_ACCURACY", "FAST_DENSITY"),
                    help="stereo preset. Only these two leave enough SHAVE "
                         "cores free for the network (default FAST_ACCURACY)")
    args = ap.parse_args()

    import depthai as dai

    # Cache the model next to the venv so it survives /tmp being wiped.
    os.environ.setdefault("DEPTHAI_ZOO_CACHE_PATH", "/home/jetson/oak-venv/zoo-cache")

    with dai.Pipeline() as pipeline:
        colour = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        left = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_B)
        right = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_C)

        stereo = pipeline.create(dai.node.StereoDepth)
        # SHAVE BUDGET - do not "upgrade" this preset without testing.
        #
        # The MyriadX has 16 SHAVE cores and the zoo's yolov6-nano blob is
        # compiled for 8 of them. StereoDepth, ImageManip and the spatial
        # calculator claim the rest, so the richer presets leave only 7 free
        # and the pipeline refuses to start with:
        #     "Blob compiled for 8 shaves, but only 7 are available"
        # Measured on this device: DEFAULT and ROBOTICS fail, FAST_ACCURACY
        # and FAST_DENSITY start. FAST_ACCURACY is chosen because ranging one
        # distinct animal rewards depth accuracy over depth density.
        stereo.setDefaultProfilePreset(
            getattr(dai.node.StereoDepth.PresetMode, args.preset))
        # Reproject depth into the colour camera's frame so the XYZ attached to
        # each detection refers to the same pixels the network saw.
        stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
        left.requestOutput((640, 400)).link(stereo.left)
        right.requestOutput((640, 400)).link(stereo.right)

        nn = pipeline.create(dai.node.SpatialDetectionNetwork).build(
            colour, stereo, MODEL, fps=args.fps)
        nn.setConfidenceThreshold(args.conf)
        # Hardware range gate: depth outside this band is discarded before the
        # spatial averaging, so far-field noise cannot drag a distance estimate.
        nn.setDepthLowerThreshold(int(args.min_dist * 1000))
        nn.setDepthUpperThreshold(int(args.max_dist * 1000))
        # Average depth over the middle of the box, not its edges, so a halo of
        # background pixels does not skew the reading.
        nn.setBoundingBoxScaleFactor(0.5)

        labels = list(nn.getClasses() or [])
        if args.list_classes:
            print(f"{MODEL}\n{len(labels)} classes:\n")
            for i, n in enumerate(labels):
                mark = "  <-- wildlife" if n in WILDLIFE else ""
                print(f"  {i:3d}  {n}{mark}")
            print(f"\nreported by default: {sorted(WILDLIFE & set(labels))}")
            return 0

        want = set(labels) if args.all_classes else (WILDLIFE & set(labels))
        dq = nn.out.createOutputQueue()
        pq = nn.passthrough.createOutputQueue()

        if not args.no_save:
            os.makedirs(args.save_dir, exist_ok=True)

        stopping = {"flag": False}
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda *_: stopping.__setitem__("flag", True))

        pipeline.start()
        print(f"model   {MODEL}  ({len(labels)} classes)")
        print(f"looking for: {', '.join(sorted(want))}")
        print(f"range gate:  {args.min_dist:.1f} - {args.max_dist:.1f} m   "
              f"conf >= {args.conf:.2f}   {args.fps:g} fps")
        print(f"saving to:   {'(disabled)' if args.no_save else args.save_dir}")
        print("\nCtrl+C to stop\n")

        n = hits = 0
        t0 = time.monotonic()
        while not stopping["flag"] and pipeline.isRunning():
            msg = dq.get()
            if msg is None:
                continue
            n += 1
            frame_msg = pq.tryGet()

            keep = [d for d in msg.detections
                    if (labels[d.label] if d.label < len(labels) else "") in want]
            if keep:
                hits += 1
                ts = time.strftime("%H:%M:%S")
                for d in keep:
                    name = labels[d.label] if d.label < len(labels) else str(d.label)
                    c = d.spatialCoordinates
                    print(f"  [{ts}] {name:<10} {d.confidence:4.0%}  "
                          f"dist {c.z/1000:6.2f} m   "
                          f"X {c.x/1000:+6.2f}  Y {c.y/1000:+6.2f}", flush=True)
                if not args.no_save and frame_msg is not None:
                    p = os.path.join(
                        args.save_dir,
                        f"{time.strftime('%Y%m%d-%H%M%S')}-{hits:04d}.jpg")
                    try:
                        draw(frame_msg, keep, p, labels)
                    except Exception as e:                     # noqa: BLE001
                        print(f"  (could not save frame: {e})", file=sys.stderr)

            if n % 50 == 0:
                el = time.monotonic() - t0
                print(f"  ... {n} frames, {n/el:.1f} fps, {hits} frames with "
                      f"detections", flush=True)

            if args.frames and n >= args.frames:
                break

        el = time.monotonic() - t0
        print(f"\n{n} frames in {el:.1f}s -> {n/el:.1f} fps; "
              f"{hits} frames contained a target")
    return 0


if __name__ == "__main__":
    sys.exit(main())
