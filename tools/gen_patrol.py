#!/usr/bin/env python3
"""Venator — 'fly to these coordinates', the patrol that completes.

A map view rather than the side view used by conops: a patrol is a ground
track, so lat/lon is the projection that means something. 16s cycle.

Beats follow drone/c2_server.py exactly: WP_BEGIN -> WP xN (each ACKed) ->
WP_END -> validate (0 < alt <= MAX_ALT_M) -> ACK{uploaded} -> CONFIRM -> arm ->
AUTO.TAKEOFF -> AUTO.MISSION -> RTL, which is the mission's own last item.

Leg timings are proportional to leg length so the aircraft holds a constant
speed, and the flown route is drawn with a dashoffset on the same schedule so
the line grows exactly under it.
"""
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets" / "brand"
W, H = 1000, 420
CYCLE = "16s"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
GROT = "Helvetica Neue,Helvetica,Arial,sans-serif"

THEMES = {
    "light": dict(bg="#F2F1EE", panel="#FFFFFF", line="#DAD8D3", muted="#6E6B66",
                  ink="#0A0A0A", signal="#E05316", grid="#E6E4E0"),
    "dark":  dict(bg="#0A0A0A", panel="#131314", line="#2A2A27", muted="#8A8781",
                  ink="#F2F1EE", signal="#E05316", grid="#151516"),
}

HOME = (150, 316)
WPS = [(320, 150), (585, 116), (812, 244), (536, 342)]
# The obstacle sits on the straight leg 2 -> 3. The operator's uploaded plan runs
# right through it; the flown track goes over the top. That contrast is the whole
# point of the beat, so the two routes are deliberately different geometry.
OBST = (664, 152, 72, 56)                      # x, y, w, h
DEV = [(648, 98), (730, 118)]                 # the way round

# Beat boundaries, % of cycle
PLOT, UPLOAD, ARM, TAKEOFF, PATROL, RTL, DONE, REST = 0, 9, 26, 33, 39, 73, 87, 93


def dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


PLAN = [HOME] + WPS                            # what was uploaded
PATH = [HOME, WPS[0], WPS[1]] + DEV + [WPS[2], WPS[3]]   # what is flown
LEGS = [dist(PATH[i], PATH[i + 1]) for i in range(len(PATH) - 1)]
TOTAL = sum(LEGS)
RTL_LEN = dist(WPS[-1], HOME)


def seg_len(pts):
    return sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))

# Time at which each waypoint is reached, spread by leg length.
span = RTL - PATROL
cum, AT = 0.0, [PATROL]            # time the aircraft reaches each PATH vertex
for L in LEGS:
    cum += L
    AT.append(PATROL + span * cum / TOTAL)
# PATH indices: 0 HOME, 1 wp1, 2 wp2, 3 devA, 4 devB, 5 wp3, 6 wp4
ARRIVE = [AT[1], AT[2], AT[5], AT[6]]          # the four numbered waypoints
DEV_IN, DEV_OUT = AT[2], AT[5]                 # the deviation window

SEG_A = seg_len(PATH[0:3])
SEG_DEV = seg_len(PATH[2:6])
SEG_B = seg_len(PATH[5:7])


def poly(pts):
    return "M" + " L".join(f"{x},{y}" for x, y in pts)


def grow(rid, pts, a, b, colour, dash_reveal=False):
    """A route segment that draws itself between a% and b% of the cycle."""
    L = seg_len(pts)
    if dash_reveal:      # the deviation is dashed, so it cannot also grow by dashoffset
        return (f'<path id="{rid}" d="{poly(pts)}" fill="none" stroke="{colour}" '
                f'stroke-width="2.2" stroke-dasharray="7 5" opacity="0"/>')
    return (f'<path id="{rid}" d="{poly(pts)}" fill="none" stroke="{colour}" '
            f'stroke-width="2.2" stroke-dasharray="{L:.1f}" stroke-dashoffset="{L:.1f}"/>')


