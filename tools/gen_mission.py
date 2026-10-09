#!/usr/bin/env python3
"""Venator — search and rescue, end to end. The how-it-works banner.

A 30s cycle: the operator fences an area, the path is planned to cover it, the
view tilts from map to altitude, the aircraft sweeps it, finds two people and
treats them differently — one still on the ground raises an emergency over
LoRa, one moving is followed — and then it comes home with the track.

Half of this is not built, and the piece says so rather than implying
otherwise. Every beat carries a state chip in the same register the rest of
assets/brand/ uses: what is bench-tested against mocks, what is a phase that
has not started, and what has no code behind it at all. In particular
camera_publisher.py runs a MobileNetSpatialDetectionNetwork — a person
detector with depth, no pose and no motion state — so "still vs moving" is a
concept here, not a capability. The resting caption states the whole position.

THE TILT. A top-down view of a plane and an axonometric view of the same plane
differ by an affine transform, so the 2D->3D move is exact rather than faked:
the ground group animates between identity and `skewX/scaleY` about a fixed
pivot, and the flight group does the same plus a constant screen-space lift.
`tilt()` below is the Python side of that same matrix, used to place everything
that must NOT inherit the shear — the aircraft, the people, the drop lines —
because shearing an icon makes it look broken. Keep the two in step: the CSS
reads SKEW/SQUASH/TILT_DY/LIFT straight out of these constants.

Motion is CSS, not SMIL, so prefers-reduced-motion can stop it. With animation
off the piece rests as the tilted scene with both people found, which is the
frame worth seeing as a still.
"""
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets" / "brand"
W, H = 1000, 500
CYCLE = "30s"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
GROT = "Helvetica Neue,Helvetica,Arial,sans-serif"

THEMES = {
    "light": dict(bg="#F2F1EE", panel="#FFFFFF", line="#DAD8D3", muted="#6E6B66",
                  ink="#0A0A0A", signal="#E05316", grid="#E6E4E0"),
    "dark":  dict(bg="#0A0A0A", panel="#131314", line="#2A2A27", muted="#8A8781",
                  ink="#F2F1EE", signal="#E05316", grid="#151516"),
}

# ---------------------------------------------------------------- the field
# Field coordinates are the flat, top-down view: what you see for the first
# quarter of the cycle, and what every tilted position is derived from.
FENCE = [(168, 126), (528, 92), (748, 150), (806, 252), (486, 322), (186, 268)]
HOME = (132, 326)
SPACING = 46.0          # metres between sweep legs, in field px
ALT_M = 40              # under the validated 50 m cap — see gen_patrol.py

# The axonometric. PIVOT stays put through the tilt, so the scene does not
# slide out from under the caption while it happens.
PIVOT = (470, 212)
SKEW = 0.42             # tan of the shear; the CSS angle is derived from it
SQUASH = 0.58
TILT_DY = 54            # the tilted plane drops to leave headroom for altitude
LIFT = 80               # screen px between ground and the flight plane

# Beat boundaries, % of cycle. Stage bar underneath groups them into five.
GEO, PLANP, UPLOAD, TILT, SWEEP, OBST, FOUND_A, FOUND_B, REPORT, RTL, REST = (
    0, 9, 17, 25, 32, 46, 52, 59, 66, 78, 94)
# The scene holds, fully populated and tilted, while the resting caption is
# read; only the last couple of per cent unwind it for the loop.
HOLD = 98
STAGES = [("PLAN", GEO, TILT), ("FLY", TILT, FOUND_A), ("DETECT", FOUND_A, REPORT),
          ("REPORT", REPORT, RTL), ("RETURN", RTL, 100)]


def dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def seg_len(pts):
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def poly(pts):
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def tilt(p, lift=0.0):
    """The Python side of the CSS tilt. Must agree with #ground / #flight."""
    dx0, dy0 = p[0] - PIVOT[0], p[1] - PIVOT[1]
    dy = dy0 * SQUASH
    return (PIVOT[0] + dx0 + dy * SKEW, PIVOT[1] + dy + TILT_DY - lift)


def span(pts, y):
    """Where a horizontal line at y crosses a convex-ish polygon, or None."""
    xs = []
    for i in range(len(pts)):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % len(pts)]
        if (y1 <= y < y2) or (y2 <= y < y1):
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    return (min(xs), max(xs)) if len(xs) >= 2 else None


