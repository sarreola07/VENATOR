#!/usr/bin/env python3
"""
Which person is the one we are looking for.

The search-and-rescue demonstration: a report says the missing person was last
seen in a red vest. The network finds people; this module decides which of them
match the description and calls everyone else "ignored".

Ignored means ignored for targeting, never for safety. Every person the detector
reports still counts toward closest_m, because someone in a blue vest walking up
to the aircraft is exactly as dangerous as someone in a red one. That is only
as far as the camera can see: it faces forward, so nobody behind the aircraft is
counted, and the flight zone has to cover that.

Why a colour rule and not a retrained network: it needs no dataset, it costs
about 0.3 ms per person on a laptop (not yet measured on the Jetson), and every
decision can be explained by pointing at the numbers. It also has a known limit
worth stating out loud: it matches a description, so a red shirt looks the same
as a red vest.

The rule, in order:

  * a person has to be detected first, so a red bin is never a candidate;
  * the chest of the box has to be mostly one colour, clearly ahead of the next;
  * one frame proves nothing, so a track has to vote the same way across about
    a second (ColourVote) before it counts. The expensive mistake here is
    locking onto the wrong person, and a wrong answer that flickers can't get
    through a vote;
  * once locked, the search stays on that track id. A second match is reported,
    not switched to. The ids are UNIQUE_ID (see gui_server.py), so a person who
    disappears and comes back is a new track and has to earn the vote again.

Stdlib only at import, and it never imports depthai: frames reach this module
as lists of pixels, so CI runs exactly the logic the aircraft runs.
"""
import collections
import colorsys
import json
import math
import os
import socket
from pathlib import Path

COLOURS = ("red", "yellow", "blue")

#: Starting values, wide enough to find a vest and meant to be replaced by
#: vest_calibrate.py in the room being flown in. Hue is in degrees and red wraps
#: through zero, so a range whose low end is above its high end crosses 360.
#: Blue's saturation floor is high on purpose: denim sits in the same hue as a
#: blue vest, at about 0.45 saturation. Red's range stops at 15 degrees on purpose:
#: skin under warm light and orange safety vests start just past it, so red is the
#: colour most worth calibrating.
DEFAULT_RANGES = {
    "red":    {"hue": [345, 15],  "sat": 0.45, "val": 0.25},
    "yellow": {"hue": [40, 80],   "sat": 0.45, "val": 0.35},
    "blue":   {"hue": [195, 255], "sat": 0.55, "val": 0.20},
}

#: A chest has to be this much one colour, and this far ahead of the runner-up.
#: Well under half, because a vest is broken up by reflective strips and arms.
MIN_SHARE = 0.30
MIN_LEAD = 0.10

#: Pixels sampled per person. A share only needs a few hundred samples to be
#: stable, and this keeps the cost flat however close the person stands.
MAX_PIXELS = 400

#: About a second at the detector's 10 fps. VOTE_KEEP is lower than
#: VOTE_CONFIRM so a confirmed vest survives someone walking past it, while
#: covering it still drops the match within a second.
VOTE_WINDOW = 10
VOTE_CONFIRM = 8
VOTE_KEEP = 3
#: This many clear readings of another colour in a row end a confirmed vest at
#: once. Stronger evidence than a missing reading: it is what a tracker looks like
#: when it has swapped two people's ids, and it shortens the time spent on the
#: wrong person from about 0.8 s to 0.3 s.
VOTE_CONTRADICT = 3

#: Beyond this a person is not a candidate, which keeps the far end of a hall
#: out of the search. Stereo depth is also least trustworthy out there.
MAX_RANGE_M = 8.0

#: Long-axis size from gui_server.py's len_m. Low enough for someone whose legs
#: are out of frame, high enough to reject what the detector calls a person but
#: isn't one (it scores a wild turkey as "person" at about 71%).
MIN_LEN_M = 0.8
MAX_LEN_M = 2.6

#: A lock outlives the tracker's own ~1 s of prediction, then lets go.
LOCK_LOST_S = 2.0
#: A missed frame or two is not "lost". Saying so only after this long keeps the
#: state from flipping on every dropout, while `visible` and the coordinates still
#: stop at once, so nothing can steer by a stale position.
LOST_GRACE_S = 1.0
#: How much a new box must overlap a recently lost one to be the same person, and
#: how many of its first readings can still pick that history up.
MATCH_IOU = 0.3
INHERIT_WITHIN_FRAMES = 3
#: Regaining the target this soon after last seeing it is the same find, not a
#: new one. A detector that drops someone for a moment gives them a new track, and
#: that must not raise another alert or save another photo each time. Measured on
#: a webcam: four FOUND alerts in 36 seconds for one person sitting still.
SAME_FIND_S = 30.0
#: Frames before a track counts as a person ignored, so a one-frame false
#: detection doesn't inflate the number the audience is shown.
IGNORED_MIN_FRAMES = 5
FORGET_AFTER_S = 30.0

