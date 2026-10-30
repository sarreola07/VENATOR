#!/usr/bin/env python3
"""
The vest search on a laptop's webcam: a proof of concept, with no drone and no OAK.

    ~/oak-venv/bin/pip install numpy opencv-python-headless \
        pyobjc-framework-Vision pyobjc-framework-AVFoundation
    ~/oak-venv/bin/python drone/wildlife/webcam_search.py
    ~/oak-venv/bin/python drone/wildlife/webcam_search.py --search blue

Then open http://127.0.0.1:8080. The page is only reachable from this computer.

The colour check, the vote, the lock, the page, the chart and the snapshots are
the same code the aircraft runs (vest.py, gui_server.py, gui_page.py). Two things
are different, and both are worth saying out loud when showing this:

  * the person detector is Apple's Vision framework, not MegaDetector, which only
    runs on the OAK's own chip. So this says nothing about MegaDetector;
  * a webcam has no depth. There are no distances, no range or size gates, and no
    closest_m, so nothing here shows the 2 m safety rule working.

macOS only, because of Vision. It has to be a stand-in rather than the flight
path: without depth it could not keep anyone safe.
"""
import argparse
import collections
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import gui_server
import ports
import tracking
import vest

#: What the vote's "about a second" assumes, and what the OAK's detector runs at.
DETECT_FPS = 10.0
#: Frame size asked of the camera. Same 16:9 shape as the aircraft's video.
SIZE = (1280, 720)
JPEG_QUALITY = 80

#: Longer than the OAK tracker's ~1 s, because Vision drops people more often.
KEEP_LOST_S = 1.5
#: No picture for this long means the camera has stopped, so reopen it.
CAMERA_STALL_S = 5.0
#: How far below an upper-body box the rest of the torso reaches, as a share of its
#: height. See VisionPeople.find().
TORSO_BELOW = 0.6


class BoxTracker:
    """Stable ids from boxes, standing in for the OAK's on-device tracker.

    Reports the same four statuses, so vest.py can't tell the difference. Ids are
    never reused, the same as gui_server.py's UNIQUE_ID: a lock is on an id, and
    a recycled one could silently put it on a different person.
    """

    def __init__(self, keep_s=KEEP_LOST_S):
        self._keep_s = keep_s
        self._tracks = {}       # id -> {"box", "conf", "seen"}
        self._next_id = 1

    def update(self, found, now):
        """`found` is [(box, confidence)]. Returns [{id, box, conf, status}]."""
        pairs = sorted(((vest.iou(t["box"], f[0]), tid, i)
                        for tid, t in self._tracks.items()
                        for i, f in enumerate(found)), reverse=True)
        taken_ids, taken_found, out = set(), set(), []
        for score, tid, i in pairs:
            if score < vest.MATCH_IOU:
                break
            if tid in taken_ids or i in taken_found:
                continue
            taken_ids.add(tid)
            taken_found.add(i)
            self._tracks[tid].update(box=found[i][0], conf=found[i][1], seen=now)
            out.append(self._tracklet(tid, "TRACKED"))
        for tid in [t for t in self._tracks if t not in taken_ids]:
            gone = now - self._tracks[tid]["seen"] > self._keep_s
            out.append(self._tracklet(tid, "REMOVED" if gone else "LOST"))
            if gone:
                del self._tracks[tid]
        for i, (box, conf) in enumerate(found):
            if i not in taken_found:
                tid = self._next_id
                self._next_id += 1
                self._tracks[tid] = {"box": box, "conf": conf, "seen": now}
                out.append(self._tracklet(tid, "NEW"))
        return sorted(out, key=lambda t: t["id"])

    def _tracklet(self, tid, status):
        t = self._tracks[tid]
        return {"id": tid, "box": t["box"], "conf": t["conf"], "status": status}


def detection(t):
    """A tracklet in the shape gui_server.py's page and vest.py both read."""
    return {"id": t["id"], "c": "person", "raw": None, "p": round(t["conf"], 3),
            "st": t["status"], "b": [round(v, 4) for v in t["box"]],
            "xyz": None, "len_m": None}