def coverage(pts, spacing, inset=16.0):
    """Boustrophedon fill: scan lines inside the fence, joined end to end.

    The inset keeps the turns off the boundary — flying the fence line itself
    is what a geofence is there to prevent.
    """
    ys = [p[1] for p in pts]
    y, legs, flip = min(ys) + spacing * 0.6, [], False
    while y < max(ys):
        s = span(pts, y)
        if s and s[1] - s[0] > inset * 2:
            a, b = s[0] + inset, s[1] - inset
            legs.append([(b, y), (a, y)] if flip else [(a, y), (b, y)])
            flip = not flip
        y += spacing
    return [p for leg in legs for p in leg]


PATH = coverage(FENCE, SPACING)
LEGS = [dist(PATH[i], PATH[i + 1]) for i in range(len(PATH) - 1)]
TOTAL = sum(LEGS)

# Time at each path vertex, spread by leg length so the speed is constant.
_cum, AT = 0.0, [SWEEP]
for _L in LEGS:
    _cum += _L
    AT.append(SWEEP + (RTL - SWEEP) * _cum / TOTAL)


def at_frac(f):
    """Position along PATH at fraction f of the sweep, as a field point."""
    want = TOTAL * max(0.0, min(1.0, f))
    run = 0.0
    for i, L in enumerate(LEGS):
        if run + L >= want:
            k = (want - run) / L if L else 0.0
            return (PATH[i][0] + (PATH[i + 1][0] - PATH[i][0]) * k,
                    PATH[i][1] + (PATH[i + 1][1] - PATH[i][1]) * k)
        run += L
    return PATH[-1]


# Where the story happens. The TIMES are what matter — a caption that talks
# about an obstacle while the aircraft is still two legs short of it reads as
# a bug — so the times are authored and the path fractions derived from them,
# never the other way round.
T_OBSTACLE, T_PERSON_A, T_PERSON_B = OBST + 3, FOUND_A + 2, FOUND_B + 2


def frac_at(pct):
    """Fraction along the swept path at a given % of the cycle."""
    return (pct - SWEEP) / (RTL - SWEEP)


F_OBST, F_A, F_B = (frac_at(T_OBSTACLE), frac_at(T_PERSON_A), frac_at(T_PERSON_B))
P_OBST, P_A, P_B = at_frac(F_OBST), at_frac(F_A), at_frac(F_B)
# The two people sit a little off the track — the aircraft finds them, it does
# not fly into them.
PERSON_A = (P_A[0] + 30, P_A[1] + 26)
PERSON_B = (P_B[0] - 34, P_B[1] + 24)
# The deviation: up and over the obstacle, then back on the line.
DEV_F = 0.035           # how far either side of the obstacle the detour runs
DEV_OFF = 76.0          # how far off the line it goes (field px, so the
                        # squash halves it on screen)


def tangent(f, eps=0.004):
    """Unit direction of travel at fraction f along the path."""
    a, b = at_frac(max(0.0, f - eps)), at_frac(min(1.0, f + eps))
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


# The detour goes perpendicular to the direction of travel, not along a fixed
# offset: a boustrophedon reverses on every leg, so a constant -x nudge is
# behind the aircraft on one leg and ahead of it on the next, which routes it
# straight through the thing it is supposed to be avoiding.
def inside(pt, pts):
    """Even-odd point in polygon."""
    x, y = pt
    c = False
    for i in range(len(pts)):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % len(pts)]
        if ((y1 > y) != (y2 > y)) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


_tx, _ty = tangent(F_OBST)
_nx, _ny = -_ty, _tx
F_DEV_IN, F_DEV_OUT = F_OBST - DEV_F, F_OBST + DEV_F


def _detour(sign):
    return [(at_frac(f)[0] + sign * _nx * DEV_OFF, at_frac(f)[1] + sign * _ny * DEV_OFF)
            for f in (F_DEV_IN, F_DEV_OUT)]


# Which side to pass on is not a free choice: a fence the aircraft leaves in
# order to avoid something is not a fence. Take the normal that keeps both ends
# of the detour inside it, and only fall back to the other if neither does.
DEV = next((d for d in (_detour(1), _detour(-1)) if all(inside(p, FENCE) for p in d)),
           _detour(1))

T_OBST = T_OBSTACLE
T_DEV_IN = SWEEP + (RTL - SWEEP) * F_DEV_IN
T_DEV_OUT = SWEEP + (RTL - SWEEP) * F_DEV_OUT

