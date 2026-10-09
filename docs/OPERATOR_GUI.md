# Operator GUI

Live video and detections on a phone, with no monitor attached to the Jetson.

```bash
./drone/wildlife/oak_camera.sh gui
```

It prints a token and every address it became reachable on. Open one on a
phone. `http://jetson.local:8080/?k=<token>` works on the hotspot, the school
Wi-Fi and the USB link alike, because avahi is running — you never need to know
the IP.

---

## Why the camera does the encoding

**The Jetson Orin Nano has no hardware video encoder.** No NVENC, no
`/dev/nvhost-msenc`, and `nvv4l2h264enc` does not exist — `nvvideo4linux2`
exposes exactly one feature, `nvv4l2decoder`. `ffmpeg -encoders` lists
`h264_nvenc` and friends but every one fails at runtime; it is a generic arm64
build. The only hardware-accelerated paths are `nvjpegenc` and `nvvidconv`.

So H.264 here means software `x264enc` burning CPU inside a 7 W budget. Instead:

> **The OAK encodes MJPEG on its own fixed-function codec block. This process
> relays the bytes without decoding them. Boxes are drawn client-side on a
> `<canvas>`.** The Jetson's video path is a `memcpy`.

Measured on this rig — 3 cameras + stereo + MegaDetector at 5 shaves + both
encoders, all at once:

| | fps | per frame | bitrate |
|---|---|---|---|
| Detector | **10.01** (unchanged) | — | — |
| MJPEG 1280×720 q80 | 10.01 | 28.6 KB | 2.24 Mbps |
| MJPEG 640×360 q75 | 8.00 | 7.9 KB | 0.50 Mbps |

Board draw 6.65 W mean. **The encoders cost the detector nothing** — the codec
is dedicated silicon, not SHAVE cores. Both rungs together are 2.74 Mbps, which
is 0.6 % of even the pessimistic 480 Mbps USB 2.0 link.

MJPEG also beats H.264 on a drone link for a reason unrelated to the encoder:
every frame is an I-frame, so a frame lost to a weak signal costs one frame
rather than the rest of a GOP.

### Boxes are not burned in

Burning boxes into the frame would cost a decode and a re-encode per frame. The
client draws them from the SSE stream instead, which is free, crisp at any
zoom, and lets layers be toggled.

The trade: the video and the detection stream are independent, so boxes can
lead or lag the picture by about one frame (~100 ms at 10 fps). That is
accepted deliberately. `seq` ships in both streams if a paired mode is ever
wanted.

**Coordinates need no transform.** The network input (512×288) and every video
rung are *both* 16:9 centre-crops of the same 4:3 sensor, so normalised boxes
land on the video frame directly. `resizeMode=CROP` is passed explicitly to
both `SpatialDetectionNetwork.build()` and every `requestOutput()` — it happens
to be the library default, but a silent default drift there would misplace
every box on screen.

---

## Range — the honest version

Link budget at 5.18 GHz, TX 13 dBm, phone at roughly 0 dBi:

| RX level | Meaning | Free space |
|---|---|---|
| −70 dBm | stable MJPEG | ~82 m |
| −78 dBm | stuttering | ~206 m |

Subtract dev-kit antennas inside an airframe near motors (−3 to −6 dB), body
shadowing, and antenna nulls every time the aircraft banks:

> **Usable video: 60–120 m line of sight. Reliable inside 50 m. Behind a tree
> line at 5 GHz it is gone.**

```
Wi-Fi is the cockpit.      <100 m. Video, tuning, preflight, hover-and-inspect.
LoRa is the nervous system. Kilometres. <200 byte frames. Alerts and status only.
```

This is why **the status and alert panel is built to work with no video at
all** — past 100 m that is the normal operating case, not an error. The video
pane greys out, says so, and everything else keeps working.

---

## Routes

| Method | Route | Notes |
|---|---|---|
| GET | `/` | App shell. Sets an `HttpOnly` cookie so the token stops riding in URLs |
| GET | `/live.mjpg?q=hi\|lo` | VPU bytes, zero transcode |
| GET | `/events` | SSE: `det` `status` `alert` `evidence` |
| GET | `/api/status` | One-shot snapshot, for first paint and `curl` |
| GET | `/api/evidence?n=40` | Newest first, with sidecar data merged in |
| GET | `/api/evidence/<name>` | Basename only, allowlisted shape |
| POST | `/api/config` | `{conf, classes[], quality, save}` |
| POST | `/api/ack` | Clears an alert banner server-side |
| POST | `/api/verdict` | `{name, ok}` → sidecar. The active-learning loop |
| GET | `/healthz` | `ok`. **Unauthenticated** — the boot fallback polls it |

