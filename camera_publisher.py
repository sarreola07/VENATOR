#!/usr/bin/env python3
"""
OAK-D person tracker -> UDP publisher.

Runs the OAK-D spatial person detector headlessly and broadcasts the nearest
person's position as JSON over UDP, so the mission app (in a separate venv) can
read it without importing DepthAI.

  Sends, per detection:  {"x": <m>, "y": <m>, "z": <m>, "conf": <0..1>}
  X = left(-)/right(+),  Y = down(-)/up(+),  Z = forward distance, all in metres,
  relative to the camera.

Optional ways to see what the camera sees (both keep publishing on UDP):
  --preview   a window on the Jetson's own screen
  --stream    a web page any laptop browser (Windows, Mac) can open at
              http://<jetson-ip>:8080

IMPORTANT: run this with the DepthAI environment, not the mission venv:
    ~/oak_drone_project/depthai-env/bin/python camera_publisher.py

Started and stopped on demand by ai_camera.sh — it is not a boot service.
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import depthai as dai
except ImportError:
    sys.exit("depthai not found. Run with ~/oak_drone_project/depthai-env/bin/python")

# --- config (override via env) ------------------------------------------------
UDP_IP = os.environ.get("CAMERA_UDP_IP", "127.0.0.1")
UDP_PORT = int(os.environ.get("CAMERA_UDP_PORT", "5005"))
CONFIDENCE = float(os.environ.get("CAMERA_CONFIDENCE", "0.5"))
PERSON_LABEL = 15  # MobileNet-SSD: index 15 == "person"
DEFAULT_BLOB = str(Path.home() / "oak_drone_project/depthai-python/examples/"
                   "models/mobilenet-ssd_openvino_2021.4_6shave.blob")
BLOB_PATH = os.environ.get("CAMERA_BLOB", DEFAULT_BLOB)
RECONNECT_WAIT_S = 5
# Web stream (--stream). Binds all interfaces so laptops on the hotspot, USB-C
# link or Tailscale can reach it; set CAMERA_STREAM_HOST=127.0.0.1 to keep it local.
STREAM_HOST = os.environ.get("CAMERA_STREAM_HOST", "0.0.0.0")
STREAM_PORT = int(os.environ.get("CAMERA_STREAM_PORT", "8080"))
STREAM_FPS = max(1.0, float(os.environ.get("CAMERA_STREAM_FPS", "15")))  # caps Wi-Fi bandwidth
STREAM_SIZE = 600          # px; the 300x300 NN frame is upscaled so the overlay is readable
STREAM_JPEG_QUALITY = 75
# -----------------------------------------------------------------------------


def log(msg):
    print(msg, flush=True)


def build_pipeline(blob_path, rgb_out=False):
    """RGB + stereo-depth + MobileNet spatial detection pipeline.

    rgb_out=True also streams the RGB frames out so they can be shown
    (preview window or web stream).
    """
    pipeline = dai.Pipeline()

    cam_rgb = pipeline.create(dai.node.ColorCamera)
    mono_left = pipeline.create(dai.node.MonoCamera)
    mono_right = pipeline.create(dai.node.MonoCamera)
    stereo = pipeline.create(dai.node.StereoDepth)
    spatial_nn = pipeline.create(dai.node.MobileNetSpatialDetectionNetwork)
    xout_nn = pipeline.create(dai.node.XLinkOut)
    xout_nn.setStreamName("detections")

    cam_rgb.setPreviewSize(300, 300)
    cam_rgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_1080_P)
    cam_rgb.setInterleaved(False)
    cam_rgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)

    mono_left.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    mono_left.setCamera("left")
    mono_right.setResolution(dai.MonoCameraProperties.SensorResolution.THE_400_P)
    mono_right.setCamera("right")

    stereo.setDefaultProfilePreset(dai.node.StereoDepth.PresetMode.HIGH_DENSITY)
    stereo.setDepthAlign(dai.CameraBoardSocket.CAM_A)
    stereo.setSubpixel(True)
    stereo.setOutputSize(mono_left.getResolutionWidth(), mono_left.getResolutionHeight())

    spatial_nn.setBlobPath(blob_path)
    spatial_nn.setConfidenceThreshold(CONFIDENCE)
    spatial_nn.input.setBlocking(False)
    spatial_nn.setBoundingBoxScaleFactor(0.5)
    spatial_nn.setDepthLowerThreshold(100)     # mm
    spatial_nn.setDepthUpperThreshold(10000)   # mm

    mono_left.out.link(stereo.left)
    mono_right.out.link(stereo.right)
    cam_rgb.preview.link(spatial_nn.input)
    stereo.depth.link(spatial_nn.inputDepth)
    spatial_nn.out.link(xout_nn.input)

    if rgb_out:
        xout_rgb = pipeline.create(dai.node.XLinkOut)
        xout_rgb.setStreamName("rgb")
        # passthrough gives the RGB frame the detections were computed on (synced)
        spatial_nn.passthrough.link(xout_rgb.input)
    return pipeline


def nearest_person(detections):
    """Return the closest person detection (smallest Z), or None."""
    people = [d for d in detections if d.label == PERSON_LABEL]
    if not people:
        return None
    return min(people, key=lambda d: d.spatialCoordinates.z or float("inf"))


def _draw_preview(cv2, frame, detections):
    """Draw person boxes + X/Y/Z distance onto the RGB frame (in place)."""
    h, w = frame.shape[:2]
    k = w / 300.0              # sizes are tuned for the 300 px NN frame; scale for bigger ones
    font, line = 0.5 * k, max(1, round(k))
    for det in detections:
        if det.label != PERSON_LABEL:
            continue
        x1, y1 = int(det.xmin * w), int(det.ymin * h)
        x2, y2 = int(det.xmax * w), int(det.ymax * h)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2 * line)
        zx = det.spatialCoordinates.x / 1000.0
        zy = det.spatialCoordinates.y / 1000.0
        zz = det.spatialCoordinates.z / 1000.0
        cv2.putText(frame, "person {:.0f}%".format(det.confidence * 100),
                    (x1 + int(6 * k), y1 + int(20 * k)), cv2.FONT_HERSHEY_SIMPLEX, font, (0, 255, 0), line)
        for i, txt in enumerate(("X {:+.2f} m".format(zx), "Y {:+.2f} m".format(zy),
                                 "Z {:.2f} m".format(zz))):
            cv2.putText(frame, txt, (x1 + int(6 * k), y1 + int((40 + i * 18) * k)),
                        cv2.FONT_HERSHEY_SIMPLEX, font, (0, 255, 0), line)


# --- web stream (--stream) ------------------------------------------------------

class StreamHub:
    """Shares the latest camera frame and person reading with web viewers.

    The detection loop only hands over a raw frame, and only while someone is
    watching; a separate thread does the resize/draw/JPEG work, so streaming
    never delays the UDP coordinates the missions fly on.
    """

    def __init__(self, cv2):
        self._cv2 = cv2
        self._cond = threading.Condition()
        self._pending = None       # (frame, detections) waiting to be encoded
        self._jpeg = None
        self._seq = 0
        self._viewers = 0
        self._next_frame_at = 0.0
        self._alive_at = 0.0       # last detection packet from the OAK-D
        self._person = None        # latest nearest-person payload
        self._person_at = 0.0
        threading.Thread(target=self._encode_loop, name="stream-encoder", daemon=True).start()

    def update(self, person):
        """Record one detection packet (person payload dict or None)."""
        now = time.time()
        self._alive_at = now
        if person is not None:
            self._person, self._person_at = person, now

    def wants_frame(self):
        """True when someone is watching and the frame-rate cap allows another frame."""
        return self._viewers > 0 and time.time() >= self._next_frame_at

    def submit(self, frame, detections):
        now = time.time()
        with self._cond:
            self._pending = (frame, detections)
            # Advance on a fixed schedule rather than "interval since the last
            # frame", which would halve the rate whenever the camera delivers
            # less than twice STREAM_FPS. Never schedule into the past (no burst after idle).
            self._next_frame_at = max(self._next_frame_at + 1.0 / STREAM_FPS, now)
            self._cond.notify_all()

    def _encode_loop(self):
        cv2 = self._cv2
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._pending is not None)
                frame, detections = self._pending
                self._pending = None
            frame = cv2.resize(frame, (STREAM_SIZE, STREAM_SIZE))
            _draw_preview(cv2, frame, detections)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY])
            if ok:
                with self._cond:
                    self._jpeg = buf.tobytes()
                    self._seq += 1
                    self._cond.notify_all()

    def frames(self):
        """Yield each new JPEG to one viewer; counts them as watching until closed."""
        with self._cond:
            self._viewers += 1
            seen = self._seq       # wait for a fresh frame, not a stale one
        try:
            while True:
                with self._cond:
                    if not self._cond.wait_for(lambda: self._seq != seen, timeout=1.0):
                        continue   # camera quiet (e.g. reconnecting) — keep waiting
                    seen, jpeg = self._seq, self._jpeg
                yield jpeg
        finally:
            with self._cond:
                self._viewers -= 1

    def status(self):
        now = time.time()
        person_fresh = self._person is not None and now - self._person_at < 1.0
        return {
            "camera": "ok" if now - self._alive_at < 3.0 else "offline",
            "person": self._person if person_fresh else None,
            "viewers": self._viewers,
        }


STREAM_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Camera</title>
<style>
  :root { color-scheme: light dark; --bg: #f4f4f5; --fg: #18181b; --muted: #71717a;
          --card: #ffffff; --ok: #15803d; --bad: #b91c1c; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #09090b; --fg: #f4f4f5; --muted: #a1a1aa; --card: #18181b;
            --ok: #4ade80; --bad: #f87171; }
  }
  body { margin: 0; padding: 16px; background: var(--bg); color: var(--fg);
         font: 15px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 600px; margin: 0 auto; }
  h1 { font-size: 18px; margin: 0 0 12px; }
  img { display: block; width: 100%; aspect-ratio: 1; background: #000; border-radius: 8px; }
  #reading { margin-top: 12px; padding: 10px 12px; border-radius: 8px; background: var(--card);
             font-variant-numeric: tabular-nums; white-space: pre-wrap; }
  .muted { color: var(--muted); } .ok { color: var(--ok); } .bad { color: var(--bad); }
</style>
</head>
<body>
<main>
  <h1>AI Camera &mdash; person tracking</h1>
  <img id="video" src="/stream.mjpg" alt="Live OAK-D camera view">
  <div id="reading" class="muted">Connecting&hellip;</div>
</main>
<script>
  const video = document.getElementById("video");
  const reading = document.getElementById("reading");
  let lost = false;
  video.onerror = () => { lost = true; };
  const signed = (v) => (v >= 0 ? "+" : "") + v.toFixed(2);
  function show(cls, text) { reading.className = cls; reading.textContent = text; }
  async function poll() {
    try {
      const s = await (await fetch("/status.json", { cache: "no-store" })).json();
      if (lost) { lost = false; video.src = "/stream.mjpg?t=" + Date.now(); }
      if (s.camera !== "ok") {
        show("bad", "Camera offline \\u2014 reconnecting\\u2026");
      } else if (s.person) {
        const p = s.person;
        show("ok", `Person   X ${signed(p.x)} m   Y ${signed(p.y)} m   Z ${p.z.toFixed(2)} m   (${Math.round(p.conf * 100)}%)`);
      } else {
        show("muted", "No person in view");
      }
    } catch (e) {
      lost = true;
      show("bad", "Jetson not reachable \\u2014 retrying\\u2026");
    }
    setTimeout(poll, 500);
  }
  poll();
</script>
</body>
</html>
"""