def build(theme):
    t = THEMES[theme]

    wp_frames = "\n".join(
        f"    @keyframes kwp{i} {{ 0%,{a-0.1:g}% {{opacity:0}} {a:g}%,100% {{opacity:1}} }}"
        for i, a in enumerate(ARRIVE))
    wp_css = "\n".join(
        f"    #wpOn{i}, #wpNum{i} {{ opacity:0; animation: kwp{i} {CYCLE} steps(1,end) infinite }}"
        for i in range(len(WPS)))

    # Drone keyframes: sits on the pad, climbs (no map movement), flies the legs, returns.
    legs_kf = "\n".join(
        f"      {AT[i+1]:g}% {{ transform: translate({PATH[i+1][0]}px, {PATH[i+1][1]}px) }}"
        for i in range(len(PATH) - 1))

    caps = [
        ("p0", PLOT,    UPLOAD,  "muted",  "operator plots 4 coordinates"),
        ("p1", UPLOAD,  ARM,     "signal", 'WP_BEGIN{4}  →  WP{i,lat,lon,alt} ×4, each ACKed  →  WP_END'),
        ("p2", ARM,     TAKEOFF, "signal", "validated: 0 &lt; alt ≤ 50 m  →  ACK{uploaded}  →  CONFIRM  →  ARMED"),
        ("p3", TAKEOFF, PATROL,  "ink",    "AUTO.TAKEOFF  →  first waypoint altitude"),
        ("p4", PATROL,  DEV_IN,  "ink",    "AUTO.MISSION  ·  flying the circuit"),
        ("p4b", DEV_IN, DEV_OUT, "signal", "OAK-D depth  →  obstacle ahead  →  deviating "
                                           "·  Phase 6, not built"),
        ("p4c", DEV_OUT, RTL,    "ink",    "clear  ·  back on the uploaded route"),
        ("p5", RTL,     DONE,    "ink",    "RTL  ·  the mission's own last item"),
        ("p6", DONE,    REST,    "ink",    "landed  ·  disarmed  ·  DONE{result}"),
        ("p7", REST,    100,     "muted",  "Target system — Phase 5 in docs/ROADMAP.md · upload, gate and RTL "
                                           "bench-tested; GPS not yet fitted"),
    ]
    cap_el = "\n".join(
        f'    <text id="{i}" x="56" y="398" fill="{t[c]}" font-family="{MONO}" '
        f'font-size="12.5" letter-spacing="1">{s}</text>' for i, _, _, c, s in caps)
    cap_css = "\n".join(f"    #{i} {{ animation: k{i} {CYCLE} steps(1,end) infinite }}"
                        for i, _, _, _, _ in caps)
    cap_kf = "\n".join(
        (f"    @keyframes k{i} {{ 0%,{b-0.1:g}% {{opacity:1}} {b:g}%,100% {{opacity:0}} }}" if a == 0 else
         f"    @keyframes k{i} {{ 0%,{a-0.1:g}% {{opacity:0}} {a:g}%,100% {{opacity:1}} }}" if b >= 100 else
         f"    @keyframes k{i} {{ 0%,{a-0.1:g}% {{opacity:0}} {a:g}%,{b-0.1:g}% {{opacity:1}} "
         f"{b:g}%,100% {{opacity:0}} }}")
        for i, a, b, _, _ in caps)

    ox, oy, ow, oh = OBST
    hatch = "".join(
        f'<path d="M{ox + k*13} {oy+oh}L{ox + k*13 + oh} {oy}" stroke="{t["muted"]}" '
        f'stroke-width="1" opacity=".55"/>' for k in range(-4, 7))
    obstacle = f"""<g>
    <defs><clipPath id="oclip"><rect x="{ox}" y="{oy}" width="{ow}" height="{oh}"/></clipPath></defs>
    <g clip-path="url(#oclip)">{hatch}</g>
    <rect x="{ox}" y="{oy}" width="{ow}" height="{oh}" fill="none"
      stroke="{t['ink']}" stroke-width="1.6"/>
    <text x="{ox + ow/2}" y="{oy + oh + 36}" fill="{t['muted']}" font-family="{MONO}"
      font-size="9.5" text-anchor="middle" letter-spacing="1">OBSTACLE</text>
    <ellipse id="obstWarn" cx="{ox + ow/2}" cy="{oy + oh/2}" rx="{ow/2 + 22}" ry="{oh/2 + 22}"
      fill="none" stroke="{t['signal']}" stroke-width="1.3" stroke-dasharray="4 4"/>
  </g>"""
    grid = "".join(f'<path d="M{x} 74V356" stroke="{t["grid"]}" stroke-width="1"/>'
                   for x in range(96, 940, 48))
    grid += "".join(f'<path d="M56 {y}H932" stroke="{t["grid"]}" stroke-width="1"/>'
                    for y in range(84, 357, 48))

    wps = ""
    for i, (x, y) in enumerate(WPS):
        wps += f"""
    <g>
      <circle cx="{x}" cy="{y}" r="11" fill="{t['panel']}" stroke="{t['muted']}" stroke-width="1.6"/>
      <circle id="wpOn{i}" cx="{x}" cy="{y}" r="11" fill="{t['signal']}"/>
      <text x="{x}" y="{y+4}" fill="{t['muted']}" font-family="{MONO}" font-size="11"
        text-anchor="middle">{i+1}</text>
      <text id="wpNum{i}" x="{x}" y="{y+4}" fill="{t['panel']}" font-family="{MONO}"
        font-size="11" text-anchor="middle">{i+1}</text>
    </g>"""

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     role="img" aria-label="Venator patrol: four coordinates uploaded over LoRa, validated, armed, flown as a circuit, then RTL home">
  <title>Venator — fly to these coordinates (target system)</title>
  <style>
    #drone {{ transform-box: view-box; transform-origin: 0 0;
             transform: translate({WPS[1][0]}px, {WPS[1][1]}px);
             animation: fly {CYCLE} linear infinite }}
    @keyframes fly {{
      0%,{TAKEOFF}% {{ transform: translate({HOME[0]}px, {HOME[1]}px) }}
      {PATROL}%     {{ transform: translate({HOME[0]}px, {HOME[1]}px) }}
{legs_kf}
      {DONE}%,100%  {{ transform: translate({HOME[0]}px, {HOME[1]}px) }}
    }}
    #rotor circle {{ transform-box: fill-box; transform-origin: center;
                    animation: spin .3s linear infinite }}
    @keyframes spin {{ 0%,100% {{ transform: scaleX(1) }} 50% {{ transform: scaleX(.3) }} }}

    /* The flown line grows under the aircraft: same schedule, dashoffset to 0. */
    #flownA {{ animation: drawA {CYCLE} linear infinite }}
    @keyframes drawA {{ 0%,{PATROL}% {{ stroke-dashoffset: {SEG_A:.1f} }}
                       {DEV_IN:g}%,100% {{ stroke-dashoffset: 0 }} }}
    #flownB {{ animation: drawB {CYCLE} linear infinite }}
    @keyframes drawB {{ 0%,{DEV_OUT:g}% {{ stroke-dashoffset: {SEG_B:.1f} }}
                       {RTL}%,100% {{ stroke-dashoffset: 0 }} }}
    /* The deviation is dashed to mark it as the one thing here that is not
       built, so it reveals rather than grows — dasharray is already spent. */
    #dev, #devChip, #obstWarn {{ opacity:0; animation: kDev {CYCLE} steps(1,end) infinite }}
    @keyframes kDev {{ 0%,{DEV_IN-0.1:g}% {{opacity:0}} {DEV_IN:g}%,100% {{opacity:1}} }}
    #rtl {{ stroke-dasharray: {RTL_LEN:.1f}; stroke-dashoffset: {RTL_LEN:.1f};
           animation: drawR {CYCLE} linear infinite }}
    @keyframes drawR {{
      0%,{RTL}%   {{ stroke-dashoffset: {RTL_LEN:.1f} }}
      {DONE}%     {{ stroke-dashoffset: 0 }}
      100%        {{ stroke-dashoffset: 0 }}
    }}
    #plan  {{ opacity:0; animation: kPlan {CYCLE} steps(1,end) infinite }}
    #armed {{ opacity:0; animation: kArm {CYCLE} steps(1,end) infinite }}
    #ping  {{ opacity:0; animation: kPing {CYCLE} steps(1,end) infinite }}
    #ping circle {{ transform-box: fill-box; transform-origin: center;
                   animation: ping 1.3s linear infinite }}
    #ping circle:nth-child(2) {{ animation-delay: .43s }}
    #ping circle:nth-child(3) {{ animation-delay: .86s }}
    @keyframes ping {{ 0% {{ transform: scale(1); opacity:.8 }}
                      100% {{ transform: scale(6.5); opacity:0 }} }}
    @keyframes kPlan {{ 0%,{PLOT+4:g}% {{opacity:0}} {PLOT+4.1:g}%,100% {{opacity:1}} }}
    @keyframes kArm  {{ 0%,{ARM+4:g}% {{opacity:0}} {ARM+4.1:g}%,{DONE:g}% {{opacity:1}}
                       {DONE+0.1:g}%,100% {{opacity:0}} }}
    @keyframes kPing {{ 0%,{UPLOAD-0.1:g}% {{opacity:0}} {UPLOAD:g}%,{ARM+4:g}% {{opacity:1}}
                       {ARM+4.1:g}%,100% {{opacity:0}} }}
{wp_css}
{wp_frames}
    #ticker text {{ opacity:0 }}
    #p7 {{ opacity:1 }}
{cap_css}
{cap_kf}
    @media (prefers-reduced-motion: reduce) {{
      #drone, #rotor circle, #ping, #ping circle {{ animation: none }}
      #ping {{ display: none }}
      #flownA, #flownB, #rtl {{ animation: none; stroke-dashoffset: 0 }}
      #dev, #devChip, #obstWarn {{ opacity: 1; animation: none }}
      #plan, #armed {{ opacity: 1; animation: none }}
      [id^="wpOn"], [id^="wpNum"] {{ opacity: 1; animation: none }}
      #ticker text {{ animation: none; opacity: 0 }}
      #p7 {{ opacity: 1 }}
    }}
  </style>
  <rect width="{W}" height="{H}" fill="{t['bg']}"/>
  {grid}
  <rect x="56" y="74" width="876" height="282" fill="none" stroke="{t['line']}" stroke-width="1.5"/>

  <text x="56" y="44" fill="{t['muted']}" font-family="{GROT}" font-size="11"
    font-weight="600" letter-spacing="3.4">FLY TO THESE COORDINATES</text>
  <text x="56" y="64" fill="{t['ink']}" font-family="{GROT}" font-size="15" font-weight="600">
    Phase 5 — upload a route over LoRa, fly the patrol, come home</text>

  <path id="plan" d="{poly(PLAN)}" fill="none" stroke="{t['muted']}"
    stroke-width="1.2" stroke-dasharray="5 5"/>
  {obstacle}
  {grow('flownA', PATH[0:3], 0, 0, t['signal'])}
  {grow('dev', PATH[2:6], 0, 0, t['signal'], dash_reveal=True)}
  {grow('flownB', PATH[5:7], 0, 0, t['signal'])}
  <path id="rtl" d="{poly([WPS[-1], HOME])}" fill="none" stroke="{t['signal']}"
    stroke-width="2.2" stroke-dasharray="{RTL_LEN:.1f}"/>
{wps}

  <g transform="translate({HOME[0]},{HOME[1]})">
    <rect x="-13" y="-13" width="26" height="26" fill="none" stroke="{t['muted']}" stroke-width="1.6"/>
    <text x="0" y="30" fill="{t['muted']}" font-family="{MONO}" font-size="10"
      text-anchor="middle" letter-spacing="1">HOME</text>
    <g id="ping" fill="none" stroke="{t['signal']}" stroke-width="1.6">
      <circle r="7"/><circle r="7"/><circle r="7"/></g>
  </g>

  <g id="drone">
    <g id="rotor" fill="{t['muted']}">
      <circle cx="-17" cy="-10" r="7"/><circle cx="17" cy="-10" r="7"/>
      <circle cx="-17" cy="10" r="7"/><circle cx="17" cy="10" r="7"/>
      <circle cx="0" cy="-15" r="7"/><circle cx="0" cy="15" r="7"/>
    </g>
    <path d="M-17-10L17 10M17-10L-17 10M0-15V15" stroke="{t['ink']}" stroke-width="2"/>
    <circle r="7.5" fill="{t['ink']}"/>
  </g>

  <g id="devChip" transform="translate({OBST[0] + OBST[2]/2},{OBST[1] - 46})">
    <rect x="-96" y="-15" width="192" height="22" rx="2" fill="{t['bg']}"
      stroke="{t['signal']}" stroke-width="1.2" stroke-dasharray="4 3"/>
    <text x="0" y="1" fill="{t['signal']}" font-family="{MONO}" font-size="9.5"
      text-anchor="middle" letter-spacing="0.6">DEVIATE · Phase 6, not built</text>
  </g>

  <g id="armed" transform="translate(800,60)">
    <circle r="4" cx="0" cy="-4" fill="{t['signal']}"/>
    <text x="12" y="0" fill="{t['signal']}" font-family="{MONO}" font-size="11"
      letter-spacing="1.6">ARMED</text>
  </g>

  <g id="ticker">
{cap_el}
  </g>
</svg>
"""


for name in ("light", "dark"):
    p = ROOT / f"patrol-{name}.svg"
    p.write_text(build(name))
    print(f"{p.name}: {p.stat().st_size} bytes")
print("legs:", [round(x) for x in LEGS], "total", round(TOTAL),
      "arrive at %:", [round(a, 1) for a in ARRIVE])