### `conf` can only tighten

`/api/config` accepts a live confidence override, but the network's own
threshold is programmed at pipeline build time to the policy's lowest value
(0.35 for MegaDetector). Anything below that was already discarded in
hardware and no host-side setting brings it back, so a request is **clamped up
to the device floor** and the response reports both:

```json
{"conf": 0.35, "conf_requested": 0.1, "device_floor": 0.35}
```

An API that accepted 0.10 and silently changed nothing would be worse than one
that refuses.

---

## Authentication

Fixes `docs/SECURITY.md` item 4 — the old stream had no key, no token and no
check of any kind, bound to `0.0.0.0`.

The token is **derived** from `radio/auth.py`'s key, never equal to it:

```python
token = hmac.new(key, b"venator-gui-v1", sha256).hexdigest()[:16]
```

So a token in browser history, a bookmark or a photographed QR code yields
nothing about the key that signs flight commands — and a GUI token cannot
verify a C2 message, which `tests/test_gui_auth.py` asserts.

- `?k=<token>` or an `X-Venator-Token` header, compared with
  `secrets.compare_digest`, with a growing delay on failure.
- **Fail safe, not open:** no key file → binds `127.0.0.1` only and prints
  `python3 radio/auth.py --init`.
- Every address it became reachable on is logged by name at startup. On the
  school SSID, that line is the warning.

---

## Field behaviour that took deliberate work

| Hazard | What was done |
|---|---|
| One thread per stream, phone locking and unlocking, **zero swap on this box** | `MAX_VIEWERS = 8`, then `503`. Verified: eight `200`s and two `503`s |
| Operator walks out of range, TCP goes silent, a write blocks forever | `connection.settimeout(10)` turns it into an `OSError` the handler already catches. Verified: 60 connect/disconnect cycles, thread count flat at 26 |
| `BaseHTTPRequestHandler` defaults to HTTP/1.0 | `protocol_version = "HTTP/1.1"` plus `Connection: close` on both streaming routes |
| Browsers cap ~6 connections per origin; MJPEG + SSE take two | Filmstrip thumbnails are `loading="lazy"` |
| iOS Safari suspends `EventSource` on lock | `: ping` comment frames, SSE `id:` for `Last-Event-ID`, acked alert ids in `sessionStorage` so a reconnect does not re-alarm |
| A slow viewer stalling the camera | `frames()` yields **outside** the lock and only ever reads the newest JPEG. Lifted verbatim from `camera_publisher.py:204-218`. Verified: 500 frames published past a stalled viewer in 1 ms |
| A missed SAR alert | `det`/`status` coalesce and drop freely; `alert`/`evidence` go in a bounded per-viewer deque, delivered at least once. Verified: 3 alerts survive 200 intervening detections |

---

## Field UI

Night-vision friendly means **red/amber dominant**: blue and white light
destroy scotopic adaptation for tens of minutes, and the operator has to look
up and find a drone afterwards. Dark is forced — there is no
`prefers-color-scheme: light` branch, because a white screen here is a
usability fault rather than a preference.

- Background `#05070a`, text `#d8d2c6` — never pure white.
- **Amber** `animal`, **magenta** `person` (highest salience, and it stays
  distinct under a red filter), dim cyan `vehicle`.
- A red-filter toggle and a black-overlay dimmer, since a browser cannot reach
  the backlight.
- Status chips in one scrolling row: fps, model, power mode, board draw, SoC
  temp, USB link speed, RSSI, GPS, detection counts.
- **SAR banner: sticky, no auto-dismiss, explicit ack tap**, with vibration and
  a beep armed on first gesture (iOS blocks audio before interaction).
- One-tap ✓/✗ on each evidence thumbnail → `POST /api/verdict` → sidecar JSON.
  Every evidence frame is in-domain training data for the species classifier
  that does not exist yet, and the operator's tap is its label.

---

## Tracking

The loop reads **tracklets**, not raw detections — same boxes, plus a stable
id, an age and a status. `dai.node.ObjectTracker` runs on the camera with
`ZERO_TERM_IMAGELESS`, which uses no image features, so it costs no SHAVE cores
and no CMX. Measured: **still 10.0 fps** with the tracker, both encoders,
stereo and the network all running.

Two settings carry the weight:

- `setSpatialAssociation(True)` — associate on the stereo Z as well as image
  overlap. Image-plane IOU alone is unreliable when the camera translates
  between frames, which on a drone it always does.
