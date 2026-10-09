#!/usr/bin/env python3
"""The detection class policy.

classes.py decides what the detector reports and how confident it has to be.
Two things must hold or the drone either goes blind or cries wolf:

  * the device threshold must sit at or below every per-class threshold, because
    the hardware filter runs first and anything it drops is gone before the
    policy can vote on it;
  * COCO's junk classes must stay suppressed, since 96% of the old model's
    output at the operational threshold was "traffic light" fired on warehouse
    ceiling lights.

Stdlib only, no depthai, no hardware - this runs on a laptop, the Jetson and in
CI identically.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "drone" / "wildlife"))

import classes  # noqa: E402

PASS = FAIL = 0

MEGADETECTOR = ["animal", "person", "vehicle"]
# The real COCO order, truncated to what matters here.
COCO = ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
        "truck", "boat", "traffic light", "fire hydrant", "stop sign", "bird",
        "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
        "giraffe"]


def check(label, got, want=True):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"    {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"   got {got!r}"))


print("\nMegaDetector vocabulary")
check("animal at 0.40 is reported", classes.classify("animal", 0.40), ("animal", "animal"))
check("animal at 0.30 is below its floor", classes.classify("animal", 0.30), None)
check("person at 0.50 is reported", classes.classify("person", 0.50), ("person", "person"))
check("person at 0.40 is below its floor", classes.classify("person", 0.40), None)
# Vehicle is held high on purpose: 8 false hits at 57% mean on bench footage.
check("vehicle at 0.57 is rejected", classes.classify("vehicle", 0.57), None)
check("vehicle at 0.70 is reported", classes.classify("vehicle", 0.70), ("vehicle", "vehicle"))

print("\nCOCO stand-ins map to the coarse class, not the wrong species")
check("sheep -> animal", classes.classify("sheep", 0.40), ("animal", "sheep"))
check("bear -> animal", classes.classify("bear", 0.40), ("animal", "bear"))
check("dog -> animal", classes.classify("dog", 0.40), ("animal", "dog"))
check("car -> vehicle", classes.classify("car", 0.60), ("vehicle", "car"))

print("\nJunk classes stay suppressed at any confidence")
for junk in ("traffic light", "stop sign", "fire hydrant", "bench", "kite"):
    check(f"{junk!r} is never reported", classes.classify(junk, 0.99), None)

print("\nThe device floor cannot hide a class from the policy")
for name, labels in (("MegaDetector", MEGADETECTOR), ("COCO", COCO)):
    floor = classes.device_floor(labels)
    active = classes.policy_for(labels)
    worst = min(f for _, f in active.values())
    check(f"{name}: floor {floor:.2f} <= every per-class threshold",
          all(floor <= f for _, f in active.values()))
    check(f"{name}: floor equals the lowest threshold ({worst:.2f})", floor == worst)

print("\nAn explicit --conf override wins")
check("override is returned verbatim", classes.device_floor(MEGADETECTOR, 0.8), 0.8)
check("override of 0.0 is honoured, not treated as unset",
      classes.device_floor(MEGADETECTOR, 0.0), 0.0)

print("\nThresholds are sane")
check("every threshold is a probability",
      all(0.0 < f <= 1.0 for _, f in classes.CLASS_POLICY.values()))
check("every class reports as one of the three coarse categories",
      {r for r, _ in classes.CLASS_POLICY.values()}
      == {classes.ANIMAL, classes.PERSON, classes.VEHICLE})
check("animal is not held to a higher bar than vehicle",
      classes.CLASS_POLICY[classes.ANIMAL][1] < classes.CLASS_POLICY[classes.VEHICLE][1])

print("\nReported names")
check("coarse name by default", classes.report_name("animal", "sheep"), "animal")
check("raw label exposed on request",
      classes.report_name("animal", "sheep", raw_classes=True), "animal:sheep")
check("no redundant suffix when raw == reported",
      classes.report_name("animal", "animal", raw_classes=True), "animal")
check("MegaDetector reports three categories",
      classes.coarse_classes(MEGADETECTOR), ["animal", "person", "vehicle"])
check("COCO collapses to the same three",
      classes.coarse_classes(COCO), ["animal", "person", "vehicle"])

print("\nA model sharing no labels still gets a usable floor")
check("unknown vocabulary falls back", classes.device_floor(["widget", "gizmo"]),
      classes.FALLBACK_FLOOR)
check("and reports nothing", classes.coarse_classes(["widget"]), [])
check("describe() says so, rather than printing an empty table",
      "suppressed" in classes.describe(["widget"]))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