class VisionPeople:
    """Apple's built-in person detector. Runs on this Mac, with no model to download."""

    def __init__(self):
        import Foundation
        import objc
        import Vision
        self._foundation, self._objc, self._vision = Foundation, objc, Vision

    def find(self, jpeg):
        """[(box, confidence)] for a JPEG, with boxes normalised and y going down.

        Whole people first, as the OAK's detector sees them. That search drops
        someone sitting close to the camera, so if it finds nobody, ask again for
        head and shoulders, and extend that box down over the torso, where the
        vest is.
        """
        with self._objc.autorelease_pool():
            data = self._foundation.NSData.dataWithBytes_length_(jpeg, len(jpeg))
            handler = self._vision.VNImageRequestHandler.alloc().initWithData_options_(data, {})
            found = self._people(handler, upper_body=False)
            if not found:
                found = [([b[0], b[1], b[2], min(1.0, b[3] + TORSO_BELOW * (b[3] - b[1]))], c)
                         for b, c in self._people(handler, upper_body=True)]
            return found

    def _people(self, handler, upper_body):
        request = self._vision.VNDetectHumanRectanglesRequest.alloc().init()
        request.setUpperBodyOnly_(upper_body)
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise RuntimeError(str(error))
        found = []
        for person in request.results() or []:
            r = person.boundingBox()    # Vision's origin is bottom-left
            x, y, w, h = r.origin.x, r.origin.y, r.size.width, r.size.height
            found.append(([max(0.0, x), max(0.0, 1.0 - (y + h)),
                           min(1.0, x + w), min(1.0, 1.0 - y)], float(person.confidence())))
        return found


def builtin_camera():
    """(OpenCV's index for the built-in camera, its name).

    OpenCV numbers cameras by sorted unique id. A nearby iPhone appears as a camera
    too, and can sort first, so index 0 can be someone's phone rather than the laptop.
    """
    import AVFoundation as av
    devices = sorted(av.AVCaptureDevice.devicesWithMediaType_(av.AVMediaTypeVideo),
                     key=lambda d: str(d.uniqueID()))
    for index, device in enumerate(devices):
        if "BuiltIn" in str(device.deviceType()):
            return index, str(device.localizedName())
    sys.exit("No built-in camera found. Name one with --camera.")


def camera_access(wait_s=120):
    """True once macOS allows the camera, asking first if it has not been asked.

    Asked for here because OpenCV gives up the moment access isn't granted, without
    waiting for the answer to the prompt it has just caused.
    """
    import AVFoundation as av
    not_asked, allowed = 0, 3   # AVAuthorizationStatus values
    media = av.AVMediaTypeVideo
    status = av.AVCaptureDevice.authorizationStatusForMediaType_(media)
    if status == not_asked:
        gui_server.log("macOS should be asking for camera access. Click Allow.")
        av.AVCaptureDevice.requestAccessForMediaType_completionHandler_(media, lambda granted: None)
        deadline = time.monotonic() + wait_s
        while status == not_asked and time.monotonic() < deadline:
            time.sleep(0.25)
            status = av.AVCaptureDevice.authorizationStatusForMediaType_(media)
    return status == allowed


def capture(cv2, index):
    cam = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    cam.set(cv2.CAP_PROP_FRAME_WIDTH, SIZE[0])
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, SIZE[1])
    return cam


def open_camera(cv2, index):
    if not camera_access():
        sys.exit("macOS has not allowed camera access. Allow it for this app in System "
                 "Settings > Privacy & Security > Camera, or run this from Terminal.")
    cam = capture(cv2, index)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        ok, frame = cam.read()
        if ok and frame is not None:
            return cam, frame
        time.sleep(0.25)
    cam.release()
    sys.exit(f"Camera {index} opened but sent no picture. Is another app using it?")


