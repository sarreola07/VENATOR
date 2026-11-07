#!/usr/bin/env python3
"""Finding the person in the yellow vest, and ignoring everyone else.

The behaviour that matters, and why:

  * a decoy is never targeted, whatever else happens in the frame. Locking onto
    the wrong person is the mistake this whole module exists to prevent;
  * a yellow object that is not a person is never a candidate, because a person
    has to be detected first;
  * one frame proves nothing: a colour that flickers must not get through the
    vote, and a lock must take about a second to earn;
  * a lock stays on one track. A second yellow vest is reported, not switched
    to, and someone who disappears has to earn the vote again;
  * ignored is for targeting, never for safety: closest_m counts every person;
  * no depth is an absence of a reading, not a person at 0 m.

Stdlib only, no camera: pixels are plain lists and detections are plain dicts,
so this is the same logic the aircraft runs.
"""
import argparse
import json
import os
import random
import socket
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "drone" / "wildlife"))

import ports  # noqa: E402
import vest   # noqa: E402

PASS = FAIL = 0


def check(label, got, want=True):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"    {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"   got {got!r}"))


YELLOW = (225, 235, 30)
RED = (205, 35, 40)
BLUE = (30, 70, 190)
GREY = (120, 120, 125)
SKIN = (205, 160, 135)
JEANS = (70, 90, 130)
WHITE = (240, 240, 240)
BLACK = (15, 15, 18)


def chest(colour, share=0.8, other=GREY, n=100):
    """n pixels, `share` of them in `colour`."""
    k = int(n * share)
    return [colour] * k + [other] * (n - k)


def person(tid, z=4.0, st="TRACKED", x=0.0, len_m=1.7, cls="person"):
    return {"id": tid, "c": cls, "p": 0.8, "st": st, "b": [0.2, 0.1, 0.4, 0.9],
            "xyz": [x, 0.0, z], "len_m": len_m}


def run_frames(search, frames, wearing, start=0.0, dt=0.1):
    """Feed `frames` frames. `wearing` maps track id -> chest pixels.

    Each person is rebuilt per frame, as gui_server.py does. Returns the last
    report and the last frame's detection dicts by id.
    """
    report, by_id = None, {}
    for i in range(frames):
        dets = [wearing[t]["det"]() for t in wearing]
        by_id = {d["id"]: d for d in dets}
        cur = {t: wearing[t]["px"] for t in wearing}

        def sample(box, _dets=dets, _cur=cur):
            return _cur[next(d["id"] for d in _dets if d["b"] is box)]

        report = search.process(dets, sample, start + i * dt)
    return report, by_id


def scene(**people):
    """scene(a=(id, pixels)) -> the structure run_frames takes."""
    return {tid: {"det": (lambda t=tid, kw=kw: person(t, **kw)), "px": px}
            for tid, px, kw in ((p[0], p[1], p[2] if len(p) > 2 else {})
                                for p in people.values())}


print("\nOne chest: colour shares")
R = vest.DEFAULT_RANGES
check("a yellow vest reads yellow", vest.pick(vest.shares(chest(YELLOW), R)), "yellow")
check("a red vest reads red", vest.pick(vest.shares(chest(RED), R)), "red")
check("a blue vest reads blue", vest.pick(vest.shares(chest(BLUE), R)), "blue")
for name, c in (("grey", GREY), ("white", WHITE), ("black", BLACK)):
    check(f"a {name} shirt reads as no vest", vest.pick(vest.shares(chest(c), R)), None)
check("bare skin is not a red vest", vest.pick(vest.shares(chest(SKIN), R)), None)
check("skin under warm light is not a red vest",
      vest.pick(vest.shares(chest((220, 140, 110)), R)), None)
check("an orange safety vest is not a red vest",
      vest.pick(vest.shares(chest((235, 110, 20)), R)), None)
check("a darker red vest in dim light still reads red",
      vest.pick(vest.shares(chest((130, 25, 30)), R)), "red")
check("jeans are not a blue vest (too grey)",
      vest.pick(vest.shares(chest(JEANS), R)), None)
check("a sliver of yellow is not enough",
      vest.pick(vest.shares(chest(YELLOW, share=0.15), R)), None)
check("reflective strips over half the vest still read yellow",
      vest.pick(vest.shares(chest(YELLOW, share=0.45, other=WHITE), R)), "yellow")
half = [YELLOW] * 50 + [BLUE] * 50
check("half yellow, half blue is not a clear answer", vest.pick(vest.shares(half, R)), None)
check("no pixels is no answer", vest.pick(vest.shares([], R)), None)
check("hue wraps through zero: 350", vest.in_hue(350, 345, 15))
check("hue wraps through zero: 5", vest.in_hue(5, 345, 15))
check("hue wraps through zero: 180 is out", vest.in_hue(180, 345, 15), False)

print("\nThe target: a yellow construction vest")
check("the search looks for yellow unless told otherwise", vest.DEFAULT_TARGET, "yellow")
# Hi-vis "yellow" is ANSI/ISEA 107 fluorescent yellow-green. These are the corners
# of its colour limits and their centre, converted from CIE xyY to sRGB, in full
# light and in shade: hue 55 to 84 degrees, saturation 0.55 or more. A real vest
# is broken up by silver reflective tape, so each is 60% fabric and 40% tape.
TAPE = (200, 200, 205)
HIVIS = {"centre": (211, 238, 0), "yellow corner": (246, 230, 0),
         "pale yellow corner": (239, 228, 107), "green corner": (167, 249, 0),
         "pale green corner": (185, 243, 96), "centre in shade": (150, 170, 0),
         "green corner in shade": (118, 177, 0), "pale green corner in shade": (131, 173, 66)}
for name, c in HIVIS.items():
    check(f"a construction vest with its tape reads yellow: {name}",
          vest.pick(vest.shares(chest(c, share=0.6, other=TAPE), R)), "yellow")
open_vest = [HIVIS["centre"]] * 40 + [TAPE] * 25 + [(45, 45, 50)] * 35
check("worn open over a dark shirt, it still reads yellow",
      vest.pick(vest.shares(open_vest, R)), "yellow")
check("an orange hi-vis vest is not taken for the yellow one",
      vest.pick(vest.shares(chest((255, 110, 0), share=0.6, other=TAPE), R)), None)
check("nor is a khaki work shirt", vest.pick(vest.shares(chest((195, 176, 145)), R)), None)

