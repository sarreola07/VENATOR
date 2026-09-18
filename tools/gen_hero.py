#!/usr/bin/env python3
"""README hero — the system self-test. Ten seconds, cold read.

A console printing its own bring-up: radio, link, flight controller, camera,
compute, C2. Every line is a real part of this repo, and the GPS line is
deliberately NOT an OK — Phase 5 still lists the M8N as unfitted, so a hero that
ticked everything green would be the one dishonest thing in the project.

Dark in both colour schemes, like cta-*.svg: a terminal is dark, and the neon
needs something to burn against.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets" / "brand"
W, H = 1000, 384
CYCLE = "10s"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
GROT = "Helvetica Neue,Helvetica,Arial,sans-serif"
SIG, HOT = "#E05316", "#FF7A3D"
TEXT, MUTED = "#F2F1EE", "#8A8781"

THEMES = {"light": "#0A0A0A", "dark": "#131314"}

# label, detail, state — order is the order they print
LINES = [
    ("RADIO",   "915 MHz · SF7 · syncword 0x12", "OK"),
    ("LINK",    "stick A ↔ stick B",         "OK"),
    ("FC",      "Pixhawk 2.4.8 · PX4 v1.13.3",   "OK"),
    ("CAMERA",  "OAK-D · spatial depth",         "OK"),
    ("COMPUTE", "Jetson Orin Nano",              "OK"),
    ("C2",      "c2_server.py · props OFF",      "OK"),
    ("GPS",     "M8N · not fitted",              "--"),
]

Y0, DY = 112, 31
T_FIRST, T_STEP, T_OK = 0.5, 0.62, 0.34      # seconds
T_READY, T_LIFT = 5.6, 5.9

pc = lambda sec: round(sec / 10 * 100, 2)    # seconds -> % of cycle


def win(name, a, b=None):
    """steps(1,end) reveal at a%, optionally hidden again at b%."""
    if b is None:
        return f"    @keyframes {name} {{ 0%,{a-0.01:g}% {{opacity:0}} {a:g}%,100% {{opacity:1}} }}"
    return (f"    @keyframes {name} {{ 0%,{a-0.01:g}% {{opacity:0}} {a:g}%,{b-0.01:g}% "
            f"{{opacity:1}} {b:g}%,100% {{opacity:0}} }}")


def build(theme):
    panel = THEMES[theme]
    scan = "".join(f'<path d="M0 {y}H{W}" stroke="{TEXT}" stroke-width="1" opacity=".035"/>'
                   for y in range(3, H, 4))

    rows, css, kf = [], [], []
    for i, (lab, det, state) in enumerate(LINES):
        y = Y0 + i * DY
        ok = state == "OK"
        c = SIG if ok else MUTED
        rows.append(f"""  <g id="ln{i}" opacity="0">
    <text x="44" y="{y}" fill="{SIG}" font-family="{MONO}" font-size="15">&gt;</text>
    <text x="72" y="{y}" fill="{TEXT}" font-family="{MONO}" font-size="15"
      letter-spacing="1.2">{lab}</text>
    <text x="196" y="{y}" fill="{MUTED}" font-family="{MONO}" font-size="15">{det}</text>
    <g id="ok{i}" opacity="0">
      <text x="600" y="{y}" fill="{c}" font-family="{MONO}" font-size="15"
        letter-spacing="1.4">[ {state} ]</text>
    </g>
  </g>""")
        t = T_FIRST + i * T_STEP
        css.append(f"    #ln{i} {{ animation: r{i} {CYCLE} steps(1,end) infinite }}")
        css.append(f"    #ok{i} {{ animation: o{i} {CYCLE} steps(1,end) infinite }}")
        kf.append(win(f"r{i}", pc(t)))
        kf.append(win(f"o{i}", pc(t + T_OK)))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     role="img" aria-label="Venator system self-test: radio, link, flight controller, camera, compute and C2 all OK; GPS not fitted; then ready and the aircraft lifts">
  <title>Venator — system self-test</title>
  <style>
    #cur {{ animation: blink 1.05s steps(1,end) infinite }}
    @keyframes blink {{ 0%,55% {{opacity:1}} 56%,100% {{opacity:0}} }}
    #sweep {{ transform-box: view-box; transform-origin: 0 0;
             animation: sweep {CYCLE} cubic-bezier(.4,0,.2,1) infinite }}
    @keyframes sweep {{ 0% {{transform:translateX(-40px); opacity:0}}
      4% {{opacity:.9}} 46% {{opacity:.9}} 54%,100% {{transform:translateX({W+40}px); opacity:0}} }}

    #ready {{ animation: rdy {CYCLE} steps(1,end) infinite }}
{win('rdy', pc(T_READY))}
    #readyGlow {{ animation: pulse 1.4s ease-in-out infinite,
                            rdy {CYCLE} steps(1,end) infinite }}
    @keyframes pulse {{ 0%,100% {{opacity:.9}} 50% {{opacity:.35}} }}

    #craft {{ transform-box: view-box; transform-origin: 0 0;
             transform: translate(858px, 196px);
             animation: lift {CYCLE} cubic-bezier(.3,0,.3,1) infinite }}
    @keyframes lift {{
      0%,{pc(T_LIFT):g}%  {{ transform: translate(858px, 300px) }}
      {pc(T_LIFT + 1.9):g}%, 100% {{ transform: translate(858px, 196px) }}
    }}
    #rotorL, #rotorR {{ transform-box: fill-box; transform-origin: center;
                       animation: spin .3s linear infinite }}
    @keyframes spin {{ 0%,100% {{transform:scaleX(1)}} 50% {{transform:scaleX(.28)}} }}
{chr(10).join(css)}
{chr(10).join(kf)}

    @media (prefers-reduced-motion: reduce) {{
      #sweep {{ display: none }}
      #cur, #rotorL, #rotorR, #readyGlow {{ animation: none }}
      #craft {{ animation: none }}
      [id^="ln"], [id^="ok"], #ready, #readyGlow {{ animation: none; opacity: 1 }}
    }}
  </style>
  <defs>
    <clipPath id="pc"><rect width="{W}" height="{H}"/></clipPath>
    <filter id="glow" x="-40%" y="-80%" width="180%" height="260%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="soft"><feGaussianBlur stdDeviation="2"/></filter>
  </defs>

  <rect width="{W}" height="{H}" fill="{panel}"/>
  <g clip-path="url(#pc)">
    {scan}
    <g id="sweep">
      <rect width="3" height="{H}" fill="{HOT}" filter="url(#soft)" opacity=".85"/>
      <rect width="1.3" height="{H}" fill="#FFFFFF" opacity=".8"/>
    </g>
  </g>

  <text x="44" y="52" fill="{MUTED}" font-family="{MONO}" font-size="13"
    letter-spacing="3.4">VENATOR // SYSTEM SELF-TEST</text>
  <rect id="cur" x="334" y="40" width="9" height="15" fill="{HOT}"/>
  <path d="M44 70H{W-44}" stroke="{SIG}" stroke-width="1.5" opacity=".5"/>

{chr(10).join(rows)}

  <g id="ready">
    <text id="readyGlow" x="44" y="352" fill="{HOT}" font-family="{GROT}" font-size="24"
      font-weight="700" letter-spacing="4" filter="url(#glow)">READY</text>
    <text x="44" y="352" fill="{TEXT}" font-family="{GROT}" font-size="24"
      font-weight="700" letter-spacing="4">READY</text>
    <text x="172" y="352" fill="{MUTED}" font-family="{MONO}" font-size="14">
      awaiting a command over the radio</text>
  </g>

  <g id="craft">
    <path d="M-30 -3h60" stroke="{TEXT}" stroke-width="3"/>
    <path d="M-30 -3l-5 -9M30 -3l5 -9" stroke="{TEXT}" stroke-width="2.5"/>
    <rect x="-14" y="-7" width="28" height="14" rx="2" fill="{TEXT}"/>
    <circle cx="0" cy="11" r="5" fill="{TEXT}"/>
    <circle cx="0" cy="11" r="2" fill="{panel}"/>
    <ellipse id="rotorL" cx="-35" cy="-13" rx="17" ry="2.4" fill="{SIG}"/>
    <ellipse id="rotorR" cx="35" cy="-13" rx="17" ry="2.4" fill="{SIG}"/>
  </g>
  <path d="M818 316h80" stroke="{MUTED}" stroke-width="2.5"/>
</svg>
"""


for name in THEMES:
    p = ROOT / f"hero-{name}.svg"
    p.write_text(build(name))
    print(f"{p.name}: {p.stat().st_size} bytes")
