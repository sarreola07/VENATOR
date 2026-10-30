#!/usr/bin/env python3
"""
Teach the vest search what these vests look like in this room.

The ranges in vest.py are only a starting point: the same vest reads differently
under fluorescent tubes, LEDs and daylight. So hold each vest up in the room being
flown in, and this writes its colour range to ~/.venator/vest-colours.json, along
with a white balance to lock so the colours hold during the run.

Needs the camera to itself, so stop the service first:

    sudo systemctl stop venator-gui
    ~/oak-venv/bin/python drone/wildlife/vest_calibrate.py
    sudo systemctl start venator-gui

Writes outside the repo: this belongs to one room on one day, not to the project.
"""
import sys
import time

import oak_wildlife
import vest

#: The middle of the frame. Whoever is holding a vest can't see a preview, so the
#: instruction is simply to fill the middle of the view from about a metre away.
CENTRE = (0.35, 0.35, 0.65, 0.65)
SIZE = (640, 360)
FRAMES = 12


def centre_pixels(rgb):
    h, w = rgb.shape[:2]
    x1, y1, x2, y2 = CENTRE
    step = max(1, (int(y2 * h) - int(y1 * h)) // 25)
    crop = rgb[int(y1 * h):int(y2 * h):step, int(x1 * w):int(x2 * w):step]
    return crop.reshape(-1, 3).tolist()


def grab(q, count):
    """The next `count` frames, or fewer if the camera stops delivering."""
    q.tryGetAll()       # the queue is still holding frames from before Enter
    frames, deadline = [], time.monotonic() + count + 5
    while len(frames) < count and time.monotonic() < deadline:
        msg = q.tryGet()
        if msg is None:
            time.sleep(0.01)
        else:
            frames.append(msg)
    return frames


def measure_white_balance(q, control, dai):
    """Read what auto white balance settled on for the room, then hold it there."""
    input("\nPoint the camera at the room, with no vest in view, then press Enter ")
    time.sleep(2.0)     # let auto white balance settle on the scene
    frames = grab(q, 5)
    wb_k = frames[-1].getColorTemperature() if frames else 0
    if not 1000 <= wb_k <= 12000:
        print("  no usable white balance reading, so it stays automatic")
        return None
    locked = dai.CameraControl()
    locked.setManualWhiteBalance(wb_k)
    control.send(locked)
    time.sleep(0.5)
    print(f"  locked at {wb_k} K")
    return wb_k


def measure_vest(q, name):
    """A colour range for one vest, asking again until it reads as one colour."""
    while True:
        input(f"\nHold the {name.upper()} vest about 1 m away, filling the middle of "
              "the view, then press Enter ")
        pixels = []
        for msg in grab(q, FRAMES):
            pixels.extend(centre_pixels(oak_wildlife.to_rgb(msg)))
        fit = vest.fit_range(pixels)
        if fit is not None:
            print(f"  hue {fit['hue'][0]}-{fit['hue'][1]}, "
                  f"saturation from {fit['sat']}, brightness from {fit['val']}")
            return fit
        print("  that did not read as one colour. Move it closer or check the lighting.")


def main():
    import depthai as dai

    try:
        return calibrate(dai)
    except RuntimeError as exc:
        sys.exit(f"Camera problem: {exc}\n"
                 "Is the OAK plugged in, with nothing else using it? On the Jetson, "
                 "stop the service first: sudo systemctl stop venator-gui")


def calibrate(dai):
    with dai.Pipeline() as pipeline:
        colour = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
        q = colour.requestOutput(SIZE, dai.ImgFrame.Type.BGR888p,
                                 resizeMode=dai.ImgResizeMode.CROP,
                                 fps=10).createOutputQueue(maxSize=2, blocking=False)
        control = colour.inputControl.createInputQueue()
        pipeline.start()

        wb_k = measure_white_balance(q, control, dai)
        ranges = {name: measure_vest(q, name) for name in vest.COLOURS}

    clashes = vest.overlaps(ranges)
    for a, b in clashes:
        print(f"\nWARNING: {a} and {b} overlap in colour, so the search could confuse "
              "them. Use a different vest, or recalibrate under better light.")
    path = vest.save_calibration(ranges, wb_k)
    print(f"\nSaved to {path}")
    return 1 if clashes else 0


if __name__ == "__main__":
    sys.exit(main())
