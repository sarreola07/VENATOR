#!/usr/bin/env python3
"""
Wildlife animal/person detection on the OAK-D-S2, with distance per detection.

A spatial detector running MegaDetector V6 from the Luxonis zoo. Inference runs
entirely on the OAK's MyriadX VPU, so the Jetson SoC stays free - which is what
keeps this inside the 7 W budget.

    # list the model's classes and the confidence each one needs
    /home/jetson/oak-venv/bin/python drone/wildlife/oak_wildlife.py --list-classes

    # detect, print distances, save annotated evidence frames
    /home/jetson/oak-venv/bin/python drone/wildlife/oak_wildlife.py

    # only care about things 2-30 m away
    /home/jetson/oak-venv/bin/python drone/wildlife/oak_wildlife.py --min-dist 2 --max-dist 30

    # the old COCO baseline, for comparison
    /home/jetson/oak-venv/bin/python drone/wildlife/oak_wildlife.py \
        --model luxonis/yolov6-nano:r2-coco-512x288 --raw-classes

THE MODEL
---------
MegaDetector V6 compact (MDV6-yolov10-c, Microsoft AI for Good) reports three
species-agnostic classes - animal, person, vehicle - and is trained on millions
of camera-trap images. Species-agnostic is the feature, not a compromise: it
cannot mistake a javelina for a sheep because it has no sheep class.

It replaced COCO YOLOv6-nano, which had no deer, hog, coyote, bobcat, javelina
or armadillo class and whose failure was not merely absence but confident
error - measured on the 89 frames in ~/Pictures/wildlife, 25 of its 26
detections at conf 0.5 were "traffic light" at 61% mean confidence, firing on
warehouse ceiling lights. See classes.py for the policy that supersedes it.

Measured on this OAK, same pipeline as below, FAST_ACCURACY:
    MegaDetector V6  65.0 ms/inference, ceiling 15.4 fps, holds 10 fps
    yolov6-nano      33.3 ms/inference, ceiling >30 fps
Both take a 512x288 NCHW BGR input with identical preprocessing, so --model
switches between them with no other change.

Still unproven: animal *recall* from the air. MegaDetector is trained on
ground-level camera-trap imagery and this is a downward-looking drone, so the
numbers above say it runs, not that it sees. That needs field imagery at
15/25/35 m AGL. At 512x288 a javelina spans ~22 px at 15 m and ~11 px at 30 m,
and a YOLO stride-8 head wants 16-20 px, so fly wildlife low (15-25 m) and
save the altitude for person-sized targets.

Also: the OAK-D-S2 has a fixed IR-cut filter and no IR illumination, so it is
a daytime sensor. Night coverage needs the IMX219-160 IR-CUT on CAM0.
"""

import argparse
import os
import signal
import sys
import time

import classes

MODEL = "luxonis/wildlife-megadetector:mdv6-yolov10-c"

# Recompile the network for 5 SHAVE cores rather than taking the archive's
# default. Measured, 18 s windows, FAST_ACCURACY, this device:
#     default  15.3 fps   65.2 ms/inference
#     4 shaves 19.7 fps
#     5 shaves 22.3 fps   44.9 ms   <-- +45% over the default, for one flag
#     6 shaves 13.4 fps   74.7 ms
#     8 shaves 15.4 fps
# Note it is NOT monotonic: 6 is worse than 4, and more shaves is not better.
# Stage count does not predict it either (6 shaves compiles to fewer stages
# than 5 and still runs slower), so this is SHAVE/CMX tiling behaviour that
# has to be measured per model. Re-run the sweep if the model changes.
DEFAULT_SHAVES = 5


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