print("\nThe chest box stays off the edges and above the waist")
x1, y1, x2, y2 = vest.chest_box([0.0, 0.0, 1.0, 0.9])
check("it starts below the head", round(y1, 3), 0.18)
check("it stops above the waist", round(y2, 3), 0.495)
check("it keeps off both arms", (x1, x2), (0.25, 0.75))
x1, y1, x2, y2 = vest.chest_box([0.1, 0.0, 0.9, 1.0])
check("with the legs cut off it moves down, off the face", (y1, y2), (0.45, 0.85))
x1, y1, x2, y2 = vest.chest_box([0.40, 0.03, 0.60, 1.0])
check("someone whole with their feet at the frame's edge is not cut off",
      (round(y1, 3), round(y2, 3)), (0.224, 0.564))

print("\nThe vote: a second of agreement, not one frame")
v = vest.ColourVote()
for i in range(7):
    v.update("yellow")
check("7 of 10 is not confirmed", v.colour, None)
v.update("yellow")
check("8 of 10 is confirmed", v.colour, "yellow")
v = vest.ColourVote()
for i in range(40):
    v.update("yellow" if i % 2 else None)
check("a colour flickering every other frame is never confirmed", v.colour, None)
v = vest.ColourVote()
for i in range(10):
    v.update("yellow")
for i in range(5):
    v.update(None)
check("a brief blockage does not drop a confirmed vest", v.colour, "yellow")
for i in range(5):
    v.update(None)
check("covering it for a second does", v.colour, None)
v = vest.ColourVote()
for i in range(10):
    v.update("yellow")
v.update("blue")
v.update("blue")
check("two readings of another colour are not enough to drop it", v.colour, "yellow")
v.update("blue")
check("three in a row drop it at once", v.colour, None)
v = vest.ColourVote()
for i in range(10):
    v.update("yellow")
v.update("blue")
v.update(None)
v.update("blue")
v.update("blue")
check("a gap in those readings keeps it, since it could be someone walking past",
      v.colour, "yellow")

print("\nFinding the target among decoys")
s = vest.VestSearch("yellow")
people = scene(y=(1, chest(YELLOW)), r=(2, chest(RED)), b=(3, chest(BLUE)))
report, dets = run_frames(s, 3, people)
check("no lock after three frames", report["state"] != "found")
check("the state says it is still looking at someone", report["state"], "checking")
check("the yellow person is being checked", dets[1]["role"], "checking")
check("the red decoy is ignored", dets[2]["role"], "ignored")
report, dets = run_frames(s, 9, people, start=1.0)
check("yellow is found after about a second", report["state"], "found")
check("the report names the right track", report["id"], 1)
check("and carries its position for the flight code", (report["x"], report["z"]), (0.0, 4.0))
check("yellow is the target", dets[1]["role"], "target")
check("red stays ignored", dets[2]["role"], "ignored")
check("blue stays ignored", dets[3]["role"], "ignored")
check("two people counted as ignored", report["ignored"], 2)
check("one match", report["matches"], 1)

print("\nThe numbers behind the confidence chart")
s = vest.VestSearch("yellow")
people = scene(y=(1, chest(YELLOW, share=0.8)), r=(2, chest(RED)))
report, dets = run_frames(s, 3, people)
check("match is the share of the chest in the target colour", dets[1]["match"], 0.8)
check("a decoy's match stays at zero", dets[2]["match"], 0.0)
check("votes count toward the target", dets[1]["votes"], 3)
check("a decoy has no votes", dets[2]["votes"], 0)
check("the report says where the match line is", report["min_share"], vest.MIN_SHARE)
check("and how many votes a lock needs", report["vote_need"], vest.VOTE_CONFIRM)
blank = vest.VestSearch()
report, dets = run_frames(blank, 2, people)
check("with no target nobody has a match", dets[1]["match"], 0.0)
check("or any votes", dets[1]["votes"], 0)

s = vest.VestSearch("yellow")
people = scene(r=(2, chest(RED)), b=(3, chest(BLUE)), g=(4, chest(GREY)))
report, dets = run_frames(s, 40, people)
check("with only decoys in view it never locks", report["state"], "searching")
check("nobody is the target", any(d["role"] == "target" for d in dets.values()), False)

s = vest.VestSearch("blue")
people = scene(y=(1, chest(YELLOW)), b=(3, chest(BLUE)))
report, dets = run_frames(s, 12, people)
check("the colour is not hard-coded: searching blue finds blue", report["id"], 3)
check("and then yellow is the decoy", dets[1]["role"], "ignored")

print("\nOnly people can be candidates")
s = vest.VestSearch("yellow")
report = None
for i in range(30):
    bin_ = person(9, cls="vehicle")
    report = s.process([bin_], lambda box: chest(YELLOW), i * 0.1)
check("a yellow object that is not a person never locks", report["state"], "searching")
check("and it gets no role", "role" in bin_, False)
check("it is not counted as a person", report["people"], 0)

print("\nA person-shaped answer: range and size gates")
s = vest.VestSearch("yellow")
report, dets = run_frames(s, 20, scene(y=(1, chest(YELLOW), {"z": 12.0})))
check("yellow beyond 8 m is not a candidate", report["state"] != "found")
s = vest.VestSearch("yellow")
report, dets = run_frames(s, 20, scene(y=(1, chest(YELLOW), {"len_m": 0.4})))
check("something turkey-sized is not a candidate", report["state"] != "found")
s = vest.VestSearch("yellow")
report, dets = run_frames(s, 20, scene(y=(1, chest(YELLOW), {"z": 0.0})))
check("no depth reading is not a candidate", report["state"] != "found")

print("\nThe lock: never switches, reports a second match")
s = vest.VestSearch("yellow")
two = scene(a=(1, chest(YELLOW), {"z": 3.0}), b=(2, chest(YELLOW), {"z": 5.0}))
report, dets = run_frames(s, 12, two)
check("two yellow vests lock onto one person", report["id"], 1)
check("the other is a match, not the target", dets[2]["role"], "match")
check("and the report says two matched", report["matches"], 2)
report, dets = run_frames(s, 30, scene(a=(1, chest(YELLOW), {"z": 6.0}),
                                       b=(2, chest(YELLOW), {"z": 2.0})), start=2.0)
check("it stays locked when the other walks closer", report["id"], 1)
check("found once, not once per frame", report["found"], 1)