# Three parts: the line flown up to the detour, the detour itself — dashed, as
# the one stretch here with no code behind it — and the line resumed after.
I_IN = max(i for i in range(len(PATH)) if AT[i] < T_DEV_IN)
J_OUT = min(i for i in range(len(PATH)) if AT[i] > T_DEV_OUT)
BEFORE = PATH[:I_IN + 1] + [DEV[0]]
AFTER = [DEV[1]] + PATH[J_OUT:]
SEG_BEFORE, SEG_AFTER = seg_len(BEFORE), seg_len(AFTER)

TRAY_N = 16


def tray_t(n):
    """When slot n of the detections tray fills — evenly across the sweep."""
    return SWEEP + (RTL - SWEEP) * ((n + 1) / TRAY_N)


# The two slots that are a person rather than terrain are whichever land
# closest to the two finds, so the tray and the scene cannot disagree.
TRAY_HIT = {min(range(TRAY_N), key=lambda n: abs(tray_t(n) - T_PERSON_A)),
            min(range(TRAY_N), key=lambda n: abs(tray_t(n) - T_PERSON_B))}


def window(name, a, b):
    """steps(1,end) keyframe that shows an element only within [a, b)."""
    if a == 0:
        return f"    @keyframes {name} {{ 0%,{b-0.1:g}% {{opacity:1}} {b:g}%,100% {{opacity:0}} }}"
    if b >= 100:
        return f"    @keyframes {name} {{ 0%,{a-0.1:g}% {{opacity:0}} {a:g}%,100% {{opacity:1}} }}"
    return (f"    @keyframes {name} {{ 0%,{a-0.1:g}% {{opacity:0}} {a:g}%,{b-0.1:g}% {{opacity:1}} "
            f"{b:g}%,100% {{opacity:0}} }}")


def chip(x, y, text, colour, bg, dashed=False, w=None):
    """A caption chip. Width is measured in mono ems rather than guessed."""
    w = w if w is not None else len(text) * 5.9 + 22
    dash = ' stroke-dasharray="4 3"' if dashed else ""
    return (f'<g transform="translate({x:.1f},{y:.1f})">'
            f'<rect x="{-w/2:.1f}" y="-15" width="{w:.1f}" height="22" rx="2" fill="{bg}" '
            f'stroke="{colour}" stroke-width="1.2"{dash}/>'
            f'<text x="0" y="1" fill="{colour}" font-family="{MONO}" font-size="9.5" '
            f'text-anchor="middle" letter-spacing="0.6">{text}</text></g>')


