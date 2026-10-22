#!/usr/bin/env python3
"""Per-object history from tracker ids.

The behaviour that matters, and why:

  * one object seen over many frames is ONE object. Counting detection events
    instead is the bug in drone/c2_server.py's `people_seen`, where a person
    flickering in and out of the detector became N people;
  * the class is voted across sightings rather than taken from the last frame,
    so a track seen at several scales settles on one answer;
  * displacement is metres from stereo X/Z, never pixels - the aircraft moves,
    so pixel motion describes the drone as much as the subject. This is the
    input to the SAR prone-detection gate;
  * a track earns exactly one evidence frame, which is what stops a motionless
    subject writing ten JPEGs a second.

Stdlib only, no camera, no depthai: tracklets are plain dicts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "drone" / "wildlife"))

import tracking  # noqa: E402

PASS = FAIL = 0


def check(label, got, want=True):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"    {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"   got {got!r}"))


def tl(tid, cls="animal", conf=0.8, status="TRACKED", xyz=(0.0, 0.0, 10.0)):
    return {"id": tid, "cls": cls, "conf": conf, "status": status, "xyz": xyz}


print("\nOne object over many frames is one object")
b = tracking.TrackBook()
for i in range(50):
    b.update([tl(7)], now=100.0 + i * 0.1)
check("one track exists", len(b), 1)
check("counted once, not fifty", b.distinct_count("animal"), 1)
check("dwell is elapsed time", round(b.get(7).dwell, 2), 4.9)
check("frame count is kept too", b.get(7).frames, 50)

print("\nA flickering detection does not mint new objects")
# This is the people_seen bug, reproduced at the level above the detector:
# present, gone, present again, with the SAME tracker id.
b2 = tracking.TrackBook()
t = 0.0
for present in (1, 1, 0, 0, 1, 1, 0, 1):
    t += 0.1
    if present:
        b2.update([tl(3, cls="person")], now=t)
    else:
        b2.update([], now=t)
check("still one person", b2.distinct_count("person"), 1)
check("not one per rising edge (would be 3)", b2.distinct_count("person") != 3)

print("\nDistinct objects are counted separately")
b3 = tracking.TrackBook()
b3.update([tl(1, cls="animal"), tl(2, cls="animal"), tl(3, cls="person")], now=1.0)
b3.update([tl(1, cls="animal"), tl(3, cls="person")], now=1.1)
check("two animals", b3.distinct_count("animal"), 2)
check("one person", b3.distinct_count("person"), 1)
check("three in total", b3.distinct_count(), 3)
check("counts() agrees", b3.counts(), {"animal": 2, "person": 1})

print("\nClass is voted, not last-wins")
b4 = tracking.TrackBook()
# Mostly animal, with one confident stray "person" at the end.
for i in range(6):
    b4.update([tl(9, cls="animal", conf=0.6)], now=i * 0.1)
b4.update([tl(9, cls="person", conf=0.9)], now=0.7)
check("voted label is animal (3.6 vs 0.9)", b4.get(9).label, "animal")
check("peak confidence is remembered", b4.get(9).peak_conf, 0.9)
# ...but a genuine sustained reclassification does win.
for i in range(10):
    b4.update([tl(9, cls="person", conf=0.9)], now=1.0 + i * 0.1)
check("sustained evidence flips the vote", b4.get(9).label, "person")

print("\nDisplacement is metric, from stereo X/Z")
b5 = tracking.TrackBook()
for i in range(5):
    b5.update([tl(4, xyz=(float(i), 0.0, 10.0))], now=i * 0.1)
check("moved 4 m across", round(b5.get(4).displacement_m(), 2), 4.0)
check("path length agrees for a straight line", round(b5.get(4).path_m(), 2), 4.0)
# A stationary subject: the SAR gate's core requirement.
b6 = tracking.TrackBook()
for i in range(20):
    b6.update([tl(5, xyz=(0.01, 0.0, 12.0))], now=i * 0.1)
check("stationary reads ~0 m displacement", b6.get(5).displacement_m() < 0.05)
# Pacing back and forth: displacement small, path large. The distinction the
# SAR gate needs, so someone shifting on the spot is not called motionless.
b7 = tracking.TrackBook()
for i in range(10):
    b7.update([tl(6, xyz=(float(i % 2), 0.0, 10.0))], now=i * 0.1)
check("pacing: displacement stays small", b7.get(6).displacement_m() < 1.01)
check("pacing: path length is large", b7.get(6).path_m() >= 8.0)
check("missing xyz does not crash",
      tracking.TrackBook().update([tl(1, xyz=None)], now=1.0)[0].displacement_m(), 0.0)

print("\nOne evidence frame per track")
b8 = tracking.TrackBook()
touched = b8.update([tl(1), tl(2)], now=1.0)
new = b8.new_tracks(touched)
check("two new tracks earn a frame", sorted(t.id for t in new), [1, 2])
b8.mark_reported(new)
touched = b8.update([tl(1), tl(2)], now=1.1)
check("they do not earn another", b8.new_tracks(touched), [])
touched = b8.update([tl(1), tl(2), tl(3)], now=1.2)
check("a third arrival does", [t.id for t in b8.new_tracks(touched)], [3])

print("\nTracks expire, running totals do not")
b9 = tracking.TrackBook(forget_after=1.0)
b9.update([tl(1, cls="animal")], now=0.0)
check("present", len(b9), 1)
b9.update([], now=5.0)
check("forgotten after the window", len(b9), 0)
check("but still counted for the sortie", b9.distinct_count("animal"), 1)
b9.update([tl(1, cls="animal")], now=6.0)
check("the same id returning is not a second animal",
      b9.distinct_count("animal"), 1)

print("\nActive list is sorted by dwell, longest first")
b10 = tracking.TrackBook()
b10.update([tl(1)], now=0.0)
b10.update([tl(1), tl(2)], now=5.0)
b10.update([tl(1), tl(2)], now=6.0)
check("longest-standing first", [t.id for t in b10.active()], [1, 2])
b10.update([tl(1, status="LOST"), tl(2)], now=6.1)
check("LOST is still active (predicted, not gone)",
      [t.id for t in b10.active()], [1, 2])
b10.update([tl(1, status="REMOVED"), tl(2)], now=6.2)
check("REMOVED drops out", [t.id for t in b10.active()], [2])

print("\nEdge cases")
check("an empty frame is harmless", tracking.TrackBook().update([], now=1.0), [])
check("unknown id returns None", tracking.TrackBook().get(99), None)
b11 = tracking.TrackBook()
check("a track with no class has no label",
      b11.update([{"id": 1, "status": "NEW"}], now=1.0)[0].label, None)
check("and does not earn an evidence frame",
      b11.new_tracks(b11.update([{"id": 1, "status": "NEW"}], now=1.1)), [])
check("history is bounded",
      len(tracking.TrackBook().update(
          [tl(1)] , now=1.0)[0].xyz.maxlen * [0]), tracking.HISTORY)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