print("\nLosing the target")
s = vest.VestSearch("yellow")
report, dets = run_frames(s, 12, scene(y=(1, chest(YELLOW)), r=(2, chest(RED))))
check("found first", report["state"], "found")
check("found_now fired on the frame it locked, not after",
      "found_now" in report, False)
report, dets = run_frames(s, 1, scene(y=(1, chest(YELLOW), {"st": "LOST"}),
                                      r=(2, chest(RED))), start=1.5)
check("a missed frame does not flip the state", report["state"], "found")
check("but it is marked not visible at once", report["visible"], False)
check("and no stale coordinates reach the flight code", "x" in report, False)
report, dets = run_frames(s, 1, scene(y=(1, chest(YELLOW), {"st": "LOST"}),
                                      r=(2, chest(RED))), start=2.2)
check("past a second it is lost", report["state"], "lost")
report, dets = run_frames(s, 40, scene(r=(2, chest(RED))), start=2.3)
check("gone for over 2 s releases the lock", report["state"], "searching")
check("it does not move on to the red decoy", dets[2]["role"], "ignored")
report, dets = run_frames(s, 3, scene(y=(5, chest(YELLOW))), start=7.0)
check("someone reappearing with a new id is not found at once",
      report["state"] != "found")
report, dets = run_frames(s, 9, scene(y=(5, chest(YELLOW))), start=7.3)
check("they earn the vote again", (report["state"], report["id"]), ("found", 5))
check("but back within 30 s it is the same find, not a new one", report["found"], 1)
check("so there is no second alert", "found_now" in report, False)

print("\nRepeat finds: measured on a webcam, four alerts in 36 s for one person")
s = vest.VestSearch("yellow")
fired, clock = [], 0.0
# Sits still while the detector keeps dropping them: a new id every few seconds.
for tid in range(1, 9):
    for _ in range(14):
        clock += 0.1
        r = s.process([person(tid)], lambda b: chest(YELLOW), clock)
        fired += ["alert"] if r.get("found_now") else []
    clock += 3.0
check("one person dropped and regained eight times is one find", len(fired), 1)
check("and the count agrees", r["found"], 1)
clock += vest.SAME_FIND_S + 1.0
for _ in range(14):
    clock += 0.1
    r = s.process([person(99)], lambda b: chest(YELLOW), clock)
    fired += ["alert"] if r.get("found_now") else []
check("gone for longer than that, finding them again is a new find", len(fired), 2)
check("and is counted", r["found"], 2)

print("\nA dropout hands someone a new id")
s = vest.VestSearch("yellow")
report, dets = run_frames(s, 12, scene(y=(1, chest(YELLOW))))
check("locked before the dropout", (report["state"], report["id"]), ("found", 1))
report, dets = run_frames(s, 1, scene(y=(2, chest(YELLOW))), start=2.0)
check("the same place and colour keeps the lock, with no re-vote", report["id"], 2)
check("and stays found throughout", report["state"], "found")
check("with no second alert", "found_now" in report, False)
s = vest.VestSearch("yellow")
run_frames(s, 12, scene(y=(1, chest(YELLOW))))
report, dets = run_frames(s, 1, scene(b=(2, chest(BLUE))), start=2.0)
check("a decoy stepping into that spot does not inherit the lock", dets[2]["role"] != "target", True)
check("and has no yellow votes from it", dets[2]["votes"], 0)
s = vest.VestSearch("yellow")
run_frames(s, 12, scene(y=(1, chest(YELLOW))))
elsewhere = {"det": lambda: dict(person(2), b=[0.7, 0.1, 0.9, 0.9]), "px": chest(YELLOW)}
report, dets = run_frames(s, 1, {2: elsewhere}, start=2.0)
check("someone in the same colour somewhere else has to earn it", report["state"], "found")
check("the lock did not jump to them", report["visible"], False)
s = vest.VestSearch("yellow")
run_frames(s, 12, scene(y=(1, chest(YELLOW))))
report, dets = run_frames(s, 1, scene(y=(2, chest(YELLOW))), start=3.5)
check("too long after, it is not a continuation", dets[2]["votes"], 1)
s = vest.VestSearch("yellow")
run_frames(s, 12, scene(y=(1, chest(YELLOW))))
report, dets = run_frames(s, 1, scene(a=(2, chest(YELLOW)), b=(3, chest(YELLOW))), start=2.0)
check("two new ids can't both claim one history",
      sorted(dets[i]["votes"] for i in (2, 3)), [1, 10])
s = vest.VestSearch("yellow")
gone_then_seen = [dict(person(1), st="LOST"), person(2)]
run_frames(s, 12, scene(y=(1, chest(YELLOW))))
report = s.process(gone_then_seen, lambda b: chest(YELLOW), 2.0)
check("the old id's fading box in the same frame does not break anything", report["id"], 2)
check("and that box is not counted as a second person", report["ignored"], 0)

print("\nIds swapped: the tracker puts the target's id on a decoy")
s = vest.VestSearch("yellow")
run_frames(s, 12, scene(y=(1, chest(YELLOW)), b=(2, chest(BLUE))))
wrong_frames = 0
for i in range(10):
    dets = [person(1), person(2)]
    px = {id(dets[0]["b"]): chest(BLUE), id(dets[1]["b"]): chest(YELLOW)}
    r = s.process(dets, lambda b: px[id(b)], 2.0 + i * 0.1)
    wrong_frames += dets[0].get("role") == "target"
check("the wrong person is the target for under 0.3 s", wrong_frames <= 2, True)
check("the lock lets go of them", dets[0]["role"], "ignored")

print("\nStress: random dropouts, new ids, moves and noise, across many runs")


