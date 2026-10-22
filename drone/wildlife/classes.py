#!/usr/bin/env python3
"""
What the detector reports, and how confident it has to be before it says so.

One table, shared by oak_wildlife.py, test_detector.py and the operator GUI, so
the live flight path and the offline evaluation harness can never disagree about
which detections count. Both files used to carry their own copy of this list.

Stdlib only, no depthai: this has to import under plain python3 for the tests
and under both OAK virtualenvs (oak-venv has depthai 3 but no OpenCV).

Why a table and not a single --conf
-----------------------------------
A global threshold cannot say "I'll take a weak animal but not a weak vehicle",
and that asymmetry is the whole job. Measured on the 89 frames in
~/Pictures/wildlife at the old global 0.5:

    yolov6-nano (COCO) : 26 detections, 25 of them "traffic light" at 61% mean
                         confidence - warehouse ceiling lights, fired on
                         *confidently*. Raising the threshold keeps the lights
                         and discards the real hits.
    MegaDetector V6    : 9 detections, 8 of them "vehicle" at 57% mean.

So: ceiling lights are gone structurally (MegaDetector has no such class, and
COCO's "traffic light" is simply absent from this table), and "vehicle" - the
least load-bearing class for a wildlife corridor survey - is held to a higher
bar than "animal" is.

Two vocabularies, one table
---------------------------
MegaDetector V6 speaks animal/person/vehicle natively. The COCO baseline is
still reachable with --model, and its animal classes are stand-ins for Texas
species it was never trained on - a feral hog lands on "bear" or "sheep", a
coyote on "dog", a bobcat on "cat". Those are mapped to the coarse "animal"
and the wrong species name is demoted to a debug field, because reporting
"sheep" in the Rio Grande valley is worse than reporting "animal": it is
confidently wrong, and a human reading the log would have to un-learn it.

Labels absent from the table are suppressed. That is deliberate and is how
"traffic light" stops being 96% of the output.
"""

ANIMAL = "animal"
PERSON = "person"
VEHICLE = "vehicle"

#: raw model label -> (what we report it as, minimum confidence to report)
CLASS_POLICY = {
    # --- MegaDetector V6 (MDV6-yolov10-c), the default model ---------------
    # Animal sits lowest: the model's headline metric is animal *recall*
    # (mAR 76.8) because its authors optimise for not missing animals and
    # expect a downstream filter. A missed animal is an unrecoverable error;
    # a false one costs a glance at an evidence JPEG.
    ANIMAL:  (ANIMAL,  0.35),
    # Person is the SAR class. Favour recall over precision for the same
    # reason, but a notch higher than animal - a person-down alert wakes
    # somebody up, so it should be worth waking up for.
    #
    # KNOWN FALSE POSITIVE, measured: a wild turkey reads as "person" at 71%
    # (and 77% on the COCO baseline, so it is not specific to this model).
    # Deliberately NOT fixed by raising this threshold - that would cost real
    # person recall, which is the one thing the SAR path cannot trade away.
    # It is filtered downstream instead, by the metric-extent gate: a person
    # is 1.2-2.2 m long by stereo Z, a turkey is ~0.6 m. Any consumer that
    # acts on `person` rather than just displaying it needs that gate.
    PERSON:  (PERSON,  0.45),
    # Vehicle is held high: it is the measured false-positive mode (8 hits at
    # 57% mean on indoor bench footage) and the least useful of the three for
    # this mission. 0.65 clears nearly all of that noise.
    VEHICLE: (VEHICLE, 0.65),

    # --- COCO stand-ins, used when --model is the yolov6-nano baseline -----
    # The comment is the Texas species the COCO class actually stands in for.
    "dog":        (ANIMAL,  0.35),   # coyote, feral dog
    "cat":        (ANIMAL,  0.40),   # bobcat, ocelot
    "cow":        (ANIMAL,  0.30),   # nilgai, cattle, a large hog
    "horse":      (ANIMAL,  0.35),   # nilgai, aoudad, white-tailed deer
    "sheep":      (ANIMAL,  0.30),   # javelina, aoudad, hog
    "bear":       (ANIMAL,  0.30),   # feral hog, javelina
    "bird":       (ANIMAL,  0.55),   # raised: vultures are everywhere and
                                     # carry little information here
    "elephant":   (ANIMAL,  0.45),
    "zebra":      (ANIMAL,  0.55),
    "giraffe":    (ANIMAL,  0.60),
    "car":        (VEHICLE, 0.50),
    "truck":      (VEHICLE, 0.50),
    "bus":        (VEHICLE, 0.55),
    "motorcycle": (VEHICLE, 0.45),
}

#: Fallback device threshold when a model shares no labels with the table at
#: all. Low rather than high: a silent detector is harder to debug than a
#: noisy one, and the host-side filter still drops everything unrecognised.
FALLBACK_FLOOR = 0.3


def classify(label, conf):
    """
    Decide whether one raw detection is worth reporting.

    Returns (reported_as, raw_label) when it clears its class threshold, or
    None when the class is not in the policy or the confidence is too low.
    """
    entry = CLASS_POLICY.get(label)
    if entry is None:
        return None
    reported, floor = entry
    if conf < floor:
        return None
    return reported, label


def policy_for(labels):
    """The subset of the policy that a model with `labels` can actually emit."""
    return {name: CLASS_POLICY[name] for name in labels if name in CLASS_POLICY}


def device_floor(labels, override=None):
    """
    The confidence threshold to program into the network itself.

    It has to be the *lowest* of the per-class thresholds, because the device
    filter runs before classify() ever sees a detection - set it to the mean
    or the max and the device silently eats animals that the policy would have
    accepted. An explicit --conf overrides the whole scheme.
    """
    if override is not None:
        return override
    active = policy_for(labels)
    if not active:
        return FALLBACK_FLOOR
    return min(floor for _, floor in active.values())


def report_name(reported, raw, raw_classes=False):
    """
    How a detection is written in logs, evidence frames and the GUI.

    `raw_classes` exposes the underlying model label, which only differs from
    the reported name for the COCO stand-ins - that is exactly when you want
    to see it, to tell a real bobcat from the model's idea of a cat.
    """
    if raw_classes and raw != reported:
        return f"{reported}:{raw}"
    return reported


def coarse_classes(labels):
    """Sorted coarse categories a model can report, for status lines."""
    return sorted({reported for reported, _ in policy_for(labels).values()})


def describe(labels):
    """Multi-line human summary of the active policy, for --list-classes."""
    active = policy_for(labels)
    if not active:
        return (f"  none of this model's {len(labels)} classes are in the "
                f"policy; everything would be suppressed")
    rows = []
    for name in sorted(active, key=lambda n: (active[n][0], n)):
        reported, floor = active[name]
        stand_in = "" if name == reported else f"  (reported as {reported})"
        rows.append(f"  {name:<12} conf >= {floor:.2f}{stand_in}")
    return "\n".join(rows)
