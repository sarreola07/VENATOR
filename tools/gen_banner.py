#!/usr/bin/env python3
"""README banner — the aircraft, named. Ten seconds, cold read.

The README used to open on the self-test, which is a true picture of the
software and a poor picture of the product: someone landing on the repository
met a terminal readout before they met the machine. This draws the machine.

A plan view of the X500 V2, to its real dimensions, and then the five things
bolted to it, each named as it arrives. The self-test still runs underneath it
in the README, where listing what is fitted and what is not is exactly its job.

Motion here obeys the rule in docs/BRAND.md: it reports, or it does not happen.
The airframe draws because that is the airframe; each label lands because that
part is on the aircraft. Nothing spins to fill the space. The accent appears
once, on the radio, because the radio is the live link.

Dark in both colour schemes, like hero-*.svg: this is a console view of a black
airframe, and it needs something to sit against.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets" / "brand"
W, H = 1000, 380
CYCLE = "10s"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
GROT = "Helvetica Neue,Helvetica,Arial,sans-serif"
SIG = "#E05316"
TEXT, MUTED, LINE = "#F2F1EE", "#8A8781", "#3A3A36"
DISC = "#55554F"          # the swept circle, a shade up from the leader lines

THEMES = {"light": "#0A0A0A", "dark": "#131314"}

# Millimetres, straight off the CAD, so the drawing is the aircraft and not an
# impression of it. Motors sit at +/-178 mm on both axes: a 503 mm diagonal,
# which is the 500 mm wheelbase the documentation claims.
MOTOR_XY = 178.0
PROP_R = 127.0            # 10 inch propeller
PLATE = 144.0             # body plates, 144 x 144
MOTOR_R = 14.0
GPS_X, GPS_R = 99.0, 20.0
SKID_SPAN, SKID_Y = 210.0, 120.0

# Scaled to sit inside the band between the rule under the header and the spec
# line at the foot: 610 mm of aircraft into 268 px, centred on that gap.
S = 0.44                  # px per mm
CX, CY = 500.0, 205.0

def mm(v):
    return v * S

def px(x, y):
    """Aircraft millimetres -> banner pixels. +X is the nose, drawn to the right."""
    return CX + x * S, CY - y * S

# label, anchor on the aircraft (mm), which side the callout sits, label y (px)
PARTS = [
    ("PIXHAWK 6X",                (  26,  30), "right", 120),
    ("HOLYBRO M10",               (GPS_X,  0), "right", 236),
    ("JETSON ORIN NANO",          ( -24, -26), "left",  214),
    ("OAK-D PRO",                 ( -58,  34), "left",  116),
    ("HELTEC WIRELESS STICK V3",  ( -20, -62), "left",  296),
]

T_FRAME = 2.1             # airframe finishes drawing
T_FIRST, T_STEP = 2.5, 0.52
pc = lambda sec: round(sec / 10 * 100, 3)


def build(theme):
    panel = THEMES[theme]
    parts, css, kf = [], [], []

    # ---- airframe, drawn once ------------------------------------------
    arms = []
    for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
        x0, y0 = px(sx * 26, sy * 26)
        x1, y1 = px(sx * MOTOR_XY, sy * MOTOR_XY)
        arms.append(f'<path d="M{x0:.1f} {y0:.1f}L{x1:.1f} {y1:.1f}"/>')
    px0, py0 = px(-PLATE / 2, PLATE / 2)
    plate = (f'<rect x="{px0:.1f}" y="{py0:.1f}" '
             f'width="{mm(PLATE):.1f}" height="{mm(PLATE):.1f}"/>')
    sk = []
    for sy in (1, -1):
        a = px(-SKID_SPAN / 2, sy * SKID_Y)
        b = px(SKID_SPAN / 2, sy * SKID_Y)
        sk.append(f'<path d="M{a[0]:.1f} {a[1]:.1f}L{b[0]:.1f} {b[1]:.1f}"/>')

    parts.append(f"""  <g id="frame" fill="none" stroke="{TEXT}" stroke-width="1.5" opacity=".9">
    {''.join(arms)}
    {plate}
    {''.join(sk)}
  </g>""")

    # motors and blades: outline only, no fill, so it reads as a drawing
    rotors = []
    for i, (sx, sy) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
        cx, cy = px(sx * MOTOR_XY, sy * MOTOR_XY)
        ang = 32 + i * 24
        rotors.append(
            f'  <g id="rot{i}">'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{mm(PROP_R):.1f}" '
            f'fill="none" stroke="{DISC}" stroke-width="1.1" stroke-dasharray="3 4"/>'
            f'<g transform="rotate({ang} {cx:.1f} {cy:.1f})">'
            f'<path d="M{cx - mm(PROP_R):.1f} {cy:.1f}L{cx + mm(PROP_R):.1f} {cy:.1f}" '
            f'stroke="{TEXT}" stroke-width="2.6" opacity=".7"/></g>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{mm(MOTOR_R):.1f}" '
            f'fill="{panel}" stroke="{TEXT}" stroke-width="1.5"/></g>')
    parts += rotors

    # ---- the five parts, named as they arrive --------------------------
    for i, (label, (ax, ay), side, ly) in enumerate(PARTS):
        axp, ayp = px(ax, ay)
        if side == "right":
            lx, bend, anchor = 672.0, 648.0, "start"
            tick = lx - 12
        else:
            lx, bend, anchor = 328.0, 352.0, "end"
            tick = lx + 12
        accent = label.startswith("HELTEC")
        col = SIG if accent else TEXT
        parts.append(
            f"""  <g id="cal{i}">
    <path d="M{tick:.1f} {ly}L{bend:.1f} {ly}L{axp:.1f} {ayp:.1f}"
      fill="none" stroke="{LINE}" stroke-width="1"/>
    <circle cx="{axp:.1f}" cy="{ayp:.1f}" r="2.6" fill="{col}"/>
    <text x="{lx:.0f}" y="{ly + 4}" fill="{col}" font-family="{MONO}"
      font-size="12.5" letter-spacing="1.6" text-anchor="{anchor}">{label}</text>
  </g>""")
        t = T_FIRST + i * T_STEP
        css.append(f"    #cal{i} {{ animation: c{i} {CYCLE} steps(1,end) infinite }}")
        kf.append(f"    @keyframes c{i} {{ 0%,{pc(t) - 0.01:g}% {{opacity:0}} "
                  f"{pc(t):g}%,100% {{opacity:1}} }}")

    for i in range(4):
        t = 1.1 + i * 0.16
        css.append(f"    #rot{i} {{ animation: r{i} {CYCLE} steps(1,end) infinite }}")
        kf.append(f"    @keyframes r{i} {{ 0%,{pc(t) - 0.01:g}% {{opacity:0}} "
                  f"{pc(t):g}%,100% {{opacity:1}} }}")

    css_block = "\n".join(css)
    kf_block = "\n".join(kf)
    body = "\n".join(parts)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     role="img" aria-label="Plan view of the Venator aircraft, a Holybro X500 V2 quadcopter, drawn to scale and labelled: Pixhawk 6X, Holybro M10, Jetson Orin Nano, OAK-D Pro, and the Heltec Wireless Stick V3 radio">
  <title>Venator — the aircraft, named</title>
  <style>
    /* The settled frame is the DEFAULT: the airframe is drawn, the rotors and
       every label are on. Animation only takes things away and puts them back,
       so a renderer that ignores CSS -- GitHub's proxy, an SVG-to-PNG step, a
       reader with reduced motion -- gets the complete labelled drawing rather
       than an empty box. docs/BRAND.md: the static artwork underneath is what
       makes the motion safe to drop. */
    #frame {{ stroke-dasharray: 2400; stroke-dashoffset: 0;
             animation: draw {CYCLE} cubic-bezier(.4,0,.2,1) infinite }}
    @keyframes draw {{ 0% {{stroke-dashoffset:2400}}
      {pc(T_FRAME):g}%,100% {{stroke-dashoffset:0}} }}
{css_block}
{kf_block}
    @media (prefers-reduced-motion: reduce) {{
      #frame {{ animation: none; stroke-dashoffset: 0 }}
      [id^="cal"], [id^="rot"] {{ animation: none; opacity: 1 }}
    }}
  </style>

  <rect width="{W}" height="{H}" fill="{panel}"/>
  <text x="44" y="46" fill="{MUTED}" font-family="{MONO}" font-size="12"
    letter-spacing="3.2">VENATOR // THE AIRCRAFT</text>
  <path d="M44 62H{W - 44}" stroke="{SIG}" stroke-width="1.5" opacity=".45"/>

{body}

  <text x="44" y="{H - 28}" fill="{MUTED}" font-family="{MONO}" font-size="11.5"
    letter-spacing="1.5">HOLYBRO X500 V2 &#183; 500 MM WHEELBASE &#183; 915 MHZ LORA COMMAND LINK</text>
  <text x="{W - 44}" y="{H - 28}" fill="{MUTED}" font-family="{GROT}" font-size="11.5"
    letter-spacing="1.5" text-anchor="end">DRAWN TO SCALE FROM THE CAD</text>
</svg>
"""


for name in THEMES:
    p = ROOT / f"banner-{name}.svg"
    # encoding and newline are explicit: the other generators inherit the
    # platform default, which is cp1252 on Windows and truncates on the first
    # non-ASCII character.
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(build(name))
    print(f"{p.name}: {p.stat().st_size} bytes")