def stress_run(seed, target="red", seconds=120.0, dt=0.1):
    """Three people, one in the target colour, with a badly behaved detector.

    Returns (frames a decoy was the target, frames someone was target, new finds,
    frames the true target was in view). Everything is random but seeded, so a
    failure can be replayed.
    """
    rng = random.Random(seed)
    colours = {"red": RED, "yellow": YELLOW, "blue": BLUE}
    cast = [dict(name=c, colour=colours[c], x=rng.uniform(0.05, 0.75), gone=0.0,
                 id=None, missing=None) for c in colours]
    owner, next_id = {}, 1
    s = vest.VestSearch(target)
    wrong = right = finds = in_view = 0
    clock = 0.0
    while clock < seconds:
        clock += dt
        dets, chests = [], {}
        for p in cast:
            p["x"] = min(0.78, max(0.02, p["x"] + rng.uniform(-0.01, 0.01)))
            box = [p["x"], 0.1, p["x"] + 0.18, 0.9]
            if p["gone"] > 0:
                p["gone"] -= dt
            elif rng.random() < 0.02:                 # the detector loses them
                p["gone"] = rng.uniform(0.1, 3.0)
            if p["gone"] > 0:
                if p["id"] is not None:
                    p["missing"] = (p["missing"] or 0.0) + dt
                    if p["missing"] > 1.0:
                        dets.append(dict(person(p["id"]), st="REMOVED", b=box))
                        p["id"] = None
                    else:
                        dets.append(dict(person(p["id"]), st="LOST", b=box))
                continue
            p["missing"] = None
            status = "TRACKED"
            if p["id"] is None:
                p["id"], next_id, status = next_id, next_id + 1, "NEW"
                owner[p["id"]] = p["name"]
            share = 0.0 if rng.random() < 0.15 else rng.uniform(0.35, 0.9)   # blur, an arm
            d = dict(person(p["id"], st=status), b=box)
            dets.append(d)
            chests[id(box)] = chest(p["colour"], share=share, other=GREY)
            in_view += p["name"] == target
        r = s.process(dets, lambda b: chests[id(b)], clock)
        finds += bool(r.get("found_now"))
        for d in dets:
            if d.get("role") == "target":
                wrong += owner[d["id"]] != target
                right += owner[d["id"]] == target and d["st"] in vest.MEASURED
        assert not ("x" in r and not r.get("visible")), "coordinates while not visible"
        assert r["state"] in ("searching", "checking", "found", "lost"), r["state"]
    return wrong, right, finds, in_view


wrong = right = finds = in_view = 0
RUNS = 40
for seed in range(RUNS):
    w, g, f, v = stress_run(seed)
    wrong, right, finds, in_view = wrong + w, right + g, finds + f, in_view + v
check(f"across {RUNS} two-minute runs a decoy was never the target", wrong, 0)
check("the real target was found in every run", finds >= RUNS)
check("and held for most of the time they were in view "
      f"({100 * right // max(in_view, 1)}%)", right > 0.7 * in_view)
check(f"without alert spam ({finds} finds in {RUNS} runs)", finds <= RUNS * 4)

print("\nThe ignored count is people in view now, not ids ever seen")
s = vest.VestSearch("yellow")
clock = 0.0
for tid in range(1, 17):      # one person, dropped and given a new id sixteen times
    for _ in range(8):
        clock += 0.1
        r = s.process([person(tid)], lambda b: chest(RED), clock)
check("one person with many ids reads as one ignored", r["ignored"], 1)
r = s.process([], None, clock + 0.1)
check("and nobody in view reads as none", r["ignored"], 0)

print("\nCovering the vest")
s = vest.VestSearch("yellow")
report, dets = run_frames(s, 12, scene(y=(1, chest(YELLOW))))
check("found", report["state"], "found")
report, dets = run_frames(s, 12, scene(y=(1, chest(GREY))), start=2.0)
check("a covered vest loses the lock", report["state"], "searching")
check("and that person becomes ignored", dets[1]["role"], "ignored")

print("\nThe target's depth drops out")
s = vest.VestSearch("yellow")
report, dets = run_frames(s, 12, scene(y=(1, chest(YELLOW))))
report, dets = run_frames(s, 1, scene(y=(1, chest(YELLOW), {"z": 0.0})), start=2.0)
check("it is still the target", report["state"], "found")
check("but there is no position to steer by", "x" in report or "z" in report, False)

print("\nSomeone leaving the frame")
s = vest.VestSearch("yellow")
gone = person(7, st="REMOVED")
report = s.process([gone], lambda box: chest(RED), 0.0)
check("their last box is grey, not the detector's colour", gone["role"], "ignored")
check("and they no longer count as nearby", report["closest_m"], None)
check("and have no reading to graph or snapshot", "match" in gone, False)

print("\nA camera with no depth")
s = vest.VestSearch("yellow", use_depth=False)
flat = {"y": {"det": lambda: dict(person(1), xyz=None, len_m=None), "px": chest(YELLOW)},
        "r": {"det": lambda: dict(person(2), xyz=None, len_m=None), "px": chest(RED)}}
wearing = {1: flat["y"], 2: flat["r"]}
report, dets = run_frames(s, 12, wearing)
check("the vest is still found", (report["state"], report["id"]), ("found", 1))
check("the decoy is still ignored", dets[2]["role"], "ignored")
check("no position is invented", "z" in report or "x" in report, False)
check("and nobody is reported as close", report["closest_m"], None)
alert = vest.found_alert(dict(report, target="yellow", found=1), 1000.0)
check("the alert has no made-up range", "rel" in alert, False)
s = vest.VestSearch("yellow")
report, dets = run_frames(s, 12, wearing)
check("with depth on, the same scene can't lock with no depth reading", report["state"] != "found")
s = vest.VestSearch("yellow", use_depth=False)
small = {"det": lambda: dict(person(1), xyz=None, len_m=None, b=[0.1, 0.1, 0.2, 0.3]), "px": chest(YELLOW)}
large = {"det": lambda: dict(person(2), xyz=None, len_m=None, b=[0.4, 0.1, 0.8, 0.9]), "px": chest(YELLOW)}
report, dets = run_frames(s, 12, {1: small, 2: large})
check("two matches lock onto the biggest, so the nearest", report["id"], 2)