- `UNIQUE_ID` rather than `SMALLEST_ID` — ids must never be recycled, or a
  count of distinct animals over a sortie is meaningless and a SAR alert could
  name a track that has since become a different subject.

`drone/wildlife/tracking.py` keeps the host-side history: dwell, a **voted**
class (summed confidence across sightings, so a track seen at several scales
settles on one answer instead of flickering), and metric displacement from
stereo X/Z. Displacement is never computed from pixels — the aircraft moves, so
pixel motion describes the drone as much as the subject. That is the input the
SAR prone-detection gate needs.

`counts` in the status stream is now **distinct objects by tracker id**, so
"3 animals" means three creatures rather than three frames that each contained
one.

`LOST` counts as active. It means the tracker did not detect the object this
frame but is predicting its position — precisely the grace a dwell window
needs, since otherwise one missed frame would reset an 8-second SAR timer. The
camera promotes `LOST` to `REMOVED` once it gives up.

## Evidence

Frames are written straight from the encoder — the bytes are already a JPEG, so
there is no decode, no PIL and no re-encode. The previous path pulled a raw
`BGR888p` passthrough frame purely so boxes could be burned in, which cost
about **35 Mbps of USB bandwidth**. Boxes live in the browser now, so the frame
goes to disk untouched.

**Saving is throttled.** Every detection frame used to become a file: a subject
in view at 10 fps wrote ten JPEGs a second, roughly 18 MB a minute, and the
filmstrip showed forty copies of one second rather than forty sightings. It
also wasted the archive's purpose — forty near-identical frames are one
training example, not forty.

The rule now: **a genuinely new track always earns a frame; otherwise a
`GUI_SAVE_INTERVAL` floor applies (default 2 s).** So a creature walking into
frame is never missed, and one standing still cannot flood the disk.

Each frame gets a `.json` sidecar with its detections and, once an operator
taps ✓/✗, their verdict.

### Reviewing a frame

Tap any thumbnail to open it full-screen with **its boxes drawn on** — replayed
from the sidecar's normalised coordinates, which are the same 16:9 crop the
network saw, so they land untransformed exactly as on the live canvas. The
saved JPEG itself stays clean.

Arrow keys, swipe or the ‹ › buttons move between frames; Escape or a tap
outside closes. The ✓/✗ verdict buttons are there too, which is easier to judge
on a large image than a 104-pixel thumbnail. The open frame is tracked **by
filename, not index** — new detections unshift onto the list, so an index would
silently slide the picture out from under whoever is reviewing it.

> **Imagery of people.** The `person` class means this can accumulate
> photographs of people. Keep SAR evidence on its own retention and separate
> from the wildlife corpus. Not yet implemented — tracked in
> `drone/wildlife/config/STATE.txt`.

---

## Ports

`ports.py` is the single source of truth. `camera_publisher.py` and
`phone_relay.py` both defaulted to 8080 and nothing caught it, because neither
is a boot service — it would have surfaced in the field as one failing to bind.

| Port | Owner |
|---|---|
| 8080 | Operator GUI (and the old camera stream — only one can own the OAK anyway) |
| 8081 | `radio/phone_relay.py` |
| 5005/udp | Person coordinates → `c2_server.py` |
| 5006/udp | Detection alerts, so a coordinate packet cannot shadow one |

---

## Only one process owns the OAK

The device allows exactly one host process. `oak_camera.sh check_free()` now
knows about `gui_server.py` as well as the detector and the flight tracker —
without that the GUI was invisible to the arbitration and you got a bare
`X_LINK_DEVICE_ALREADY_IN_USE` twenty seconds in, which is the exact failure
that function exists to prevent.

```
./drone/wildlife/oak_camera.sh status     # who has it
```

---

## Verifying it

```bash
python3 tests/test_gui_auth.py                      # 59 assertions, no camera

./drone/wildlife/oak_camera.sh gui                  # then, from another shell:
curl -s localhost:8080/healthz                      # -> ok
curl -s "localhost:8080/api/status?k=$TOK" | python3 -m json.tool
curl -sN "localhost:8080/events?k=$TOK" | head -20  # SSE frames
curl -o /dev/null -w '%{http_code}\n' localhost:8080/api/status          # -> 403
curl -o /dev/null -w '%{http_code}\n' \
  "localhost:8080/api/evidence/../../etc/passwd?k=$TOK"                  # -> 40x
```

Thread-leak check, which is the one that matters in the field — lock and unlock
the phone twenty times, then:

```bash
ls /proc/$(pgrep -f 'python.*gui_server')/task | wc -l   # must not grow
```

Measure power with `tegrastats` while a viewer is attached; the video path
should be invisible in it.
