#!/usr/bin/env python3
"""
Run the OAK detector over image files instead of the live camera.

This is how you find out what the model can actually see before you fly it.
Drop Texas wildlife photos into a folder and run:

    V=/home/jetson/oak-venv/bin/python
    $V drone/wildlife/test_detector.py ~/Pictures/testset/
    $V drone/wildlife/test_detector.py ~/Pictures/testset/ --conf 0.15 --save-dir /tmp/out

Images are fed to the real network on the real MyriadX through a host input
queue, so the result is exactly what the drone would produce in flight - not a
desktop approximation.

Reading the output
------------------
A blank result is a result. The default model reports three species-agnostic
classes - animal, person, vehicle - so it will not name the species; "animal"
on a javelina is a correct answer. classes.py decides the confidence each
class needs and suppresses the rest.

Run it against the COCO baseline to see the difference:

    $V drone/wildlife/test_detector.py ~/Pictures/wildlife \\
        --model luxonis/yolov6-nano:r2-coco-512x288 --raw-classes

Matching what flies
-------------------
--resize defaults to 'crop', which is what oak_wildlife.py uses, so results
here predict in-flight behaviour. That was not always true: this harness used
to letterbox while the live path cropped, so the two disagreed about framing.
Use --resize letterbox only to measure that difference deliberately.
"""

import argparse
import os
import sys
import time

import classes

MODEL = "luxonis/wildlife-megadetector:mdv6-yolov10-c"