print("\nThe webcam's stand-in tracker")
import webcam_search  # noqa: E402
near = [0.1, 0.1, 0.3, 0.9]
moved = [0.12, 0.1, 0.32, 0.9]
far = [0.6, 0.1, 0.8, 0.9]
t = webcam_search.BoxTracker(keep_s=1.0)
out = t.update([(near, 0.9)], 0.0)
check("someone new gets an id and NEW", (out[0]["id"], out[0]["status"]), (1, "NEW"))
out = t.update([(moved, 0.8)], 0.1)
check("the same person keeps their id", (out[0]["id"], out[0]["status"]), (1, "TRACKED"))
check("and their latest box", out[0]["box"], moved)
out = t.update([(moved, 0.8), (far, 0.7)], 0.2)
check("a second person gets a second id", [o["id"] for o in out], [1, 2])
out = t.update([(far, 0.7)], 0.3)
check("someone unseen is LOST, not gone", {o["id"]: o["status"] for o in out}, {1: "LOST", 2: "TRACKED"})
out = t.update([(far, 0.7)], 1.3)
check("after a second they are REMOVED once", {o["id"]: o["status"] for o in out}, {1: "REMOVED", 2: "TRACKED"})
out = t.update([(far, 0.7)], 1.4)
check("and then they are gone", [o["id"] for o in out], [2])
out = t.update([(far, 0.7), (near, 0.9)], 1.5)
check("an id is never reused", sorted(o["id"] for o in out), [2, 3])
check("no overlap means no match", vest.iou(near, far), 0.0)
check("a box matches itself exactly", round(vest.iou(near, near), 6), 1.0)
d = webcam_search.detection(out[0])
check("a detection claims no depth", (d["xyz"], d["len_m"]), (None, None))
check("the search accepts one", vest.VestSearch("yellow", use_depth=False).process(
    [d], lambda b: chest(YELLOW), 0.0)["people"], 1)

print("\nA colour frame missing must not change anyone's vote")
s = vest.VestSearch("yellow")
run_frames(s, 12, scene(y=(1, chest(YELLOW))))
report = None
for i in range(30):
    report = s.process([person(1)], None, 2.0 + i * 0.1)
check("no frames keeps the lock rather than casting empty votes", report["state"], "found")

print("\nIgnored for targeting, never for safety")
s = vest.VestSearch("yellow")
report, dets = run_frames(s, 12, scene(y=(1, chest(YELLOW), {"z": 5.0}),
                                       r=(2, chest(RED), {"z": 1.5})))
check("an ignored person still sets closest_m", report["closest_m"], 1.5)
check("while the target stays the target", report["id"], 1)
s = vest.VestSearch(None)
report, dets = run_frames(s, 3, scene(r=(2, chest(RED), {"z": 1.5})))
check("closest_m works with no search running", report["closest_m"], 1.5)
s = vest.VestSearch("yellow")
report, dets = run_frames(s, 3, scene(y=(1, chest(GREY), {"z": 0.0})))
check("a 0 m depth reading is not someone on the lens", report["closest_m"], None)

print("\nTargets")
s = vest.VestSearch()
check("no target to begin with", s.target, None)
report, dets = run_frames(s, 12, scene(y=(1, chest(YELLOW))))
check("no target means idle", report["state"], "idle")
check("people still get a vest label", dets[1]["vest"], "yellow")
check("and no role", "role" in dets[1], False)
check("an unknown colour is refused", s.set_target("green"), False)
check("and changes nothing", s.target, None)
check("a known one is accepted", s.set_target("yellow"), True)
report, dets = run_frames(s, 1, scene(y=(1, chest(YELLOW))), start=2.0)
check("a vest voted on earlier locks without waiting again", report["state"], "found")
s.set_target("yellow")
report, dets = run_frames(s, 1, scene(y=(1, chest(YELLOW))), start=2.1)
check("repeating the target does not restart the search", report["found"], 1)
s.set_target("blue")
report, dets = run_frames(s, 1, scene(y=(1, chest(YELLOW))), start=2.2)
check("changing the target starts a new search", report["state"], "searching")

print("\nThe FOUND alert")
s = vest.VestSearch("yellow")
fired = []
for i in range(30):
    r = s.process([person(1, z=4.0, x=4.0)], lambda b: chest(YELLOW), i * 0.1)
    if r.get("found_now"):
        fired.append(r)
check("found_now fires exactly once", len(fired), 1)
a = vest.found_alert(fired[0], 1000.0)
check("the alert names the colour", a["kind"], "missing_person_found_yellow_vest")
check("range comes from depth", a["rel"]["rng"], 4.0)
check("bearing is measured off the camera axis", a["rel"]["brg"], 45)

print("\nCalibration")
fit = vest.fit_range(chest(YELLOW, share=0.9, other=WHITE))
check("a vest fits a range", fit is not None)
check("that range contains the vest", vest.pick(vest.shares(
    chest(YELLOW), {"yellow": fit, "blue": R["blue"]})), "yellow")
check("and rejects another vest", vest.pick(vest.shares(
    chest(BLUE), {"yellow": fit})), None)
fit_red = vest.fit_range(chest((205, 40, 25)) + chest((205, 25, 45)))
check("red straddling zero degrees fits as a wrapping range",
      fit_red["hue"][0] > fit_red["hue"][1], True)
check("a grey wall is not a colour", vest.fit_range(chest(GREY)), None)
check("a half yellow, half blue target is not one colour",
      vest.fit_range(chest(YELLOW, share=0.5, other=BLUE)), None)
check("too few colourful pixels is refused",
      vest.fit_range(chest(YELLOW, share=0.1)), None)
fits = {"yellow": vest.fit_range(chest(YELLOW)), "blue": vest.fit_range(chest(BLUE))}
check("distinct vests do not overlap", vest.overlaps(fits), [])
orange = vest.fit_range(chest((230, 130, 20)))
near = vest.fit_range(chest((235, 150, 25)))
check("two vests too close in colour are flagged",
      vest.overlaps({"red": orange, "yellow": near}), [("red", "yellow")])

with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "sub" / "vest.json"
    ranges, wb, source = vest.load_calibration(path)
    check("no file means defaults", ranges, vest.DEFAULT_RANGES)
    check("and says so", source, "built-in defaults")
    vest.save_calibration(vest.DEFAULT_RANGES, 4200, path)
    ranges, wb, source = vest.load_calibration(path)
    check("a saved file round-trips", (ranges, wb), (vest.DEFAULT_RANGES, 4200))
    check("and names where it came from", str(path) in source)
    path.write_text("{not json")
    check("a damaged file falls back to defaults",
          vest.load_calibration(path)[0], vest.DEFAULT_RANGES)
    path.write_text(json.dumps({"ranges": {"yellow": {"hue": "x"}}, "wb_k": 99}))
    ranges, wb, source = vest.load_calibration(path)
    check("one bad colour falls back alone", ranges["yellow"], vest.DEFAULT_RANGES["yellow"])
    check("an impossible white balance is dropped", wb, None)
    check("and the fallback is named", "defaults for" in source)
    path.write_text(json.dumps({"ranges": {"yellow": {
        "hue": ["40", "80"], "sat": "0.45", "val": "0.35"}}}))
    ranges, wb, source = vest.load_calibration(path)
    check("numbers saved as text still work on real pixels",
          vest.pick(vest.shares(chest(YELLOW), ranges)), "yellow")

