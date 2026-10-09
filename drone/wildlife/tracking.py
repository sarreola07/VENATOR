#!/usr/bin/env python3
"""
Per-object history, built from the OAK's tracklets.

Until this existed the detector had no memory at all: every frame's detections
were consumed and discarded, so nothing could answer "how long has that been
there", "is it the same animal", or "how many distinct creatures walked past".
Three things needed that and could not be built without it:

  * dwell time, which the operator GUI shows per track;
  * `people_seen` in drone/c2_server.py, which counted rising edges and so
    turned one person flickering in and out of the detector into N people;
  * the SAR prone-detection gate, which has to know a subject has been
    motionless *and horizontal* for several continuous seconds, and has to
    measure displacement in metres rather than pixels because the camera is
    moving.

The tracker itself runs on the camera (`dai.node.ObjectTracker`,
ZERO_TERM_IMAGELESS, so no image features and no SHAVE cost). This module is
the host-side bookkeeping on top of it.

Stdlib only, and it never imports depthai: tracklets are passed in as plain
values so this is testable in CI with no camera.
"""
import collections
import time

#: How much spatial history to keep per track. At 10 fps this is ~6 s, which
#: comfortably covers the 8-10 s dwell window the SAR gate wants while staying
#: bounded - a drone flight is long and the alternative grows without limit.
HISTORY = 64

#: A track is forgotten this long after its last sighting. Long enough that a
#: brief occlusion does not mint a new identity, short enough that a flight's
#: worth of tracks does not accumulate.
FORGET_AFTER_S = 30.0


class Track:
    """One tracked object's history."""

    __slots__ = ("id", "first_seen", "last_seen", "votes", "xyz", "peak_conf",
                 "status", "frames", "reported")

    def __init__(self, tid, now):
        self.id = tid
        self.first_seen = now
        self.last_seen = now
        #: class name -> summed confidence. Voting beats last-wins: a track
        #: seen at several scales and angles gets one stable answer instead of
        #: flickering between "animal" and "person" frame to frame.
        self.votes = {}
        self.xyz = collections.deque(maxlen=HISTORY)
        self.peak_conf = 0.0
        self.status = "NEW"
        self.frames = 0
        #: True once an evidence frame has been written for this track, so a
        #: creature standing still does not keep triggering saves.
        self.reported = False

    @property
    def dwell(self):
        return self.last_seen - self.first_seen

    @property
    def label(self):
        """The voted class, not the latest guess."""
        if not self.votes:
            return None
        return max(self.votes, key=self.votes.get)

    def displacement_m(self):
        """Straight-line metres between the oldest and newest fix.

        Computed from stereo X/Z, never from pixels: the aircraft is moving, so
        image-plane displacement says as much about the drone as the subject.
        Y is ignored - at survey altitude it is inside the stereo noise.
        """
        pts = [p for p in self.xyz if p is not None]
        if len(pts) < 2:
            return 0.0
        (x0, _, z0), (x1, _, z1) = pts[0], pts[-1]
        return ((x1 - x0) ** 2 + (z1 - z0) ** 2) ** 0.5

    def path_m(self):
        """Total distance walked, which separates pacing from genuine travel."""
        pts = [p for p in self.xyz if p is not None]
        total = 0.0
        for (x0, _, z0), (x1, _, z1) in zip(pts, pts[1:]):
            total += ((x1 - x0) ** 2 + (z1 - z0) ** 2) ** 0.5
        return total


class TrackBook:
    """Everything currently or recently tracked, keyed by tracker id.

    Feed it one frame of tracklets at a time. It does not care where they came
    from, only that each carries an id, a class name, a confidence, a status
    and optionally a metric (x, y, z).
    """

    def __init__(self, forget_after=FORGET_AFTER_S):
        self._tracks = {}
        self._forget_after = forget_after
        #: Distinct ids ever seen per class. This is what a "how many did we
        #: see" count must be built on, rather than counting detection events.
        self._seen_ids = {}

    def update(self, tracklets, now=None):
        """Absorb one frame. `tracklets` is a sequence of dicts:

            {"id": int, "cls": str, "conf": float, "status": str,
             "xyz": (x, y, z) | None}

        Returns the Track objects touched by this frame, in id order.
        """
        now = time.monotonic() if now is None else now
        touched = []
        for t in tracklets:
            tid = t["id"]
            track = self._tracks.get(tid)
            if track is None:
                track = self._tracks[tid] = Track(tid, now)
            track.last_seen = now
            track.status = t.get("status", "TRACKED")
            track.frames += 1
            cls, conf = t.get("cls"), float(t.get("conf") or 0.0)
            if cls:
                track.votes[cls] = track.votes.get(cls, 0.0) + conf
                self._seen_ids.setdefault(cls, set()).add(tid)
            track.peak_conf = max(track.peak_conf, conf)
            track.xyz.append(tuple(t["xyz"]) if t.get("xyz") else None)
            touched.append(track)
        self._expire(now)
        return sorted(touched, key=lambda x: x.id)

    def _expire(self, now):
        dead = [tid for tid, t in self._tracks.items()
                if now - t.last_seen > self._forget_after]
        for tid in dead:
            del self._tracks[tid]
        # _seen_ids is deliberately NOT pruned: it is the running total for the
        # sortie, and forgetting it would re-count a creature that wandered off
        # and came back.

    def new_tracks(self, touched):
        """Of these, the ones no evidence frame has been written for yet.

        This is what makes "one frame per creature" possible: a new animal
        always earns a frame, and one standing in view does not keep earning
        them.
        """
        return [t for t in touched if not t.reported and t.label]

    def mark_reported(self, tracks):
        for t in tracks:
            t.reported = True

    def active(self):
        """Everything the tracker still believes in, longest-standing first.

        LOST counts as active. It means the tracker did not detect the object
        this frame but is predicting its position, which is precisely the grace
        period a dwell window needs - without it, one missed frame would reset
        an 8-second SAR timer. The camera promotes LOST to REMOVED once it
        gives up (setTrackletMaxLifespan), so this cannot linger.

        Callers that want only confirmed sightings filter on status; the GUI
        fades any row whose status is not TRACKED.
        """
        return sorted((t for t in self._tracks.values() if t.status != "REMOVED"),
                      key=lambda x: -x.dwell)

    def distinct_count(self, cls=None):
        """How many distinct objects have been seen, by voted class.

        The honest answer to "how many people did we see", as opposed to
        counting the times the detector's output changed state.
        """
        if cls is not None:
            return len(self._seen_ids.get(cls, ()))
        return sum(len(v) for v in self._seen_ids.values())

    def counts(self):
        """Distinct-object counts per class, for a status line."""
        return {k: len(v) for k, v in sorted(self._seen_ids.items()) if v}

    def get(self, tid):
        return self._tracks.get(tid)

    def __len__(self):
        return len(self._tracks)