#: Tracker states whose box is a measurement. The others are predictions, and a
#: predicted box can sit on whoever walked through that spot next.
MEASURED = frozenset({"NEW", "TRACKED"})

#: A box reaching this far down touches the bottom of the frame...
FRAME_BOTTOM_Y = 0.97
#: ...and is only head and torso if it is also no taller than this, in real pixels.
#: Someone whole is about three times taller than wide, and can stand with their
#: feet at the frame's edge, so the edge alone doesn't mean their legs are cut off.
TORSO_ONLY_ASPECT = 1.8
#: Both cameras are 16:9, and boxes are normalised to each side separately.
FRAME_ASPECT = 16 / 9

CALIBRATION_FILE = Path.home() / ".venator" / "vest-colours.json"


def iou(a, b):
    """Overlap of two [x1, y1, x2, y2] boxes, 0..1."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    shared = w * h
    return shared / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - shared)


# --- one chest ---------------------------------------------------------------

def chest_box(box):
    """The chest of a normalised person box: the middle half of its width.

    Staying off the edges keeps out the background and the arms. For a whole
    person it is 20-55% of the height, which stops above the waist and keeps out
    blue jeans. With the legs cut off by the frame the box is only head and torso,
    so that would be the face: 45-85% is the chest instead. Measured at a desk on a
    webcam, a red shirt read 19% the first way, under the 30% it takes to count.
    """
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    torso_only = (y2 >= FRAME_BOTTOM_Y and w > 0
                  and h / (w * FRAME_ASPECT) <= TORSO_ONLY_ASPECT)
    top, bottom = (0.45, 0.85) if torso_only else (0.20, 0.55)
    return (x1 + 0.25 * w, y1 + top * h, x1 + 0.75 * w, y1 + bottom * h)


def chest_pixels(rgb, box, max_pixels=MAX_PIXELS):
    """Up to about max_pixels (r, g, b) values from the chest of a person box.

    `rgb` is the (h, w, 3) array from oak_wildlife.to_rgb. Slicing is the only
    thing asked of it, so this module stays importable without numpy.
    """
    height, width = rgb.shape[:2]
    x1, y1, x2, y2 = chest_box(box)
    x0, x1 = max(0, int(x1 * width)), min(width, int(x2 * width))
    y0, y1 = max(0, int(y1 * height)), min(height, int(y2 * height))
    if x1 <= x0 or y1 <= y0:
        return []
    step = max(1, math.ceil(math.sqrt((x1 - x0) * (y1 - y0) / max_pixels)))
    return rgb[y0:y1:step, x0:x1:step].reshape(-1, 3).tolist()


def in_hue(hue, lo, hi):
    """True when hue (degrees) lies in [lo, hi], which may wrap through 360."""
    return lo <= hue <= hi if lo <= hi else hue >= lo or hue <= hi


def shares(pixels, ranges):
    """colour name -> the fraction of these pixels inside that colour's range."""
    counts = dict.fromkeys(ranges, 0)
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        h *= 360.0
        for name, want in ranges.items():
            if s >= want["sat"] and v >= want["val"] and in_hue(h, *want["hue"]):
                counts[name] += 1
    total = len(pixels) or 1
    return {name: n / total for name, n in counts.items()}


