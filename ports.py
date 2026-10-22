#!/usr/bin/env python3
"""Every TCP/UDP port this project binds, in one place.

Two servers both defaulted to 8080 - drone/camera_publisher.py's video stream
and radio/phone_relay.py's LoRa chat page. Nothing caught it because neither is
a boot service, so the collision would have surfaced the first time both ran in
the field, as one of them failing to bind.

8080 belongs to the operator GUI: it is the port deploy/wifi_mode.sh,
drone/camera.sh, both READMEs and the printed stream URLs already advertise, so
moving it would mean correcting all of those.

Every value can be overridden by its environment variable, which is how the
existing scripts already expose them.

Stdlib only.
"""
import os


def _port(env, default):
    """An int port from the environment, falling back to `default`.

    A malformed value falls back rather than crashing: being unreachable on the
    expected port is a better failure than a camera process that will not
    start at all.
    """
    raw = os.environ.get(env)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if 1 <= value <= 65535 else default


# --- HTTP -------------------------------------------------------------------
#: Operator GUI: live MJPEG, detections over SSE, evidence review.
GUI_HTTP = _port("CAMERA_STREAM_PORT", 8080)
#: radio/phone_relay.py — LoRa chat relay for a phone. Moved off 8080.
PHONE_RELAY_HTTP = _port("PHONE_RELAY_PORT", 8081)

# --- UDP, loopback only -----------------------------------------------------
# The CV side never opens the flight controller's serial port; it publishes
# here and c2_server.py (which owns the FC link) consumes. See drone/camera.sh.
#: Nearest-person coordinates, read by missions.py and c2_server.py.
CAMERA_COORDS_UDP = _port("CAMERA_UDP_PORT", 5005)
#: Detection events that must not be shadowed by a following coordinate packet.
#: _read_person() keeps only the latest of a drained batch, so an alert sharing
#: CAMERA_COORDS_UDP could be dropped in the same tick. Separate port instead.
ALERTS_UDP = _port("ALERTS_UDP_PORT", 5006)


if __name__ == "__main__":
    for name, value in sorted(
            (k, v) for k, v in globals().items()
            if k.isupper() and isinstance(v, int)):
        print(f"{name:<20} {value}")