def run(args, hub, cfg, stop):
    import cv2

    index, name = (args.camera, f"camera {args.camera}") if args.camera is not None else builtin_camera()
    cam, frame = open_camera(cv2, index)
    gui_server.log(f"webcam open: {name} at {frame.shape[1]}x{frame.shape[0]}")
    search, link = cfg["search"], cfg["search_link"]
    people, tracker, book = VisionPeople(), BoxTracker(), tracking.TrackBook()
    fps_window = collections.deque(maxlen=20)
    seq = hits = saved = detector_faults = 0
    last_status = 0.0
    last_picture = time.monotonic()
    try:
        while not stop["flag"]:
            started = time.monotonic()
            ok, frame = cam.read()
            if not ok:
                # Another app can take the camera, or the laptop can sleep. Say
                # so and keep trying, rather than sitting silent or dying.
                if started - last_picture > CAMERA_STALL_S:
                    gui_server.log("no picture from the webcam, reopening it")
                    hub.publish("status", {"t": round(time.time(), 2), "camera": "offline",
                                           "error": "the webcam stopped sending pictures",
                                           "fps": 0.0, "pm": "webcam"})
                    cam.release()
                    cam = capture(cv2, index)
                    last_picture = time.monotonic()
                time.sleep(0.05)
                continue
            last_picture = started
            encoded, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not encoded:
                continue
            jpeg = buf.tobytes()
            for rung in gui_server.QUALITIES:
                hub.publish_frame(rung, jpeg)

            now = time.monotonic()
            try:
                found = people.find(jpeg)
            except Exception as exc:   # noqa: BLE001 - one bad frame, keep the feed up
                detector_faults += 1
                if detector_faults == 1 or detector_faults % 100 == 0:
                    gui_server.log(f"person detector fault x{detector_faults}: {exc}")
                found = []
            dets = [detection(t) for t in tracker.update(found, now)]
            touched = book.update([{"id": d["id"], "cls": "person", "conf": d["p"],
                                    "status": d["st"], "xyz": None} for d in dets], now=now)
            dwell = {t.id: round(t.dwell, 1) for t in touched}
            for d in dets:
                d["dwell"] = dwell.get(d["id"], 0.0)

            link.poll_target(search)
            rgb = frame[:, :, ::-1]
            report = search.process(dets, lambda box: vest.chest_pixels(rgb, box), now)
            link.send(report)

            seq += 1
            hits += bool(dets)
            fps_window.append(now)
            hub.publish("det", {"seq": seq, "t": round(time.time(), 2),
                                "w": frame.shape[1], "h": frame.shape[0], "d": dets,
                                "tracks": len(book),
                                "search": {k: v for k, v in report.items() if k != "found_now"}})
            if report.get("found_now"):
                gui_server.log(f"FOUND {report['target']} vest: track {report['id']}, "
                               f"{report['ignored']} ignored")
                hub.publish("alert", vest.found_alert(report, time.time()), reliable=True)
                if cfg["save"]:
                    saved += 1
                    gui_server.save_evidence(hub, args.save_dir, saved, dets)

            if now - last_status >= 1.0:
                last_status = now
                fps = 0.0
                if len(fps_window) > 2:
                    fps = (len(fps_window) - 1) / (fps_window[-1] - fps_window[0])
                hub.publish("status", {
                    "t": round(time.time(), 2), "fps": round(fps, 1), "frames": seq,
                    "hits": hits, "counts": book.counts(), "tracks": len(book),
                    "active": len(book.active()), "saved": saved,
                    "model": "Apple Vision", "pm": "webcam", "quality": cfg["quality"],
                    # No depth and no GPS here, and the page must not imply otherwise.
                    "gps": {"fix": "none on a webcam"},
                })

            spare = 1.0 / DETECT_FPS - (time.monotonic() - started)
            if spare > 0:
                time.sleep(spare)
    finally:
        cam.release()
        gui_server.log("webcam closed")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--search", default="red", choices=vest.COLOURS, metavar="COLOUR",
                    help="the vest colour to search for (default red)")
    ap.add_argument("--camera", type=int, default=None,
                    help="camera index (default: the laptop's built-in camera)")
    ap.add_argument("--port", type=int, default=ports.GUI_HTTP)
    ap.add_argument("--save-dir", default=str(Path.home() / "Pictures" / "venator-search"))
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    ranges, _, source = vest.load_calibration()
    cfg = {"conf": None, "classes": [], "quality": "hi", "save": not args.no_save, "pm": "webcam",
           "search": vest.VestSearch(args.search, ranges, use_depth=False),
           "search_link": vest.SearchLink(ports.SEARCH_TARGET_UDP, ports.SEARCH_REPORT_UDP,
                                          log=gui_server.log)}
    if cfg["save"]:
        Path(args.save_dir).mkdir(parents=True, exist_ok=True)

    hub = gui_server.Hub()
    # No token, on purpose: gui_server treats that as loopback only, and this
    # binds loopback. A webcam picture has no business being on the network.
    server = gui_server.start_server(hub, None, "127.0.0.1", args.port, args.save_dir, cfg)
    if server is None:
        return 1
    gui_server.log(f"searching for {args.search}, colours from {source}")
    gui_server.log(f"open http://127.0.0.1:{args.port}")

    stop = {"flag": False}
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.__setitem__("flag", True))
    run(args, hub, cfg, stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