# Match oak_wildlife.py's shave count. Nothing here competes with stereo for
# cores, so this is not about fitting - it is about the two paths differing in
# as few ways as possible, which is the same reason --resize defaults to crop.
DEFAULT_SHAVES = 5

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def fit(img, size, mode):
    """
    Fit an image to the model's input box the way the device would.

    Returns (rgb, scale, pad_x, pad_y) so detections can be mapped back onto
    the original image. Pad values are negative for 'crop', where pixels are
    discarded rather than added - the same inverse mapping then works for all
    three modes.

      crop      scale to cover, centre-crop the overflow. Keeps the full
                sensor width at full resolution; loses 25% of a 4:3 frame's
                height into a 16:9 net. This is the device default.
      letterbox scale to fit, pad with grey. Keeps the whole field of view but
                spends 25% of the input tensor on bars, so a distant animal
                lands on fewer pixels.
      stretch   squash to fit. Distorts body proportions, which is the cue the
                detector relies on. Here for completeness.
    """
    from PIL import Image
    tw, th = size
    w, h = img.size
    if mode == "stretch":
        return img.resize((tw, th), Image.BILINEAR), (tw / w, th / h), 0, 0
    pick = max if mode == "crop" else min
    scale = pick(tw / w, th / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = img.resize((nw, nh), Image.BILINEAR)
    px, py = (tw - nw) // 2, (th - nh) // 2
    if mode == "crop":
        # px, py are <= 0 here; crop the centre out of the oversized image.
        canvas = resized.crop((-px, -py, -px + tw, -py + th))
    else:
        canvas = Image.new("RGB", (tw, th), (114, 114, 114))
        canvas.paste(resized, (px, py))
    return canvas, (scale, scale), px, py


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="image file, or a directory of images")
    ap.add_argument("--conf", type=float, default=None,
                    help="override every per-class threshold in classes.py with "
                         "one global value; try 0.15 to see near-misses")
    ap.add_argument("--all-classes", action="store_true",
                    help="report every class the model has, bypassing classes.py")
    ap.add_argument("--raw-classes", action="store_true",
                    help="also show the model's own label, e.g. 'animal:sheep'")
    ap.add_argument("--save-dir", help="write annotated copies here")
    ap.add_argument("--model", default=MODEL, help=f"HubAI model id (default {MODEL})")
    ap.add_argument("--resize", default="crop", choices=("crop", "letterbox", "stretch"),
                    help="how images are fitted to the network input. Default "
                         "'crop' matches oak_wildlife.py, so results here "
                         "predict flight")
    ap.add_argument("--shaves", type=int, default=DEFAULT_SHAVES,
                    help=f"recompile the network for N SHAVE cores (default "
                         f"{DEFAULT_SHAVES}, matching the live path; 0 = archive default)")
    args = ap.parse_args()

    import depthai as dai
    import numpy as np
    from PIL import Image, ImageDraw

    os.environ.setdefault("DEPTHAI_ZOO_CACHE_PATH", "/home/jetson/oak-venv/zoo-cache")

    if os.path.isdir(args.path):
        files = sorted(os.path.join(args.path, f) for f in os.listdir(args.path)
                       if f.lower().endswith(IMAGE_EXT))
    elif os.path.isfile(args.path):
        files = [args.path]
    else:
        print(f"error: no such file or directory: {args.path}", file=sys.stderr)
        return 2
    if not files:
        print(f"error: no images ({', '.join(IMAGE_EXT)}) in {args.path}", file=sys.stderr)
        return 2

    desc = dai.NNModelDescription(args.model)
    desc.platform = "RVC2"
    archive = dai.NNArchive(dai.getModelFromZoo(desc))
    iw, ih = archive.getInputSize()

    with dai.Pipeline() as pipeline:
        nn = pipeline.create(dai.node.DetectionNetwork)
        nn.setNNArchive(archive)
        if args.shaves:
            nn.setBlob(archive.getSuperBlob().getBlobWithNumShaves(args.shaves))
        qin = nn.input.createInputQueue()
        qout = nn.out.createOutputQueue()

        labels = list(nn.getClasses() or [])
        # Same reasoning as oak_wildlife.py: the device filter sits at the
        # lowest per-class threshold so the host policy gets to see everything
        # it might want to keep.
        floor = classes.device_floor(labels, args.conf)
        nn.setConfidenceThreshold(0.0 if args.all_classes else floor)
        pipeline.start()

        print(f"model  {args.model}")
        print(f"input  {iw}x{ih}   resize {args.resize}"
              f"{f'   {args.shaves} shaves' if args.shaves else ''}")
        if args.all_classes:
            print(f"report everything ({len(labels)} classes, classes.py bypassed)\n")
        elif args.conf is not None:
            print(f"report {', '.join(classes.coarse_classes(labels))}   "
                  f"at a forced conf >= {args.conf:.2f}\n")
        else:
            print(f"report {', '.join(classes.coarse_classes(labels))}   "
                  f"(per-class thresholds, device floor {floor:.2f})")
            print(f"{classes.describe(labels)}\n")

        if args.save_dir:
            os.makedirs(args.save_dir, exist_ok=True)

        hits = misses = 0
        tally = {}
        for path in files:
            img = Image.open(path).convert("RGB")
            boxed, (sx, sy), px, py = fit(img, (iw, ih), args.resize)

            # BGR888p is planar: three stacked single-channel planes, B first.
            rgb = np.asarray(boxed, dtype=np.uint8)
            planar = np.ascontiguousarray(rgb[:, :, ::-1].transpose(2, 0, 1))

            frame = dai.ImgFrame()
            frame.setData(planar.tobytes())
            frame.setType(dai.ImgFrame.Type.BGR888p)
            frame.setWidth(iw)
            frame.setHeight(ih)
            qin.send(frame)

            msg = qout.get()
            dets = []
            for d in (msg.detections if msg else []):
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
                dets.append((d, classes.report_name(reported, raw, args.raw_classes)))
                tally[reported] = tally.get(reported, 0) + 1

            name = os.path.basename(path)
            if dets:
                hits += 1
                print(f"{name}")
                for d, cls in sorted(dets, key=lambda x: -x[0].confidence):
                    print(f"    {cls:<14} {d.confidence:5.1%}")
            else:
                misses += 1
                print(f"{name}\n    (nothing detected)")

            if args.save_dir:
                draw = ImageDraw.Draw(img)
                W, H = img.size
                for d, cls in dets:
                    # Undo the fit: model coords -> original pixels. px/py are
                    # negative for crop (pixels removed) and positive for
                    # letterbox (pixels added), so one expression covers both.
                    x1 = (d.xmin * iw - px) / sx
                    y1 = (d.ymin * ih - py) / sy
                    x2 = (d.xmax * iw - px) / sx
                    y2 = (d.ymax * ih - py) / sy
                    draw.rectangle([max(0, x1), max(0, y1), min(W, x2), min(H, y2)],
                                   outline=(255, 64, 64), width=3)
                    draw.text((max(0, x1) + 4, max(0, y1) + 4),
                              f"{cls} {d.confidence:.0%}", fill=(255, 255, 0))
                img.save(os.path.join(args.save_dir, name))

        total = hits + misses
        print(f"\n{total} image(s): {hits} with a detection, {misses} with none")
        if tally:
            print("by class: " + "   ".join(
                f"{k} {v}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1])))
        if misses and not args.all_classes:
            print("Re-run with --all-classes --conf 0.1 to see what else the "
                  "model thought it saw.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