def start_stream_server(hub):
    """Serve the web viewer on STREAM_HOST:STREAM_PORT from background threads.

    Returns the server, or None if the port can't be opened — tracking keeps
    running either way, because the missions depend on the UDP coordinates.
    """
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._send(200, "text/html; charset=utf-8", STREAM_PAGE.encode())
            elif path == "/status.json":
                self._send(200, "application/json", json.dumps(hub.status()).encode())
            elif path == "/stream.mjpg":
                self._stream()
            else:
                self._send(404, "text/plain", b"not found")

        def _send(self, code, content_type, body):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            frames = hub.frames()
            try:
                for jpeg in frames:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            except OSError:
                pass   # viewer closed the page
            finally:
                frames.close()

        def log_message(self, *args):
            pass       # keep camera.log for tracking messages

    try:
        server = ThreadingHTTPServer((STREAM_HOST, STREAM_PORT), Handler)
    except OSError as exc:
        log("Web stream disabled: cannot open port {} ({})".format(STREAM_PORT, exc))
        return None
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="stream-http", daemon=True).start()
    log("Web stream on port {} — open http://<jetson-ip>:{} in a browser".format(
        STREAM_PORT, STREAM_PORT))
    return server


def run_once(sock, blob_path, preview=False, hub=None):
    """Open the camera and stream until the device drops or (preview) the user quits.

    hub, when given, receives frames for the web stream.
    Returns True if the user asked to quit (pressed q in the preview window).
    """
    cv2 = None
    if preview:
        import cv2  # only needed for the window; lives in the DepthAI env

    rgb_out = preview or hub is not None
    pipeline = build_pipeline(blob_path, rgb_out=rgb_out)
    with dai.Device(pipeline) as device:
        log("OAK-D connected (MxId {}). Publishing to {}:{}{}{}".format(
            device.getMxId(), UDP_IP, UDP_PORT, "  [preview]" if preview else "",
            "  [web stream]" if hub is not None else ""))
        det_queue = device.getOutputQueue(name="detections", maxSize=4, blocking=False)
        rgb_queue = device.getOutputQueue(name="rgb", maxSize=4, blocking=False) if rgb_out else None
        win = "AI Camera - person tracking (press q to close)"
        last_report = 0.0
        while True:
            in_det = det_queue.get()  # blocks until a frame arrives
            detections = in_det.detections

            person = nearest_person(detections)
            payload = None
            if person is not None:
                payload = {
                    "x": person.spatialCoordinates.x / 1000.0,
                    "y": person.spatialCoordinates.y / 1000.0,
                    "z": person.spatialCoordinates.z / 1000.0,
                    "conf": float(person.confidence),
                }
                sock.sendto(json.dumps(payload).encode(), (UDP_IP, UDP_PORT))
                now = time.time()
                if now - last_report >= 1.0:   # throttle console logging to 1 Hz
                    log("person X:{x:+.2f} Y:{y:+.2f} Z:{z:.2f} m  ({conf:.0%})".format(**payload))
                    last_report = now
            if hub is not None:
                hub.update(payload)

            if preview:
                in_rgb = rgb_queue.get()
                frame = in_rgb.getCvFrame()
                if hub is not None and hub.wants_frame():
                    hub.submit(frame.copy(), detections)   # copy: the window draws on frame
                _draw_preview(cv2, frame, detections)
                cv2.imshow(win, frame)
                if cv2.waitKey(1) == ord("q"):
                    cv2.destroyAllWindows()
                    return True
            elif hub is not None and hub.wants_frame():
                frames = rgb_queue.tryGetAll()   # newest frame; older ones are stale
                if frames:
                    hub.submit(frames[-1].getCvFrame(), detections)


