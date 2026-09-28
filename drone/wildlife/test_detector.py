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
A blank result is a result. The default model is COCO-trained and its entire
animal vocabulary is:

    bird, cat, dog, horse, sheep, cow, elephant, bear, zebra, giraffe

There is no deer, hog, coyote, armadillo, raccoon, bobcat or javelina - the
species that actually matter in Texas. Expect misses, and expect near-misses
like a coyote landing on "dog" or a bobcat on "cat". Both are reported so you
can see the confusion rather than guess at it.
"""

import argparse
import os
import sys
import time

MODEL = "luxonis/yolov6-nano:r2-coco-512x288"

# COCO classes worth reporting for wildlife work.
WILDLIFE = {
    "person",
    "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe",
}

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def letterbox(img, size):
    """
    Resize into the model's input box without distorting aspect ratio.

    Returns (padded_rgb, scale, pad_x, pad_y) so detections can be mapped back
    onto the original image. Squashing instead of padding would change animal
    body proportions, which is exactly the cue the detector relies on.
    """
    from PIL import Image
    tw, th = size
    w, h = img.size
    scale = min(tw / w, th / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("RGB", (tw, th), (114, 114, 114))
    px, py = (tw - nw) // 2, (th - nh) // 2
    canvas.paste(resized, (px, py))
    return canvas, scale, px, py


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="image file, or a directory of images")
    ap.add_argument("--conf", type=float, default=0.25,
                    help="confidence threshold (default 0.25, lower than live "
                         "so you can see near-misses)")
    ap.add_argument("--all-classes", action="store_true",
                    help="report every COCO class, not just animals/people")
    ap.add_argument("--save-dir", help="write annotated copies here")
    ap.add_argument("--model", default=MODEL, help=f"HubAI model id (default {MODEL})")
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
        nn.setConfidenceThreshold(args.conf)
        qin = nn.input.createInputQueue()
        qout = nn.out.createOutputQueue()
        pipeline.start()

        labels = list(nn.getClasses() or [])
        want = set(labels) if args.all_classes else (WILDLIFE & set(labels))
        print(f"model  {args.model}")
        print(f"input  {iw}x{ih}   conf >= {args.conf:.2f}")
        print(f"report {', '.join(sorted(want))}\n")

        if args.save_dir:
            os.makedirs(args.save_dir, exist_ok=True)

        hits = misses = 0
        for path in files:
            img = Image.open(path).convert("RGB")
            boxed, scale, px, py = letterbox(img, (iw, ih))

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
            dets = [d for d in (msg.detections if msg else [])
                    if (labels[d.label] if d.label < len(labels) else "") in want]

            name = os.path.basename(path)
            if dets:
                hits += 1
                print(f"{name}")
                for d in sorted(dets, key=lambda x: -x.confidence):
                    cls = labels[d.label] if d.label < len(labels) else str(d.label)
                    print(f"    {cls:<10} {d.confidence:5.1%}")
            else:
                misses += 1
                print(f"{name}\n    (nothing detected)")

            if args.save_dir:
                draw = ImageDraw.Draw(img)
                W, H = img.size
                for d in dets:
                    # undo the letterbox: model coords -> original pixels
                    x1 = (d.xmin * iw - px) / scale
                    y1 = (d.ymin * ih - py) / scale
                    x2 = (d.xmax * iw - px) / scale
                    y2 = (d.ymax * ih - py) / scale
                    cls = labels[d.label] if d.label < len(labels) else str(d.label)
                    draw.rectangle([max(0, x1), max(0, y1), min(W, x2), min(H, y2)],
                                   outline=(255, 64, 64), width=3)
                    draw.text((max(0, x1) + 4, max(0, y1) + 4),
                              f"{cls} {d.confidence:.0%}", fill=(255, 255, 0))
                img.save(os.path.join(args.save_dir, name))

        total = hits + misses
        print(f"\n{total} image(s): {hits} with a detection, {misses} with none")
        if misses and not args.all_classes:
            print("Re-run with --all-classes --conf 0.1 to see what else the "
                  "model thought it saw.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