def pick(colour_shares):
    """The colour this chest clearly is, or None."""
    ranked = sorted(colour_shares.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked or ranked[0][1] < MIN_SHARE:
        return None
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < MIN_LEAD:
        return None
    return ranked[0][0]


# --- one track ---------------------------------------------------------------

class ColourVote:
    """What colour one tracked person is wearing, voted across frames."""

    def __init__(self):
        self._recent = collections.deque(maxlen=VOTE_WINDOW)
        self.colour = None

    def update(self, seen):
        self._recent.append(seen)
        if (self.colour is not None and self._recent.count(self.colour) >= VOTE_KEEP
                and not self._contradicted()):
            return
        self.colour = next((c for c in COLOURS
                            if self._recent.count(c) >= VOTE_CONFIRM), None)

    def _contradicted(self):
        latest = list(self._recent)[-VOTE_CONTRADICT:]
        return (len(latest) == VOTE_CONTRADICT
                and all(c is not None and c != self.colour for c in latest))

    def count(self, colour):
        return self._recent.count(colour)


class _Seen:
    __slots__ = ("vote", "last_seen", "frames", "match", "box")

    def __init__(self, now):
        self.vote = ColourVote()
        self.last_seen = now
        self.frames = 0
        #: How much of the chest is the target colour, 0..1. What the phones
        #: graph, so the decision can be watched rather than taken on trust.
        self.match = 0.0
        #: Where this person last actually was: measured, never predicted.
        self.box = None


# --- the search --------------------------------------------------------------

class VestSearch:
    """Labels each person in a frame and reports what the search has found.

    process() takes gui_server.py's detection dicts, adds "vest" and "role" to
    each person, and returns the report the flight code and the phones read.

    Roles: target (the locked person), match (also fits, not locked), checking
    (the vote is under way), ignored (everyone else).
    """

    def __init__(self, target=None, ranges=None, use_depth=True):
        self.ranges = ranges or DEFAULT_RANGES
        #: False for a camera with no depth (webcam_search.py). The range and
        #: size gates then have nothing to read, and closest_m stays None, so
        #: this must never be how the aircraft runs.
        self.use_depth = use_depth
        self.target = None
        self._tracks = {}
        self._reset()
        self.set_target(target)

    def _reset(self):
        self._locked = None
        self._target_seen_at = None
        self.found_count = 0

    def set_target(self, colour):
        """Start searching for this colour, or stop with None.

        Repeating the current target changes nothing, so the sender can repeat
        it as a heartbeat without restarting the search each time. The votes
        are kept on purpose: what someone is wearing doesn't depend on who we
        are looking for.
        """
        if colour is not None and colour not in COLOURS:
            return False
        if colour != self.target:
            self.target = colour
            self._reset()
        return True

    def _eligible(self, det, track):
        """Could this person be locked onto, in this frame?"""
        if track.vote.colour != self.target or det.get("st") not in MEASURED:
            return False
        if not self.use_depth:
            return True
        z = _depth(det)
        size = det.get("len_m")
        return (z is not None and z <= MAX_RANGE_M
                and size is not None and MIN_LEN_M <= size <= MAX_LEN_M)

    def process(self, dets, sample, now):
        """Absorb one detection frame. `sample(box)` returns a person's chest
        pixels, or is None when there is no colour frame to read.

        Anything steering by the report must use `visible` and the coordinates.
        `state` stays "found" through a brief dropout, for people to read.
        """
        people = [d for d in dets
                  if d.get("c") == "person" and d.get("st") != "REMOVED"]
        in_frame = {d["id"] for d in people if d.get("st") in MEASURED}
        closest = None
        for d in people:
            track = self._tracks.get(d["id"])
            if track is None:
                track = self._tracks[d["id"]] = _Seen(now)
            track.last_seen = now
            if sample is not None and d.get("st") in MEASURED:
                seen = shares(sample(d["b"]), self.ranges)
                colour = pick(seen)
                if track.frames < INHERIT_WITHIN_FRAMES:
                    self._inherit(d, track, colour, in_frame, now)
                track.vote.update(colour)
                track.frames += 1
                track.match = seen.get(self.target, 0.0)
                track.box = d["b"]
            d["vest"] = track.vote.colour
            d["match"] = round(track.match, 2)
            d["votes"] = track.vote.count(self.target) if self.target else 0
            z = _depth(d)
            if z is not None and (closest is None or z < closest):
                closest = z

        report = {"target": self.target, "state": "idle", "people": len(people),
                  "closest_m": closest}
        self._expire(now)
        if self.target is None:
            return report

        found_now = self._update_lock(people, now)
        locked = None
        matches = 0
        checking = False
        # People ignored in this frame, not ids ever ignored. Ids are not people:
        # a dropout gives the same person a new one, so a running total read
        # "16 ignored" with one person in the room.
        ignored = 0
        for d in people:
            track = self._tracks[d["id"]]
            if d["id"] == self._locked:
                d["role"] = "target"
                locked = d
                matches += 1
            elif self._eligible(d, track):
                d["role"] = "match"
                matches += 1
            elif track.vote.count(self.target) >= 2 and d.get("st") in MEASURED:
                d["role"] = "checking"
                checking = True
            else:
                d["role"] = "ignored"
                # Only someone actually measured here. A track whose history just
                # moved to a new id is still fading out, and is not a second person.
                ignored += (track.frames >= IGNORED_MIN_FRAMES
                            and d.get("st") in MEASURED)

        # Someone leaving the frame gets one last box. Without a role it would
        # flash in the detector's colour, the loudest thing on the page.
        for d in dets:
            if d.get("c") == "person" and d.get("st") == "REMOVED":
                d["role"] = "ignored"

        report.update(ignored=ignored, matches=matches,
                      found=self.found_count, min_share=MIN_SHARE,
                      vote_need=VOTE_CONFIRM)
        if self._locked is not None:
            visible = locked is not None and locked.get("st") in MEASURED
            if visible:
                self._target_seen_at = now
            recent = now - self._target_seen_at <= LOST_GRACE_S
            report.update(state="found" if recent else "lost",
                          id=self._locked, visible=visible)
            if visible:
                report["conf"] = locked.get("p", 0.0)
                # No position without depth. The device reports 0, 0, 0 then,
                # which would read as "dead ahead, on the lens".
                if _depth(locked) is not None:
                    x, y, z = locked["xyz"]
                    report.update(x=x, y=y, z=z)
        else:
            report["state"] = "checking" if checking else "searching"
        if found_now:
            report["found_now"] = True
        return report

    def _inherit(self, det, track, colour, in_frame, now):
        """Give a new id the history of the track it continues, if there is one.

        A detector that drops someone for a moment hands them a new id, which would
        otherwise cost them their vote and any lock, over and over, while they stand
        still. It has to be the same place and a colour that track was already seen
        in, so a decoy stepping into the spot someone just left inherits nothing. A
        lock only moves on a clear reading of the target colour itself.
        """
        if colour is None:
            return
        for tid, old in self._tracks.items():
            if (old is track or tid in in_frame or old.box is None
                    or now - old.last_seen > LOCK_LOST_S
                    or old.vote.count(colour) == 0
                    or iou(det["b"], old.box) < MATCH_IOU):
                continue
            if tid == self._locked:
                if colour != self.target:
                    continue
                self._locked = det["id"]
            track.vote, track.frames = old.vote, old.frames
            # Spent, so two new ids can't both claim one history. Left in place
            # rather than deleted, because this frame may still have its box.
            old.vote, old.box = ColourVote(), None
            return

    def _update_lock(self, people, now):
        """Release a lock that no longer holds, then take one if free.

        Returns True only for a new find, not for regaining the same target.
        """
        if self._locked is not None:
            track = self._tracks.get(self._locked)
            if (track is None or track.vote.colour != self.target
                    or now - track.last_seen > LOCK_LOST_S):
                self._locked = None
        if self._locked is not None:
            return False
        ready = [d for d in people if self._eligible(d, self._tracks[d["id"]])]
        if not ready:
            return False
        self._locked = min(ready, key=_nearness)["id"]
        if (self._target_seen_at is not None
                and now - self._target_seen_at <= SAME_FIND_S):
            return False
        self.found_count += 1
        return True

    def _expire(self, now):
        for tid in [t for t, s in self._tracks.items()
                    if now - s.last_seen > FORGET_AFTER_S and t != self._locked]:
            del self._tracks[tid]


def _depth(det):
    """A person's stereo distance in metres, or None when depth has no answer.

    The device reports 0 when it found no valid depth in the box. That is an
    absence of a reading, not a person standing on the lens.
    """
    xyz = det.get("xyz")
    return xyz[2] if xyz and xyz[2] > 0 else None


def _nearness(det):
    """Sorts nearest first: by depth, or by the biggest box without any."""
    z = _depth(det)
    if z is not None:
        return z
    x1, y1, x2, y2 = det["b"]
    return -(x2 - x1) * (y2 - y1)


def found_alert(report, stamp):
    """The phone alert for a new lock, in the shape gui_page.py already renders."""
    alert = {
        "id": f"found-{report['found']}-{int(stamp)}",
        "kind": f"missing_person_found_{report['target']}_vest",
        "conf": report.get("conf", 0.0),
    }
    if "z" in report:
        alert["rel"] = {"rng": round(report["z"], 1),
                        "brg": round(math.degrees(math.atan2(report["x"], report["z"])))}
    return alert


# --- calibration -------------------------------------------------------------

def fit_range(pixels, min_sat=0.35, min_val=0.2, coverage=0.90, pad=8,
              widest=120):
    """A colour range from pixels of one vest, or None if they aren't one colour.

    Finds the shortest arc of hue holding `coverage` of the colourful pixels.
    Shortest arc rather than growing out from the peak, because a red vest can
    land on both sides of zero with a gap between, and growing the wrong way
    would swallow the whole circle. Grey, black and white are dropped first:
    their hue means nothing, and a reflective strip would pull the range sideways.
    """
    colourful = []
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        if s >= min_sat and v >= min_val:
            colourful.append((h * 360.0, s, v))
    if len(colourful) < max(20, 0.25 * len(pixels)):
        return None

    width = 5
    bins = [0] * (360 // width)
    for h, _, _ in colourful:
        bins[int(h // width) % len(bins)] += 1
    arc = None
    for length in range(1, widest // width + 1):
        held, start = max((sum(bins[(s + i) % len(bins)] for i in range(length)), s)
                          for s in range(len(bins)))
        if held >= coverage * len(colourful):
            arc = (start, length)
            break
    if arc is None:
        return None

    hue_lo = (arc[0] * width - pad) % 360
    hue_hi = ((arc[0] + arc[1]) * width + pad) % 360
    inside = [(s, v) for h, s, v in colourful if in_hue(h, hue_lo, hue_hi)]
    sats = sorted(s for s, _ in inside)
    vals = sorted(v for _, v in inside)
    return {"hue": [hue_lo, hue_hi],
            "sat": round(max(0.25, sats[len(sats) // 10] * 0.7), 2),
            "val": round(max(0.15, vals[len(vals) // 10] * 0.6), 2)}


def overlaps(ranges):
    """Pairs of colours whose hue ranges share any degree."""
    arcs = {name: {d for d in range(360) if in_hue(d, *want["hue"])}
            for name, want in ranges.items()}
    names = sorted(arcs)
    return [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
            if arcs[a] & arcs[b]]


def _clean_range(want):
    """A colour range with its numbers checked and converted, or None if unusable.

    Converted, not just checked: a saved "0.5" would pass a check and then raise
    on every pixel, once per frame, for the whole search.
    """
    try:
        lo, hi = want["hue"]
        clean = {"hue": [float(lo), float(hi)],
                 "sat": float(want["sat"]), "val": float(want["val"])}
    except (KeyError, TypeError, ValueError):
        return None
    if (0 <= clean["hue"][0] < 360 and 0 <= clean["hue"][1] < 360
            and 0 <= clean["sat"] <= 1 and 0 <= clean["val"] <= 1):
        return clean
    return None


def calibration_path():
    return Path(os.environ.get("VENATOR_VEST_FILE") or CALIBRATION_FILE)


def load_calibration(path=None):
    """(ranges, white balance in kelvin or None, where the ranges came from).

    A missing or damaged file falls back to the defaults rather than stopping
    the camera, and the third value says so, because the defaults are a much
    weaker answer than a calibration done in the room.
    """
    path = Path(path) if path else calibration_path()
    try:
        data = json.loads(path.read_text())
        saved = data["ranges"]
        ranges = {name: _clean_range(saved.get(name) or {}) for name in COLOURS}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return DEFAULT_RANGES, None, "built-in defaults"
    damaged = [name for name in COLOURS if ranges[name] is None]
    for name in damaged:
        ranges[name] = DEFAULT_RANGES[name]
    wb_k = data.get("wb_k")
    wb_k = wb_k if isinstance(wb_k, int) and 1000 <= wb_k <= 12000 else None
    source = str(path) + (f" (defaults for {', '.join(damaged)})" if damaged else "")
    return ranges, wb_k, source


def save_calibration(ranges, wb_k=None, path=None):
    path = Path(path) if path else calibration_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ranges": ranges, "wb_k": wb_k}, indent=1))
    return path


# --- the link to the flight code --------------------------------------------

class SearchLink:
    """Loopback UDP: the target comes in, the report goes out.

    Loopback is the point. Nothing on the Wi-Fi network, including a phone in the
    audience, can change who the aircraft is looking for. The target is meant to
    come from the LoRa remote through c2_server.py. That side isn't built yet.

    Separate ports from ports.CAMERA_COORDS_UDP, because Mission 1 and Mission 2
    read every packet on that one as a person's coordinates.
    """

    def __init__(self, target_port, report_port, log=print):
        self._report_addr = ("127.0.0.1", report_port)
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx.setblocking(False)
        try:
            self._rx.bind(("127.0.0.1", target_port))
        except OSError as exc:
            log(f"search target port {target_port} unavailable ({exc}); "
                "the target stays as started")
            self._rx.close()
            self._rx = None

    def poll_target(self, search):
        """Apply any target commands waiting on the socket."""
        for _ in range(20 if self._rx else 0):
            try:
                data, _addr = self._rx.recvfrom(256)
            except OSError:
                return
            try:
                search.set_target(json.loads(data.decode())["target"])
            except (ValueError, KeyError, TypeError):
                pass

    def send(self, report):
        try:
            self._tx.sendto(json.dumps(report, separators=(",", ":")).encode(),
                            self._report_addr)
        except OSError:
            pass        # the flight code must treat silence as stale data
