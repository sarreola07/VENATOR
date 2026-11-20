#!/usr/bin/env python3
"""
The judges' numbers for the vest search, computed from what the search already
reports: how fast it locks, whether it ever locks onto the wrong person, and
how far apart the target and the decoys read.

Fed one detection frame at a time from gui_server.search_step(), after
VestSearch.process() has added "role", "vest" and "match" to each person. Costs
a handful of dict updates per frame, which is what a 7 W Jetson can afford.

  * time to lock: seconds from the first measured sighting of a track to the
    FOUND that locked onto it. The demo claim is "TARGET within about a
    second"; this is that number, for the last find and as a median.
  * wrong locks: a FOUND whose person is wearing a vest that is not the target
    colour. By construction this should stay at zero, which is exactly the
    point of showing it. The operator can also mark one by hand from the page
    the moment a decoy is seen with TARGET on it; both are counted, separately.
  * match share: the running mean of the target's chest share against the best
    non-target person's, so the gap the vote relies on is visible as a number.

Stdlib only, like vest.py, so CI pins it with no camera.
"""
import statistics

from vest import MEASURED

#: Forget a track's first sighting this long after it was last seen.
FORGET_AFTER_S = 60.0


class _Mean:
    __slots__ = ("n", "total")

    def __init__(self):
        self.n = 0
        self.total = 0.0

    def add(self, value):
        self.n += 1
        self.total += value

    @property
    def value(self):
        return self.total / self.n if self.n else None


class SearchMetrics:
    """Running numbers for one search target. reset() on a new target."""

    def __init__(self):
        self.reset()

    def reset(self, target=None):
        self.target = target
        self._first_seen = {}      # track id -> when first measured
        self._last_seen = {}       # track id -> when last measured
        self.ttl_last = None
        self.ttls = []
        self.wrong_locks = 0       # seen in the data
        self.wrong_marked = 0      # marked by the operator
        self._match_target = _Mean()
        self._match_decoy = _Mean()
        self.state = None
        self.state_since = None
        self.finds = 0
        self.people = 0
        self.ignored = 0
        self.closest_m = None
        self.frames = 0

    def mark_wrong_lock(self):
        self.wrong_marked += 1

    def update(self, report, dets, now):
        """Absorb one frame's report and its detections."""
        if report is None:
            return
        if report.get("target") != self.target:
            self.reset(report.get("target"))
        if self.target is None:
            return
        self.frames += 1
        people = [d for d in dets if d.get("c") == "person" and d.get("st") in MEASURED]
        for d in people:
            self._first_seen.setdefault(d["id"], now)
            self._last_seen[d["id"]] = now
        for tid in [t for t, seen in self._last_seen.items() if now - seen > FORGET_AFTER_S]:
            self._first_seen.pop(tid, None)
            self._last_seen.pop(tid, None)

        # The target's share against the best of the people the search ignores.
        # Someone still being voted on ("checking") is neither yet, and before
        # the lock the real target is exactly that person.
        best_decoy = None
        for d in people:
            match = d.get("match")
            if not isinstance(match, (int, float)):
                continue
            if d.get("role") == "target":
                self._match_target.add(match)
            elif d.get("role") == "ignored" and (best_decoy is None or match > best_decoy):
                best_decoy = match
        if best_decoy is not None:
            self._match_decoy.add(best_decoy)

        if report.get("found_now"):
            tid = report.get("id")
            first = self._first_seen.get(tid)
            if first is not None:
                self.ttl_last = round(now - first, 2)
                self.ttls.append(self.ttl_last)
            locked = next((d for d in dets if d.get("id") == tid), None)
            if locked is not None and locked.get("vest") not in (None, self.target):
                self.wrong_locks += 1

        state = report.get("state")
        if state != self.state:
            self.state, self.state_since = state, now
        self.finds = report.get("found", self.finds) or 0
        self.people = report.get("people", 0) or 0
        self.ignored = report.get("ignored", 0) or 0
        self.closest_m = report.get("closest_m")
        self._now = now

    def snapshot(self):
        """What the page and /api/metrics show. Shares are 0..1."""
        now = getattr(self, "_now", None)
        target, decoy = self._match_target.value, self._match_decoy.value
        return {
            "target": self.target,
            "frames": self.frames,
            "ttl_last_s": self.ttl_last,
            "ttl_median_s": round(statistics.median(self.ttls), 2) if self.ttls else None,
            "finds": self.finds,
            "wrong_locks": self.wrong_locks + self.wrong_marked,
            "wrong_locks_seen": self.wrong_locks,
            "wrong_locks_marked": self.wrong_marked,
            "match_target": round(target, 3) if target is not None else None,
            "match_decoy": round(decoy, 3) if decoy is not None else None,
            "people": self.people,
            "ignored": self.ignored,
            "closest_m": self.closest_m,
            "state": self.state,
            "state_s": (round(now - self.state_since, 1)
                        if now is not None and self.state_since is not None else None),
        }
