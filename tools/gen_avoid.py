#!/usr/bin/env python3
"""ROADMAP hero — forward obstacle avoidance. Phase 6, not started.

A tactical zoom rather than the patrol's route map, so it shows the mechanism
instead of repeating the outcome: the OAK-D's forward depth fan finds a wall,
the distance closes, PX4 brakes at CP_DIST, the aircraft routes around and
rejoins the line.

Nothing here is implemented. run_mission2 steers toward a person and otherwise
hovers; the only rangefinder discussed in the repo is a downward lidar for
altitude. The parts that ARE real are the ingredients: camera_publisher.py runs
a MobileNetSpatialDetectionNetwork on stereo depth, and PX4 1.13 brakes on
OBSTACLE_DISTANCE via CP_DIST. The resting caption says exactly that.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets" / "brand"
W, H = 1000, 380
CYCLE = "14s"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
GROT = "Helvetica Neue,Helvetica,Arial,sans-serif"

THEMES = {
    "light": dict(bg="#F2F1EE", panel="#FFFFFF", line="#DAD8D3", muted="#6E6B66",
                  ink="#0A0A0A", signal="#E05316", grid="#E6E4E0"),
    "dark":  dict(bg="#0A0A0A", panel="#131314", line="#2A2A27", muted="#8A8781",
                  ink="#F2F1EE", signal="#E05316", grid="#151516"),
}

LANE_Y = 208
OBST = (500, 168, 62, 150)          # x, y, w, h — a wall across the lane
CRUISE, DETECT, BRAKE, DEVIATE, REJOIN, REST = 0, 14, 30, 40, 64, 79

# waypoints of the flown track (x, y) keyed by % of cycle
TRACK = [(0, 120, LANE_Y), (DETECT, 300, LANE_Y), (BRAKE, 430, LANE_Y),
         (48, 478, 142), (58, 610, 126), (REJOIN, 700, 166), (REST, 880, LANE_Y),
         (100, 880, LANE_Y)]

READOUT = [   # (start%, text) — the closing distance, then the brake
    (CRUISE, "OBST  --"), (DETECT, "OBST  8.0 m"), (20, "OBST  6.4 m"),
    (25, "OBST  5.1 m"), (BRAKE, "OBST  4.0 m"), (DEVIATE, "BRAKE"),
    (48, "DEVIATE"), (REJOIN, "CLEAR"), (REST, "OBST  --"),
]

CAPS = [
    ("a0", CRUISE,  DETECT,  "ink",    "AUTO.MISSION  ·  cruising the leg"),
    ("a1", DETECT,  BRAKE,   "signal", "OAK-D stereo depth  →  return ahead, closing"),
    ("a2", BRAKE,   DEVIATE, "signal", "OBSTACLE_DISTANCE  →  PX4 brakes at CP_DIST"),
    ("a3", DEVIATE, REJOIN,  "signal", "deviating  ·  the planned line is not flyable"),
    ("a4", REJOIN,  REST,    "ink",    "clear  ·  rejoining the route"),
    ("a5", REST,    100,     "muted",  "Phase 6 — not started. The depth camera and the PX4 "
                                       "side both exist; the link between them does not."),
]


def win(name, a, b=None):
    if a == 0 and b is not None:
        return f"    @keyframes {name} {{ 0%,{b-0.01:g}% {{opacity:1}} {b:g}%,100% {{opacity:0}} }}"
    if b is None or b >= 100:
        return f"    @keyframes {name} {{ 0%,{a-0.01:g}% {{opacity:0}} {a:g}%,100% {{opacity:1}} }}"
    return (f"    @keyframes {name} {{ 0%,{a-0.01:g}% {{opacity:0}} {a:g}%,{b-0.01:g}% "
            f"{{opacity:1}} {b:g}%,100% {{opacity:0}} }}")


def build(theme):
    t = THEMES[theme]
    ox, oy, ow, oh = OBST

    grid = "".join(f'<path d="M{x} 84V330" stroke="{t["grid"]}" stroke-width="1"/>'
                   for x in range(104, 940, 48))
    grid += "".join(f'<path d="M56 {y}H944" stroke="{t["grid"]}" stroke-width="1"/>'
                    for y in range(96, 331, 48))
    hatch = "".join(
        f'<path d="M{ox + k*13} {oy+oh}L{ox + k*13 + oh} {oy}" stroke="{t["muted"]}" '
        f'stroke-width="1" opacity=".5"/>' for k in range(-12, 8))

    flight = "\n".join(f"      {p:g}% {{ transform: translate({x}px, {y}px) }}"
                       for p, x, y in TRACK)

    # depth returns on the wall's near face
    hits = "".join(f'<path d="M{ox-7} {oy+14+j*19}h9" stroke="{t["signal"]}" '
                   f'stroke-width="2.4"/>' for j in range(7))

    ro_el, ro_css, ro_kf = [], [], []
    for i, (a, txt) in enumerate(READOUT):
        b = READOUT[i + 1][0] if i + 1 < len(READOUT) else 100
        col = t["signal"] if txt in ("BRAKE", "DEVIATE") else (
            t["muted"] if "--" in txt else t["ink"])
        ro_el.append(f'<text id="ro{i}" x="0" y="0" fill="{col}" font-family="{MONO}" '
                     f'font-size="12.5" text-anchor="middle" letter-spacing="1">{txt}</text>')
        ro_css.append(f"    #ro{i} {{ animation: q{i} {CYCLE} steps(1,end) infinite }}")
        ro_kf.append(win(f"q{i}", a, b))

    cap_el = "\n".join(
        f'    <text id="{i}" x="56" y="358" fill="{t[c]}" font-family="{MONO}" '
        f'font-size="13" letter-spacing="0.8">{s}</text>' for i, _, _, c, s in CAPS)
    cap_css = "\n".join(f"    #{i} {{ animation: k{i} {CYCLE} steps(1,end) infinite }}"
                        for i, *_ in CAPS)
    cap_kf = "\n".join(win(f"k{i}", a, b) for i, a, b, _, _ in CAPS)

    rings = "".join(
        f'<circle r="{r}" fill="none" stroke="{t["signal"]}" stroke-width="1" '
        f'opacity=".28" stroke-dasharray="3 5"/>' for r in (50, 100, 150, 200))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     role="img" aria-label="Forward obstacle avoidance, not built: the depth camera finds a wall, PX4 brakes at CP_DIST, the aircraft routes around and rejoins">
  <title>Venator — forward obstacle avoidance (Phase 6, not started)</title>
  <style>
    #craft {{ transform-box: view-box; transform-origin: 0 0;
             transform: translate(478px, 142px);
             animation: fly {CYCLE} linear infinite, fade {CYCLE} linear infinite }}
    @keyframes fly {{
{flight}
    }}
    @keyframes fade {{ 0% {{opacity:0}} 2.5% {{opacity:1}} 96% {{opacity:1}} 100% {{opacity:0}} }}
    #rotor circle {{ transform-box: fill-box; transform-origin: center;
                    animation: spin .3s linear infinite }}
    @keyframes spin {{ 0%,100% {{transform:scaleX(1)}} 50% {{transform:scaleX(.3)}} }}

    #fan {{ animation: fan 2.2s ease-in-out infinite }}
    @keyframes fan {{ 0%,100% {{opacity:.20}} 50% {{opacity:.42}} }}

    #cpring {{ transform-box: fill-box; transform-origin: center;
              animation: kCp {CYCLE} steps(1,end) infinite }}
{win('kCp', BRAKE, REJOIN)}
    #hits {{ animation: kHit {CYCLE} steps(1,end) infinite }}
{win('kHit', DETECT, REJOIN)}
    #devpath {{ animation: kDev {CYCLE} steps(1,end) infinite }}
{win('kDev', DEVIATE, 100)}
{chr(10).join(ro_css)}
{chr(10).join(ro_kf)}
    #ticker text {{ opacity: 0 }}
    #a5 {{ opacity: 1 }}
{cap_css}
{cap_kf}
    @media (prefers-reduced-motion: reduce) {{
      #craft, #rotor circle, #fan {{ animation: none }}
      #craft {{ opacity: 1 }}
      #fan {{ opacity: .3 }}
      #cpring, #hits, #devpath {{ opacity: 1; animation: none }}
      [id^="ro"] {{ animation: none; opacity: 0 }}
      #ro6 {{ opacity: 1 }}
      #ticker text {{ animation: none; opacity: 0 }}
      #a5 {{ opacity: 1 }}
    }}
  </style>
  <rect width="{W}" height="{H}" fill="{t['bg']}"/>
  {grid}
  <rect x="56" y="84" width="888" height="246" fill="none" stroke="{t['line']}" stroke-width="1.5"/>

  <text x="56" y="44" fill="{t['muted']}" font-family="{GROT}" font-size="11"
    font-weight="600" letter-spacing="3.4">FORWARD OBSTACLE AVOIDANCE</text>
  <text x="56" y="64" fill="{t['ink']}" font-family="{GROT}" font-size="15" font-weight="600">
    Phase 6 — see it, brake, go around, rejoin</text>

  <path d="M120 {LANE_Y}H880" stroke="{t['muted']}" stroke-width="1.2" stroke-dasharray="5 5"/>
  <path id="devpath" d="M430 {LANE_Y}L478 142L610 126L700 166L880 {LANE_Y}" fill="none"
    stroke="{t['signal']}" stroke-width="2" stroke-dasharray="7 5" opacity="0"/>

  <g id="craft">
    <g id="fan" opacity=".2">
      <path d="M0 0 L205 -118 A205 205 0 0 1 205 118 Z" fill="{t['signal']}"/>
    </g>
    {rings}
    <circle id="cpring" r="100" fill="none" stroke="{t['signal']}" stroke-width="2" opacity="0"/>
    <g id="rotor" fill="{t['muted']}">
      <circle cx="-15" cy="-9" r="6"/><circle cx="15" cy="-9" r="6"/>
      <circle cx="-15" cy="9" r="6"/><circle cx="15" cy="9" r="6"/>
      <circle cx="0" cy="-13" r="6"/><circle cx="0" cy="13" r="6"/>
    </g>
    <path d="M-15-9L15 9M15-9L-15 9M0-13V13" stroke="{t['ink']}" stroke-width="2"/>
    <circle r="6.5" fill="{t['ink']}"/>
    <g transform="translate(0,-46)">{''.join(ro_el)}</g>
  </g>

  <g>
    <defs><clipPath id="oc"><rect x="{ox}" y="{oy}" width="{ow}" height="{oh}"/></clipPath></defs>
    <rect x="{ox}" y="{oy}" width="{ow}" height="{oh}" fill="{t['bg']}"/>
    <g clip-path="url(#oc)">{hatch}</g>
    <rect x="{ox}" y="{oy}" width="{ow}" height="{oh}" fill="none" stroke="{t['ink']}" stroke-width="1.6"/>
    <text x="{ox + ow/2}" y="{oy + oh + 20}" fill="{t['muted']}" font-family="{MONO}"
      font-size="10" text-anchor="middle" letter-spacing="1">OBSTACLE</text>
  </g>
  <g id="hits" opacity="0">{hits}</g>

  <g id="ticker">
{cap_el}
  </g>
</svg>
"""


for name in ("light", "dark"):
    p = ROOT / f"avoid-{name}.svg"
    p.write_text(build(name))
    print(f"{p.name}: {p.stat().st_size} bytes")