def draw(msg, named_dets, path):
    """
    Save an annotated evidence frame. Uses PIL; no OpenCV needed.

    Takes (detection, display_name) pairs rather than raw labels so the frame
    is captioned with what classes.py decided to report, not the model's own
    label - otherwise a COCO stand-in would burn "sheep" into the evidence.
    """
    from PIL import Image, ImageDraw
    img = Image.fromarray(to_rgb(msg))
    d = ImageDraw.Draw(img)
    w, h = img.size
    for det, name in named_dets:
        x1, y1 = int(det.xmin * w), int(det.ymin * h)
        x2, y2 = int(det.xmax * w), int(det.ymax * h)
        z = det.spatialCoordinates.z / 1000.0
        d.rectangle([x1, y1, x2, y2], outline=(255, 64, 64), width=2)
        d.text((x1 + 3, max(0, y1 - 11)),
               f"{name} {det.confidence:.0%} {z:.1f}m", fill=(255, 255, 0))
    img.save(path, quality=90)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=MODEL, help=f"HubAI model id (default {MODEL})")
    ap.add_argument("--conf", type=float, default=None,
                    help="override every per-class threshold in classes.py with "
                         "one global value; normally leave this alone")
    ap.add_argument("--fps", type=float, default=10.0,
                    help="inference fps; keep modest on USB 2.0 (default 10)")
    ap.add_argument("--min-dist", type=float, default=0.3, help="metres, range gate low (default 0.3)")
    ap.add_argument("--max-dist", type=float, default=35.0, help="metres, range gate high (default 35)")
    ap.add_argument("--all-classes", action="store_true",
                    help="report every class the model has, bypassing classes.py")
    ap.add_argument("--raw-classes", action="store_true",
                    help="also show the model's own label, e.g. 'animal:sheep'")
    ap.add_argument("--frames", type=int, default=0, help="stop after N frames (0 = until Ctrl+C)")
    ap.add_argument("--save-dir", default="/home/jetson/Pictures/wildlife",
                    help="where annotated detections are written")
    ap.add_argument("--no-save", action="store_true", help="console only, save nothing")
    ap.add_argument("--list-classes", action="store_true",
                    help="print the model's classes and their thresholds, then exit")
    ap.add_argument("--resize", default="crop", choices=("crop", "letterbox", "stretch"),
                    help="how the camera frame is fitted to the network input. "
                         "Keep 'crop' (default): the sensor is 4:3 and the net "
                         "is 16:9, so letterboxing would spend 25%% of the "
                         "input tensor on grey bars, and pixels-on-target is "
                         "the binding constraint for small aerial targets. "
                         "test_detector.py defaults to the same thing so "
                         "offline results predict flight")
    ap.add_argument("--shaves", type=int, default=DEFAULT_SHAVES,
                    help=f"recompile the network for N SHAVE cores (default "
                         f"{DEFAULT_SHAVES}, measured fastest; 0 = leave the "
                         f"archive's default). Not monotonic - see DEFAULT_SHAVES")
    ap.add_argument("--preset", default="FAST_ACCURACY",
                    choices=("FAST_ACCURACY", "FAST_DENSITY", "DEFAULT", "ROBOTICS"),
                    help="stereo preset (default FAST_ACCURACY). DEFAULT and "
                         "ROBOTICS only fit at --shaves 4-6; they refuse to "
                         "start at 8 or at the archive default")
    args = ap.parse_args()

    import depthai as dai

    # Cache the model next to the venv so it survives /tmp being wiped.
    os.environ.setdefault("DEPTHAI_ZOO_CACHE_PATH", "/home/jetson/oak-venv/zoo-cache")

    with dai.Pipeline() as pipeline:
        colour = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        left = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_B)
        right = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_C)

        stereo = pipeline.create(dai.node.StereoDepth)
        # SHAVE BUDGET - a knob, not a wall.
        #
        # The MyriadX has 16 SHAVE cores. StereoDepth, ImageManip and the
        # spatial calculator claim some, and the network claims the rest; the
        # richer stereo presets leave only 7 free, so a network compiled for 8
        # refuses to start with:
        #     "Blob compiled for 8 shaves, but only 7 are available"
        # That is a real symptom and it is why FAST_ACCURACY is the default.
        #
        # But the zoo ships a *superblob*, not a blob: it recompiles on the
        # host for whatever shave count you ask for, so the fix is --shaves
        # rather than giving up on a preset. Measured on this device, fps at
        # 30 fps requested, 6 s per cell (SHAVE = refused to start):
        #
        #     preset          dflt     4     5     6     8
        #     FAST_ACCURACY   15.3  19.7  22.1  13.4  15.4
        #     FAST_DENSITY    15.4  19.6  22.2  13.4  15.4
        #     DEFAULT        SHAVE   11.5  14.1  12.9  SHAVE
        #     ROBOTICS       SHAVE   11.5  14.2  12.9  SHAVE
        #
        # Three things fall out of that table:
        #   - DEFAULT and ROBOTICS *do* work, at 4-6 shaves. The old claim that
        #     they simply fail was true only at the archive's default count.
        #   - The richer presets cost ~36% of the frame rate (14.1 vs 22.1 at
        #     5 shaves), and still clear a 10 fps target with headroom.
        #   - FAST_ACCURACY and FAST_DENSITY are identical in throughput, so
        #     choose between them on depth quality alone. FAST_ACCURACY is the
        #     default because ranging one distinct animal rewards depth
        #     accuracy over depth density.
        stereo.setDefaultProfilePreset(
            getattr(dai.node.StereoDepth.PresetMode, args.preset))
        # Reproject depth into the colour camera's frame so the XYZ attached to
        # each detection refers to the same pixels the network saw.
        stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
        left.requestOutput((640, 400)).link(stereo.left)
        right.requestOutput((640, 400)).link(stereo.right)

        # Build the archive ourselves rather than handing build() a model id,
        # so --shaves can reach the superblob underneath it.
        desc = dai.NNModelDescription(args.model)
        desc.platform = "RVC2"
        archive = dai.NNArchive(dai.getModelFromZoo(desc))

        # Be explicit about the resize mode. The library default is CROP, which
        # is what we want, but leaving it implicit meant this path and
        # test_detector.py silently disagreed about framing.
        nn = pipeline.create(dai.node.SpatialDetectionNetwork).build(
            colour, stereo, archive, fps=args.fps,
            resizeMode=getattr(dai.ImgResizeMode, args.resize.upper()))
        if args.shaves:
            nn.setBlob(archive.getSuperBlob().getBlobWithNumShaves(args.shaves))
        # Hardware range gate: depth outside this band is discarded before the
        # spatial averaging, so far-field noise cannot drag a distance estimate.
        nn.setDepthLowerThreshold(int(args.min_dist * 1000))
        nn.setDepthUpperThreshold(int(args.max_dist * 1000))
        # Average depth over the middle of the box, not its edges, so a halo of
        # background pixels does not skew the reading.
        nn.setBoundingBoxScaleFactor(0.5)

        labels = list(nn.getClasses() or [])

        # The device filter runs before classify() ever sees a detection, so it
        # has to sit at the *lowest* per-class threshold or the hardware
        # silently eats animals the policy would have kept.
        floor = classes.device_floor(labels, args.conf)
        nn.setConfidenceThreshold(0.0 if args.all_classes else floor)

        if args.list_classes:
            print(f"{args.model}\n{len(labels)} classes:\n")
            for i, n in enumerate(labels):
                entry = classes.CLASS_POLICY.get(n)
                mark = f"  <-- {entry[0]} @ {entry[1]:.2f}" if entry else ""
                print(f"  {i:3d}  {n}{mark}")
            print(f"\npolicy (classes.py):\n{classes.describe(labels)}")
            print(f"\nreported as: {', '.join(classes.coarse_classes(labels))}")
            print(f"device threshold: {floor:.2f}")
            return 0

        dq = nn.out.createOutputQueue()
        pq = nn.passthrough.createOutputQueue()

        if not args.no_save:
            os.makedirs(args.save_dir, exist_ok=True)

        stopping = {"flag": False}
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, lambda *_: stopping.__setitem__("flag", True))

        pipeline.start()
        print(f"model   {args.model}  ({len(labels)} classes)")
        if args.all_classes:
            print("looking for: everything (classes.py bypassed)")
        elif args.conf is not None:
            print(f"looking for: {', '.join(classes.coarse_classes(labels))}   "
                  f"at a forced conf >= {args.conf:.2f}")
        else:
            print(f"looking for: {', '.join(classes.coarse_classes(labels))}   "
                  f"(per-class thresholds, device floor {floor:.2f})")
        print(f"range gate:  {args.min_dist:.1f} - {args.max_dist:.1f} m   "
              f"{args.fps:g} fps   resize {args.resize}"
              f"{f'   {args.shaves} shaves' if args.shaves else ''}")
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

            # (detection, display name) pairs, so the console, the evidence
            # frame and anything downstream all agree on the wording.
            keep = []
            for d in msg.detections:
                raw = labels[d.label] if d.label < len(labels) else str(d.label)
                if args.all_classes:
                    verdict = (raw, raw)
                elif args.conf is not None:
                    verdict = (raw, raw) if d.confidence >= args.conf else None
                else:
                    verdict = classes.classify(raw, d.confidence)
                if verdict is None:
                    continue
                reported, raw = verdict
                keep.append((d, classes.report_name(reported, raw, args.raw_classes)))

            if keep:
                hits += 1
                ts = time.strftime("%H:%M:%S")
                for d, name in keep:
                    c = d.spatialCoordinates
                    print(f"  [{ts}] {name:<14} {d.confidence:4.0%}  "
                          f"dist {c.z/1000:6.2f} m   "
                          f"X {c.x/1000:+6.2f}  Y {c.y/1000:+6.2f}", flush=True)
                if not args.no_save and frame_msg is not None:
                    p = os.path.join(
                        args.save_dir,
                        f"{time.strftime('%Y%m%d-%H%M%S')}-{hits:04d}.jpg")
                    try:
                        draw(frame_msg, keep, p)
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