print("\nThe target arrives over loopback, and bad packets are harmless")
check("the search ports are all distinct",
      len({ports.SEARCH_TARGET_UDP, ports.SEARCH_REPORT_UDP, ports.ALERTS_UDP,
           ports.CAMERA_COORDS_UDP}), 4)
rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx.bind(("127.0.0.1", 0))
report_port = rx.getsockname()[1]
probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
probe.bind(("127.0.0.1", 0))
target_port = probe.getsockname()[1]
probe.close()
link = vest.SearchLink(target_port, report_port, log=lambda m: None)
tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s = vest.VestSearch()
for packet in (b"garbage", b"{}", b'{"target": "green"}', b'{"target": "yellow"}', b"\xff\xfe"):
    tx.sendto(packet, ("127.0.0.1", target_port))
deadline = time.monotonic() + 2.0
while s.target is None and time.monotonic() < deadline:
    link.poll_target(s)
check("a valid target gets through the junk around it", s.target, "yellow")
tx.sendto(b'{"target": null}', ("127.0.0.1", target_port))
deadline = time.monotonic() + 2.0
while s.target is not None and time.monotonic() < deadline:
    link.poll_target(s)
check("null stops the search", s.target, None)
link.send({"state": "found", "z": 4.0})
rx.settimeout(2.0)
check("the report reaches the flight code as JSON",
      json.loads(rx.recvfrom(512)[0].decode())["state"], "found")
taken = vest.SearchLink(target_port, report_port, log=lambda m: None)
taken.poll_target(s)
check("a taken port leaves the search running, not crashed", s.target, None)

print("\nRecording a trial")
import trial_log  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    said = []
    trials = trial_log.TrialLog(Path(tmp) / "trials", log=said.append)
    check("nothing is recorded until it is started", trials.status(), None)
    trials.write({"target": "red", "state": "searching"}, [person(1)])
    check("and writing while stopped does nothing", trials.rows, 0)
    name = trials.start("4 m, Daylight! Sam in red")
    check("a recording is named by time and note",
          bool(trial_log.NAME.match(name)) and name.endswith("-4-m-daylight-sam-in-red.csv"))
    s = vest.VestSearch("red")
    dets = [dict(person(1), role="target", vest="red", match=0.8, votes=8),
            dict(person(2, z=0.0), role="ignored", vest="blue", match=0.0, votes=0),
            dict(person(3, cls="animal"))]
    trials.write({"target": "red", "state": "found", "id": 1, "z": 4.0, "conf": 0.8,
                  "found_now": True}, dets)
    check("one row per person, plus one for the find", trials.rows, 3)
    check("the page sees it recording", trials.status(), {"name": name, "rows": 3})
    check("stopping returns its name", trials.stop(), name)
    check("and stopping again is harmless", trials.stop(), None)
    import csv  # noqa: E402
    rows = list(csv.DictReader(open(Path(tmp) / "trials" / name)))
    check("the columns are the documented ones", list(rows[0]), list(trial_log.COLUMNS))
    check("the note is on every row", {r["note"] for r in rows}, {"4 m, Daylight! Sam in red"})
    check("an animal is not a row", [r["track"] for r in rows[:2]], ["1", "2"])
    check("a missing depth is blank, not 0", rows[1]["distance_m"], "")
    check("the find is its own row", (rows[2]["event"], rows[2]["track"]), ("found", "1"))
    check("it is listed", [t["name"] for t in trials.list()], [name])
    check("and can be found by name", trials.path(name) is not None)
    for bad in ("../" + name, "x.csv", name + ".bak", "", "/etc/passwd", "20261106-120000.CSV"):
        check(f"refuses {bad!r}", trials.path(bad), None)
    trials.start("")
    trials._file.close()           # a write that fails, like a full disk
    trials.write({"target": "red", "state": "found"}, [dict(person(1), role="target")])
    check("a failed write stops the recording", trials.recording, False)
    check("and says so", any("could not write" in m for m in said))
    blocked = trial_log.TrialLog(Path(tmp) / "trials" / name / "nested", log=said.append)
    check("a folder that can't be made refuses to start", blocked.start("x"), None)
    first = trials.start("retake")
    trials.stop()
    second = trials.start("retake")
    trials.stop()
    check("two recordings in one second with one note don't overwrite each other",
          first != second and all(trials.path(n) for n in (first, second)))
    check("and both can be listed", {first, second} <= {t["name"] for t in trials.list()})

print("\nA calibration that gets no picture gives up")
import gui_server  # noqa: E402
cal_cfg = {"search": vest.VestSearch("red")}
check("it starts", gui_server.start_calibration(cal_cfg, "red"), None)
for t in (0.0, 1.0, vest.CALIBRATION_TIMEOUT_S - 0.5):
    gui_server.search_step(gui_server.Hub(), cal_cfg, [], None, t)
check("it waits while frames may still come", cal_cfg["calibrating"] is not None)
gui_server.search_step(gui_server.Hub(), cal_cfg, [], None, vest.CALIBRATION_TIMEOUT_S + 0.5)
check("then gives up instead of reading forever", cal_cfg["calibrating"], None)

print("\nA camera started with --conf can't run the search")
conf_cfg = {"device_conf": 0.8}
check("turning it on is refused", gui_server.set_search(conf_cfg, "red"), False)
check("and nothing starts", conf_cfg.get("search"), None)
check("turning it off is still fine", gui_server.set_search(conf_cfg, None), True)

print("\nThe pixel step, with numpy when it is available")
try:
    import numpy as np
except ImportError:
    print("    skip  numpy is not installed here (CI is stdlib-only by design)")