def main():
    parser = argparse.ArgumentParser(description="OAK-D person tracker -> UDP")
    parser.add_argument("--preview", action="store_true",
                        help="show a live window with person boxes (needs a display)")
    parser.add_argument("--stream", action="store_true",
                        help="serve the live view to laptop browsers on port {} "
                             "(CAMERA_STREAM_PORT)".format(STREAM_PORT))
    args = parser.parse_args()

    if not Path(BLOB_PATH).exists():
        sys.exit("Model blob not found: {}".format(BLOB_PATH))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    modes = [m for m, on in (("preview", args.preview), ("web stream", args.stream)) if on]
    log("Camera publisher starting{}. Blob: {}".format(
        " ({})".format(", ".join(modes)) if modes else "", BLOB_PATH))

    hub = None
    if args.stream:
        import cv2  # JPEG encoding; lives in the DepthAI env
        hub = StreamHub(cv2)
        if start_stream_server(hub) is None:
            hub = None

    while True:
        try:
            if run_once(sock, BLOB_PATH, preview=args.preview, hub=hub):
                log("Preview closed — camera stopped.")
                return
        except KeyboardInterrupt:
            log("Camera publisher stopped.")
            return
        except Exception as exc:
            log("Camera error: {} — reconnecting in {}s".format(exc, RECONNECT_WAIT_S))
            time.sleep(RECONNECT_WAIT_S)


if __name__ == "__main__":
    main()