def build(theme):
    t = THEMES[theme]
    skew_deg = math.degrees(math.atan(SKEW))
    flat = "translate(0px,0px) skewX(0deg) scaleY(1)"
    tilted = f"translate(0px,{TILT_DY}px) skewX({skew_deg:.3f}deg) scaleY({SQUASH})"
    lifted = f"translate(0px,{TILT_DY-LIFT}px) skewX({skew_deg:.3f}deg) scaleY({SQUASH})"

    # ---------------------------------------------------------------- captions
    caps = [
        ("m0", GEO,     PLANP,   "muted",  "operator fences the search area  ·  no geofence in the repo yet"),
        ("m1", PLANP,   UPLOAD,  "signal", "coverage path planned to cover the box  ·  no planner built"),
        ("m2", UPLOAD,  TILT,    "signal", "WP_BEGIN{n}  &#8594;  WP{i,lat,lon,alt} each ACKed  &#8594;  WP_END  &#8594;  "
                                           "0 &lt; alt &#8804; 50 m  &#8594;  CONFIRM  &#8594;  ARMED"),
        ("m3", TILT,    SWEEP,   "ink",    f"AUTO.TAKEOFF  &#8594;  {ALT_M} m  ·  the plan is a surface, not a line"),
        ("m4", SWEEP,   OBST,    "ink",    "AUTO.MISSION  ·  sweeping the area  ·  OAK-D looking down"),
        ("m5", OBST,    FOUND_A, "signal", "obstacle ahead  &#8594;  deviating  ·  Phase 6, not started"),
        ("m6", FOUND_A, FOUND_B, "signal", "person detected, not moving  &#8594;  hold station  ·  "
                                           "posture is not something the detector reports"),
        ("m7", FOUND_B, REPORT,  "signal", "person detected, moving  &#8594;  OFFBOARD follow, keep 3 m  ·  Mission 2"),
        ("m8", REPORT,  RTL,     "signal", "ALERT{person, x, y, static}  &#8594;  915 MHz SF7  &#8594;  ground station"),
        ("m9", RTL,     REST,    "ink",    "AUTO.RTL  &#8594;  home  ·  the track and the detections land with the operator"),
        ("m10", REST,   100,     "muted",  "Concept. Detection, follow, upload, the arm gate and RTL are built "
                                           "and bench-tested against mocks.||The fence, the planner, the "
                                           "deviation and the still-vs-moving call are not. Outdoor flight pending."),
    ]

    def cap_text(i, c, s):
        """One line, or two where '||' splits it. At 12px mono with the
        letter-spacing below a line runs out of canvas around 110 characters,
        and the resting caption is the one line that must not be clipped."""
        head, _, tail = s.partition("||")
        y = 458 if tail else 470
        body = head + (f'<tspan x="56" dy="16">{tail}</tspan>' if tail else "")
        return (f'    <text id="{i}" x="56" y="{y}" fill="{t[c]}" font-family="{MONO}" '
                f'font-size="12" letter-spacing="0.8">{body}</text>')

    cap_el = "\n".join(cap_text(i, c, s) for i, _, _, c, s in caps)
    cap_css = "\n".join(f"    #{i} {{ animation: k{i} {CYCLE} steps(1,end) infinite }}"
                        for i, _, _, _, _ in caps)
    cap_kf = "\n".join(window(f"k{i}", a, b) for i, a, b, _, _ in caps)

    # ------------------------------------------------------------- stage bar
    stage_el, stage_css, stage_kf = [], [], []
    sx = 56
    for n, (label, a, b) in enumerate(STAGES):
        stage_el.append(
            f'<g transform="translate({sx},424)">'
            f'<circle cx="0" cy="-4" r="3.2" fill="{t["line"]}"/>'
            f'<circle id="sd{n}" cx="0" cy="-4" r="3.2" fill="{t["signal"]}"/>'
            f'<text x="12" y="0" fill="{t["muted"]}" font-family="{MONO}" font-size="10" '
            f'letter-spacing="1.8">{label}</text>'
            f'<text id="sl{n}" x="12" y="0" fill="{t["signal"]}" font-family="{MONO}" '
            f'font-size="10" letter-spacing="1.8">{label}</text></g>')
        if n < len(STAGES) - 1:
            stage_el.append(f'<path d="M{sx+len(label)*7.2+26} 420H{sx+140}" '
                            f'stroke="{t["line"]}" stroke-width="1"/>')
        stage_css.append(f"    #sd{n}, #sl{n} {{ opacity:0; animation: ks{n} {CYCLE} steps(1,end) infinite }}")
        stage_kf.append(window(f"ks{n}", a, b))
        sx += 160

    # ------------------------------------------------------------- the fence
    fence_len = seg_len(FENCE + [FENCE[0]])
    verts = "".join(
        f'<circle cx="{x}" cy="{y}" r="3.4" fill="{t["signal"]}"/>' for x, y in FENCE)

    # Ground grid, clipped to the stage so the tilt does not run off the edge.
    grid = "".join(f'<path d="M{x} 70V350" stroke="{t["grid"]}" stroke-width="1"/>'
                   for x in range(80, 941, 40))
    grid += "".join(f'<path d="M56 {y}H944" stroke="{t["grid"]}" stroke-width="1"/>'
                    for y in range(70, 351, 40))

    # Drop lines: computed at tilted positions, because they only exist tilted.
    drops = "".join(
        f'<path d="M{tilt(p,LIFT)[0]:.1f} {tilt(p,LIFT)[1]:.1f}'
        f'L{tilt(p)[0]:.1f} {tilt(p)[1]:.1f}" stroke="{t["line"]}" stroke-width="1"/>'
        for p in FENCE)

    # The aircraft's own keyframes, in absolute screen space so it never shears.
    # Built as (time, point) and sorted numerically. Emitting strings and
    # sorting those puts 100% before 25%, and a duplicate time silently wins
    # or loses depending on set ordering.
    keys = [(0.0, HOME), (float(UPLOAD), HOME), (float(TILT), HOME)]
    keys += [(AT[i], tilt(p, LIFT)) for i, p in enumerate(PATH) if AT[i] < T_DEV_IN]
    keys += [(T_DEV_IN, tilt(DEV[0], LIFT)), (T_DEV_OUT, tilt(DEV[1], LIFT))]
    keys += [(AT[i], tilt(p, LIFT)) for i, p in enumerate(PATH) if AT[i] > T_DEV_OUT]
    # Overhead the pad, then down onto it: the mission's last item is RTL, and
    # RTL ends landed and disarmed.
    keys += [(float(RTL) + 8, tilt(HOME, LIFT)), (float(REST), tilt(HOME)),
             (float(HOLD), tilt(HOME)), (100.0, HOME)]
    seen = {}
    for _t, _p in keys:
        seen[round(_t, 4)] = _p
    fly_kf = "\n".join(
        f"      {_t:g}% {{ transform: translate({_p[0]:.1f}px,{_p[1]:.1f}px) }}"
        for _t, _p in sorted(seen.items()))

    # The ground footprint tracks the aircraft, one plane down.
    foot_kf = []
    for i, p in enumerate(PATH):
        q = tilt(p)
        foot_kf.append(f"      {AT[i]:g}% {{ transform: translate({q[0]:.1f}px,{q[1]:.1f}px) }}")
    _fh = tilt(HOME)
    foot_kf = ([f"      0%,{SWEEP}% {{ transform: translate({_fh[0]:.1f}px,{_fh[1]:.1f}px) }}"]
               + foot_kf
               + [f"      {HOLD}%,100% {{ transform: translate({_fh[0]:.1f}px,{_fh[1]:.1f}px) }}"])
    foot_kf = "\n".join(foot_kf)

    # ------------------------------------------------------------------ tray
    tray, tray_css, tray_kf = [], [], []
    tw, tx0 = 44, 56
    for n in range(TRAY_N):
        x = tx0 + n * (tw + 6)
        hit = n in TRAY_HIT
        col = t["signal"] if hit else t["muted"]
        tray.append(
            f'<g><rect x="{x}" y="368" width="{tw}" height="34" fill="none" '
            f'stroke="{t["line"]}" stroke-width="1"/>'
            f'<g id="tf{n}"><rect x="{x}" y="368" width="{tw}" height="34" '
            f'fill="{col}" opacity="{0.22 if hit else 0.13}"/>'
            f'<rect x="{x}" y="368" width="{tw}" height="34" fill="none" stroke="{col}" '
            f'stroke-width="{1.4 if hit else 1}"/>'
            + (f'<circle cx="{x+tw/2}" cy="385" r="4.6" fill="none" stroke="{t["signal"]}" '
               f'stroke-width="1.5"/>' if hit else "") + '</g></g>')
        a = tray_t(n)
        tray_css.append(f"    #tf{n} {{ opacity:0; animation: kt{n} {CYCLE} steps(1,end) infinite }}")
        tray_kf.append(f"    @keyframes kt{n} {{ 0%,{a-0.1:g}% {{opacity:0}} {a:g}%,100% {{opacity:1}} }}")

    def person(pid, p, moving):
        q = tilt(p)
        lock = (f'<g id="{pid}lock" fill="none" stroke="{t["signal"]}" stroke-width="1.6">'
                f'<path d="M-16-40h-8v8M16-40h8v8M-16 6h-8V-2M16 6h8V-2"/></g>')
        return (f'<g id="{pid}" transform="translate({q[0]:.1f},{q[1]:.1f})">'
                f'<ellipse cx="0" cy="2" rx="17" ry="7" fill="{t["signal"]}" opacity=".13"/>'
                + (f'<g fill="{t["ink"]}"><circle cx="0" cy="-30" r="6"/>'
                   f'<path d="M-5-23h10l2 14h-5l-1 11h-3l-1-11h-4z"/></g>' if moving else
                   f'<g fill="{t["ink"]}"><circle cx="-14" cy="-6" r="6"/>'
                   f'<path d="M-9-11h22v9h-22z"/></g>')
                + lock + '</g>')

    q_obst = tilt(P_OBST, LIFT)
    obstacle = (f'<g id="obst" transform="translate({q_obst[0]:.1f},{q_obst[1]:.1f})">'
                f'<path d="M-21 0l21-12 21 12-21 12z" fill="none" stroke="{t["ink"]}" '
                f'stroke-width="1.6"/>'
                f'<path d="M-21 0v-13l21-12 21 12v13" fill="none" stroke="{t["ink"]}" '
                f'stroke-width="1.6" opacity=".55"/>'
                f'<ellipse cx="0" cy="0" rx="42" ry="26" fill="none" stroke="{t["signal"]}" '
                f'stroke-width="1.3" stroke-dasharray="4 4"/></g>')

    q_home = tilt(HOME)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     role="img" aria-label="Venator search and rescue concept: an operator fences a search area, a coverage path is planned inside it, the view tilts to show {ALT_M} m of altitude, the aircraft sweeps the area and deviates around an obstacle, finds one person who is not moving and raises an emergency over 915 MHz LoRa, finds a second who is moving and follows, then returns home. Detection, follow, upload and RTL are bench-tested against mocks; the fence, the planner, the obstacle deviation and the still-versus-moving call are not built.">
  <title>Venator — search and rescue (concept)</title>
  <style>
    #ground, #flight {{ transform-box: view-box; transform-origin: {PIVOT[0]}px {PIVOT[1]}px;
                       animation: toIso {CYCLE} ease-in-out infinite }}
    #ground {{ animation-name: isoGround }}
    #flight {{ animation-name: isoFlight }}
    @keyframes isoGround {{
      0%,{TILT}% {{ transform: {flat} }}
      {SWEEP}%,{HOLD}% {{ transform: {tilted} }}
      100% {{ transform: {flat} }}
    }}
    @keyframes isoFlight {{
      0%,{TILT}% {{ transform: {flat} }}
      {SWEEP}%,{HOLD}% {{ transform: {lifted} }}
      100% {{ transform: {flat} }}
    }}

    #fence {{ stroke-dasharray: {fence_len:.1f}; stroke-dashoffset: {fence_len:.1f};
             animation: drawFence {CYCLE} linear infinite }}
    @keyframes drawFence {{ 0% {{ stroke-dashoffset: {fence_len:.1f} }}
                           {PLANP}%,100% {{ stroke-dashoffset: 0 }} }}
    #plan {{ stroke-dasharray: {TOTAL:.1f}; stroke-dashoffset: {TOTAL:.1f};
            animation: drawPlan {CYCLE} linear infinite }}
    @keyframes drawPlan {{ 0%,{PLANP}% {{ stroke-dashoffset: {TOTAL:.1f} }}
                          {UPLOAD}%,100% {{ stroke-dashoffset: 0 }} }}

    /* Flown track, in two parts so the deviation can sit between them. */
    #flownA {{ stroke-dasharray: {SEG_BEFORE:.1f}; stroke-dashoffset: {SEG_BEFORE:.1f};
              animation: drawA {CYCLE} linear infinite }}
    @keyframes drawA {{ 0%,{SWEEP}% {{ stroke-dashoffset: {SEG_BEFORE:.1f} }}
                       {T_DEV_IN:g}%,100% {{ stroke-dashoffset: 0 }} }}
    #flownB {{ stroke-dasharray: {SEG_AFTER:.1f}; stroke-dashoffset: {SEG_AFTER:.1f};
              animation: drawB {CYCLE} linear infinite }}
    @keyframes drawB {{ 0%,{T_DEV_OUT:g}% {{ stroke-dashoffset: {SEG_AFTER:.1f} }}
                       {RTL}%,100% {{ stroke-dashoffset: 0 }} }}

    #drone {{ transform-box: view-box; transform-origin: 0 0;
             animation: fly {CYCLE} linear infinite }}
    @keyframes fly {{
{fly_kf}
    }}
    #foot {{ transform-box: view-box; transform-origin: 0 0;
            animation: foot {CYCLE} linear infinite }}
    @keyframes foot {{
{foot_kf}
    }}
    #rotor ellipse {{ transform-box: fill-box; transform-origin: center;
                     animation: spin .34s linear infinite }}
    @keyframes spin {{ 0%,100% {{ transform: scaleX(1) }} 50% {{ transform: scaleX(.28) }} }}

    #drops, #shadow, #altChip {{ opacity:0; animation: kDrops {CYCLE} steps(1,end) infinite }}
    @keyframes kDrops {{ 0%,{SWEEP-0.1:g}% {{opacity:0}} {SWEEP:g}%,{HOLD-0.1:g}% {{opacity:1}}
                        {HOLD:g}%,100% {{opacity:0}} }}
    #footG {{ opacity:0; animation: kFoot {CYCLE} steps(1,end) infinite }}
    @keyframes kFoot {{ 0%,{SWEEP-0.1:g}% {{opacity:0}} {SWEEP:g}%,{RTL-0.1:g}% {{opacity:1}}
                       {RTL:g}%,100% {{opacity:0}} }}

    #obst {{ opacity:0; animation: kObst {CYCLE} steps(1,end) infinite }}
{window('kObst', OBST, HOLD)}
    #pa {{ opacity:0; animation: kPa {CYCLE} steps(1,end) infinite }}
{window('kPa', FOUND_A, HOLD)}
    #pb {{ opacity:0; animation: kPb {CYCLE} steps(1,end) infinite }}
{window('kPb', FOUND_B, HOLD)}
    #palock, #pblock {{ animation: pulse 1.1s ease-in-out infinite }}
    @keyframes pulse {{ 0%,100% {{ opacity:1 }} 50% {{ opacity:.35 }} }}

    #followChip {{ opacity:0; animation: kPb {CYCLE} steps(1,end) infinite }}
    #alert {{ opacity:0; animation: kAlert {CYCLE} steps(1,end) infinite }}
{window('kAlert', REPORT, RTL)}
    #alert .rings circle {{ transform-box: fill-box; transform-origin: center;
                           animation: ping 1.5s linear infinite }}
    #alert .rings circle:nth-child(2) {{ animation-delay: .5s }}
    #alert .rings circle:nth-child(3) {{ animation-delay: 1s }}
    @keyframes ping {{ 0% {{ transform: scale(1); opacity:.85 }}
                      100% {{ transform: scale(7); opacity:0 }} }}
    #armed {{ opacity:0; animation: kArmed {CYCLE} steps(1,end) infinite }}
{window('kArmed', UPLOAD + 5, REST)}
    #dev, #devChip {{ opacity:0; animation: kDev {CYCLE} steps(1,end) infinite }}
{window('kDev', OBST, FOUND_A)}
{chr(10).join(tray_css)}
{chr(10).join(tray_kf)}
{chr(10).join(stage_css)}
{chr(10).join(stage_kf)}
    #m10 {{ opacity:1 }}
{cap_css}
{cap_kf}
    @media (prefers-reduced-motion: reduce) {{
      #ground {{ animation: none; transform: {tilted} }}
      #flight {{ animation: none; transform: {lifted} }}
      #drone, #foot, #rotor ellipse, #palock, #pblock,
      #alert .rings circle {{ animation: none }}
      #drone {{ transform: translate({tilt(P_B, LIFT)[0]:.1f}px,{tilt(P_B, LIFT)[1]:.1f}px) }}
      #footG, #alert .rings {{ display: none }}
      #fence, #plan, #flownA, #flownB {{ animation: none; stroke-dashoffset: 0 }}
      #dev {{ opacity:1; animation: none }}
      #drops, #shadow, #altChip, #obst, #pa, #pb, #alert, #armed, #devChip,
      #followChip {{ opacity:1; animation: none }}
      [id^="tf"] {{ opacity:1; animation: none }}
      [id^="sd"], [id^="sl"] {{ opacity:0; animation: none }}
      #sd2, #sl2 {{ opacity:1 }}
      #ticker text {{ animation: none; opacity:0 }}
      #m10 {{ opacity:1 }}
    }}
  </style>
  <rect width="{W}" height="{H}" fill="{t['bg']}"/>

  <text x="56" y="38" fill="{t['muted']}" font-family="{GROT}" font-size="11"
    font-weight="600" letter-spacing="3.4">SEARCH AND RESCUE</text>
  <text x="56" y="58" fill="{t['ink']}" font-family="{GROT}" font-size="15" font-weight="600">
    Fence an area, sweep it, find who is in it, come home — the system as designed</text>

  <g id="ground">
    {grid}
    <path id="shadow" d="{poly(FENCE)} Z" fill="none" stroke="{t['line']}"
      stroke-width="1.2" stroke-dasharray="5 4"/>
  </g>

  <g id="drops">{drops}</g>

  <!-- Fence and path lift together: the fence is a volume with a ceiling, and
       the aircraft flies inside it. Flat, the lift is zero and this is a map. -->
  <g id="flight">
    <path id="fenceFill" d="{poly(FENCE)} Z" fill="{t['signal']}" opacity=".05"/>
    <path id="fence" d="{poly(FENCE)} Z" fill="none" stroke="{t['signal']}" stroke-width="2"/>
    {verts}
    <path id="plan" d="{poly(PATH)}" fill="none" stroke="{t['muted']}"
      stroke-width="1.3" stroke-dasharray="{TOTAL:.1f}"/>
    <path id="flownA" d="{poly(BEFORE)}" fill="none" stroke="{t['signal']}" stroke-width="2.2"/>
    <path id="dev" d="{poly(DEV)}" fill="none" stroke="{t['signal']}"
      stroke-width="2.2" stroke-dasharray="7 5"/>
    <path id="flownB" d="{poly(AFTER)}" fill="none" stroke="{t['signal']}" stroke-width="2.2"/>
  </g>

  {obstacle}
  {person('pa', PERSON_A, moving=False)}
  {person('pb', PERSON_B, moving=True)}

  <g id="footG"><g id="foot">
    <ellipse rx="26" ry="12" fill="{t['signal']}" opacity=".12"/>
    <ellipse rx="26" ry="12" fill="none" stroke="{t['signal']}" stroke-width="1"
      stroke-dasharray="3 3" opacity=".5"/>
  </g></g>

  <g transform="translate({q_home[0]:.1f},{q_home[1]:.1f})">
    <rect x="-12" y="-12" width="24" height="24" fill="none" stroke="{t['muted']}" stroke-width="1.6"/>
    <text x="0" y="28" fill="{t['muted']}" font-family="{MONO}" font-size="10"
      text-anchor="middle" letter-spacing="1">HOME</text>
  </g>

  <g id="drone">
    <g id="rotor">
      <ellipse cx="-19" cy="-9" rx="11" ry="2.4" fill="{t['muted']}"/>
      <ellipse cx="19" cy="-9" rx="11" ry="2.4" fill="{t['muted']}"/>
      <ellipse cx="-19" cy="9" rx="11" ry="2.4" fill="{t['muted']}"/>
      <ellipse cx="19" cy="9" rx="11" ry="2.4" fill="{t['muted']}"/>
    </g>
    <path d="M-19-9L19 9M19-9L-19 9" stroke="{t['ink']}" stroke-width="2"/>
    <rect x="-7" y="-5" width="14" height="10" rx="2" fill="{t['ink']}"/>
  </g>

  <!-- The altitude chip rides the leftmost drop line; the deviation chip sits
       clear above the obstacle. Both are placed off measured tilted points, so
       moving the fence cannot push them into each other. -->
  <g id="altChip">
    {chip(104, (tilt(FENCE[0])[1] + tilt(FENCE[0], LIFT)[1]) / 2, f"ALTITUDE {ALT_M} m",
          t['signal'], t['bg'])}
  </g>

  <g id="devChip">
    {chip(q_obst[0] + 104, 100, "DEVIATE &#183; Phase 6, not started", t['signal'], t['bg'], dashed=True)}
  </g>

  <!-- The two finds, and the two different answers. The protocol line itself
       is in the ticker, so these stay short enough to read at a glance. -->
  <g id="alert" transform="translate({tilt(PERSON_A)[0]:.1f},{tilt(PERSON_A)[1]:.1f})">
    <g class="rings" fill="none" stroke="{t['signal']}" stroke-width="1.6">
      <circle r="9"/><circle r="9"/><circle r="9"/>
    </g>
    {chip(-34, 44, "EMERGENCY &#183; not built", t['signal'], t['bg'], dashed=True)}
  </g>

  <g id="followChip">
    {chip(tilt(PERSON_B)[0] - 10, tilt(PERSON_B)[1] + 44, "FOLLOW 3 m &#183; Mission 2",
          t['signal'], t['bg'])}
  </g>

  <g id="armed" transform="translate(856,58)">
    <circle r="4" cx="0" cy="-4" fill="{t['signal']}"/>
    <text x="12" y="0" fill="{t['signal']}" font-family="{MONO}" font-size="11"
      letter-spacing="1.6">ARMED</text>
  </g>

  <text x="56" y="360" fill="{t['muted']}" font-family="{MONO}" font-size="9.5"
    letter-spacing="1.6">DETECTIONS</text>
  {"".join(tray)}

  {"".join(stage_el)}

  <g id="ticker">
{cap_el}
  </g>
</svg>
"""


if __name__ == "__main__":
    for name in ("light", "dark"):
        p = ROOT / f"mission-{name}.svg"
        p.write_text(build(name), encoding="utf-8")
        print(f"{p.name}: {p.stat().st_size} bytes")
    print(f"fence {len(FENCE)} verts, path {len(PATH)} pts, {TOTAL:.0f} px,"
          f" obstacle at {T_OBST:.1f}%")