else:
    frame = np.zeros((288, 512, 3), dtype=np.uint8)
    frame[:, :] = GREY
    box = [0.25, 0.1, 0.5, 0.9]
    x1, y1, x2, y2 = vest.chest_box(box)
    frame[int(y1 * 288):int(y2 * 288), int(x1 * 512):int(x2 * 512)] = YELLOW
    px = vest.chest_pixels(frame, box)
    check("the chest samples read the vest", vest.pick(vest.shares(px, R)), "yellow")
    check("samples are capped", len(px) <= vest.MAX_PIXELS * 1.5)
    check("samples are plain values", isinstance(px[0][0], int))
    check("an empty box gives no pixels", vest.chest_pixels(frame, [0.5, 0.5, 0.5, 0.5]), [])
    check("a box off the frame gives no pixels",
          vest.chest_pixels(frame, [1.2, 1.2, 1.4, 1.4]), [])

    # The whole path the camera service runs, from a planar frame as the
    # network passthrough delivers it.
    import gui_server  # noqa: E402

    class Frame:
        def __init__(self, rgb):
            self._planar = np.concatenate([rgb[:, :, 2], rgb[:, :, 1], rgb[:, :, 0]])
            self._h, self._w = rgb.shape[:2]

        def getFrame(self):
            return self._planar

        def getWidth(self):
            return self._w

        def getHeight(self):
            return self._h

    s = vest.VestSearch("yellow")
    step_cfg = {"search": s}
    report = None
    for i in range(12):
        det = person(1)
        det["b"] = box
        frames = gui_server.ColourFrames()
        frames.offer(Frame(frame), i * 0.1)
        report = gui_server.search_step(gui_server.Hub(), step_cfg, [det],
                                        frames.take(step_cfg, [det], i * 0.1), i * 0.1)
    check("a planar camera frame reaches a lock", report["state"], "found")
    check("the detection comes back labelled", (det["role"], det["vest"]), ("target", "yellow"))

    print("\nEach colour frame votes once")
    frames = gui_server.ColourFrames()
    one = Frame(frame)
    frames.offer(one, 1.0)
    check("no people means the frame is not even converted",
          frames.take(step_cfg, [], 1.0), None)
    check("but it is still there for the next batch that has someone",
          frames.take(step_cfg, [person(1)], 1.0) is not None)
    check("and the same frame is never read twice",
          frames.take(step_cfg, [person(1)], 1.05), None)
    frames.offer(one, 1.1)
    check("not even when the queue hands the same frame back",
          frames.take(step_cfg, [person(1)], 1.1), None)
    frames.offer(Frame(frame), 1.2)
    check("a stale frame is never read",
          frames.take(step_cfg, [person(1)], 1.2 + gui_server.FRAME_MAX_AGE_S + 0.01), None)
    s2 = vest.VestSearch("yellow")
    det = person(1)
    det["b"] = box
    stuck = gui_server.ColourFrames()
    stuck.offer(Frame(frame), 0.0)
    for i in range(10):     # ten batches of tracklets, one stalled colour frame
        gui_server.search_step(gui_server.Hub(), {"search": s2}, [det],
                               stuck.take({"search": s2}, [det], i * 0.04), i * 0.04)
    check("ten batches on one stalled frame are one vote, not ten",
          s2._tracks[1].vote.count("yellow"), 1)

    # The camera loop itself, on a fake camera. Everything above tests pieces;
    # this is what catches a mistake in how run() joins them, which otherwise
    # would only surface on the aircraft.
    def fake_camera_run(cfg, frames, save_dir, on_batch=None, result=None):
        """gui_server.run() with depthai replaced. Returns (hub, passthrough queue).
        on_batch(n, cfg) runs before the nth tracklet batch, like a page request.
        run()'s return value goes in result["value"]."""
        dai = mock.MagicMock()
        dai.NNArchive.return_value.getInputSize.return_value = (512, 288)
        nn, tracker = mock.MagicMock(), mock.MagicMock()
        nn.getClasses.return_value = ["animal", "person", "vehicle"]
        tq, fq = mock.MagicMock(), mock.MagicMock()
        tracker.out.createOutputQueue.return_value = tq
        nn.passthrough.createOutputQueue.return_value = fq
        nn.build.return_value = nn
        pipeline = dai.Pipeline.return_value.__enter__.return_value
        pipeline.create.side_effect = lambda node: {
            dai.node.SpatialDetectionNetwork: nn, dai.node.ObjectTracker: tracker
        }.get(node, mock.MagicMock())
        pipeline.isRunning.side_effect = [True] * frames + [False]

        def tracklet(tid):
            t = mock.MagicMock()
            t.id, t.label = tid, 1
            t.srcImgDetection.confidence = 0.9
            t.status.name = "TRACKED"
            t.spatialCoordinates.x = 500.0
            t.spatialCoordinates.y = 0.0
            t.spatialCoordinates.z = 3000.0     # 0.8 of the frame at 3 m: 1.86 m tall
            t.roi.isNormalized.return_value = True
            t.roi.x, t.roi.y, t.roi.width, t.roi.height = box[0], box[1], 0.25, 0.8
            return t

        batches = {"n": 0}

        def next_batch():
            batches["n"] += 1
            if on_batch is not None:
                on_batch(batches["n"], cfg)
            return mock.Mock(tracklets=[tracklet(1)])

        tq.tryGet.side_effect = next_batch
        # A new frame object each time, as a real queue gives: the search reads
        # each frame once, so one object handed back forever would vote once.
        fq.tryGet.side_effect = lambda: Frame(frame)
        hub = gui_server.Hub()
        hub.publish_frame("hi", b"\xff\xd8jpeg\xff\xd9")
        args = argparse.Namespace(model="m", shaves=None, conf=None, fps=10.0,
                                  preset="DEFAULT", min_dist=0.3, max_dist=35.0,
                                  save_dir=save_dir)
        with mock.patch.dict(sys.modules, {"depthai": dai}), \
                mock.patch.object(gui_server, "resolve_model", return_value="m"), \
                mock.patch.object(gui_server.time, "sleep"):
            value = gui_server.run(args, hub, cfg)
        if result is not None:
            result["value"] = value
        return hub, nn.passthrough.createOutputQueue

    def camera_cfg(**extra):
        return dict({"conf": None, "classes": [], "quality": "hi", "save": True,
                     "pm": "7W"}, **extra)

    # The size gate is only as good as this number. It used to scale height by
    # the frame's width, which measured a standing 1.7 m person as 3 m.
    size = gui_server.long_axis_m
    check("a standing 1.7 m person at 4 m measures about 1.7 m",
          abs(size(0.1, 0.55, 4.0) - 1.7) < 0.05)
    check("that fits the size gate",
          vest.MIN_LEN_M <= size(0.1, 0.55, 4.0) <= vest.MAX_LEN_M)
    check("someone lying down is measured along their width",
          abs(size(0.45, 0.1, 3.0) - 1.85) < 0.05)
    check("a turkey at 4 m is too small for the gate",
          size(0.05, 0.13, 4.0) < vest.MIN_LEN_M)
    check("no depth means no size", size(0.1, 0.5, 0.0), None)

    with tempfile.TemporaryDirectory() as tmp:
        cfg = camera_cfg(search=vest.VestSearch("yellow"))
        hub, frame_queue = fake_camera_run(cfg, 30, tmp)
        det_event = hub._dets
        check("the loop reaches a lock", det_event["search"]["state"], "found")
        check("phones get the role on the box", det_event["d"][0]["role"], "target")
        check("found_now stays out of what phones are sent",
              "found_now" in det_event["search"], False)
        alerts = hub.snapshot()["recent_alerts"]
        check("exactly one FOUND alert over 30 frames", len(alerts), 1)
        check("and it names the vest", alerts[0]["kind"], "missing_person_found_yellow_vest")
        saved = sorted(Path(tmp).glob("*.json"))
        check("one evidence photo, for the find only", len(saved), 1)
        check("and it records who the target was",
              json.loads(saved[0].read_text())["detections"][0]["role"], "target")

    with tempfile.TemporaryDirectory() as tmp:
        hub, frame_queue = fake_camera_run(camera_cfg(), 3, tmp)
        check("without --search no frames are pulled over USB",
              frame_queue.called, False)
        check("without --search phones get no search state", "search" in hub._dets, False)
        check("without --search no box gets a role", "role" in hub._dets["d"][0], False)
        check("without --search evidence is saved as before",
              len(list(Path(tmp).glob("*.json"))) >= 1)

    # Settings that hide people must not be able to hide them from a search,
    # which is also what reports how close anyone is to the aircraft.
    with tempfile.TemporaryDirectory() as tmp:
        hub, _ = fake_camera_run(camera_cfg(classes=["animal"], conf=0.99,
                                            search=vest.VestSearch("yellow")), 3, tmp)
        check("during a search the live filters can't hide a person",
              hub._dets["search"]["closest_m"], 3.0)
    with tempfile.TemporaryDirectory() as tmp:
        hub, _ = fake_camera_run(camera_cfg(classes=["animal"]), 3, tmp)
        check("without a search they still work as before", hub._dets["d"], [])

    class BrokenSearch(vest.VestSearch):
        def process(self, dets, sample, now):
            raise RuntimeError("broken")

    with tempfile.TemporaryDirectory() as tmp:
        hub, _ = fake_camera_run(camera_cfg(search=BrokenSearch("yellow")), 3, tmp)
        check("a fault in the search does not stop the video or the boxes",
              len(hub._dets["d"]), 1)

    print("\nThe operator turns the search on and off from the page")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VENATOR_VEST_FILE"] = str(Path(tmp) / "vest-colours.json")
        cfg = camera_cfg()
        result = {}
        hub, queue = fake_camera_run(
            cfg, 30, tmp, result=result,
            on_batch=lambda n, c: n == 3 and gui_server.set_search(c, "yellow"))
        check("turning it on stops the loop to rebuild the camera", result["value"], "rebuild")
        check("the first build pulled no colour frames", queue.called, False)
        check("phones were told the camera is restarting",
              hub.snapshot().get("camera"), "restarting")
        hub, queue = fake_camera_run(cfg, 30, tmp, result=result)
        check("the rebuilt camera pulls colour frames", queue.called)
        check("and the search finds the target", hub._dets["search"]["state"], "found")
        check("a finished run is not a rebuild", result["value"] != "rebuild")
        check("changing colour needs no rebuild",
              (gui_server.set_search(cfg, "blue"), cfg.get("rebuild")), (True, None))
        check("turning it off does", (gui_server.set_search(cfg, None), cfg.get("rebuild")),
              (True, True))
        hub, queue = fake_camera_run(cfg, 3, tmp, result=result)
        check("and then the colour frames stop", queue.called, False)
        check("a colour that isn't a vest is refused", gui_server.set_search(cfg, "green"), False)

    print("\nCalibrating a vest from the page")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["VENATOR_VEST_FILE"] = str(Path(tmp) / "vest-colours.json")
        cfg = {"search": vest.VestSearch("blue")}
        check("it needs the search on",
              gui_server.start_calibration({"search": None}, "blue") is not None)
        check("and a vest colour", gui_server.start_calibration(cfg, "green") is not None)
        middle = np.zeros((288, 512, 3), dtype=np.uint8)
        middle[:, :] = GREY
        middle[90:200, 170:345] = BLUE
        check("a calibration starts", gui_server.start_calibration(cfg, "blue"), None)
        hub = gui_server.Hub()
        for i in range(vest.CALIBRATION_FRAMES):
            gui_server.search_step(hub, cfg, [], middle, i * 0.1)
        check("it finishes after about a second of frames", cfg["calibrating"], None)
        check("the new range is used straight away", cfg["search"].ranges["blue"] != R["blue"])
        check("the defaults themselves are untouched", vest.DEFAULT_RANGES["blue"], R["blue"])
        saved, _, source = vest.load_calibration()
        check("and it is saved for the next start", saved["blue"], cfg["search"].ranges["blue"])
        check("a blue vest still reads blue", vest.pick(vest.shares(chest(BLUE), saved)), "blue")
        done = gui_server.finish_calibration(cfg, cfg["search"],
                                             {"colour": "red", "fit": vest.fit_range(chest(YELLOW))})
        check("a range that overlaps another vest is flagged", done["ok"], False)
        check("and the warning names both", "red and yellow" in done["message"])
        grey = np.zeros((288, 512, 3), dtype=np.uint8)
        grey[:, :] = GREY
        reading = vest.Calibration("yellow")
        out = [reading.feed(grey) for _ in range(vest.CALIBRATION_FRAMES)]
        check("a grey wall gives an answer, but no range",
              (out[-2], out[-1]["fit"]), (None, None))
        check("which the page explains",
              "didn't read as one color" in gui_server.finish_calibration(cfg, cfg["search"], out[-1])["message"])
        del os.environ["VENATOR_VEST_FILE"]

    start = time.perf_counter()
    for _ in range(100):
        vest.pick(vest.shares(vest.chest_pixels(frame, box), R))
    print(f"    info  {(time.perf_counter() - start) * 10:.2f} ms per person on this machine")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
