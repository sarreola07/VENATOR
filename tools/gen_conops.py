#!/usr/bin/env python3
"""Venator concept of operations — the system as designed, end to end.

One 20s cycle walks Mission 2 from the roadmap: the operator selects it on a
laptop, the two-step arm gate clears, the aircraft takes off, the OAK-D acquires
a person, it follows at 3 m streaming telemetry home, the link drops, and the
RTL failsafe brings it back.

This is the TARGET system. The roadmap has missions 1 and 2 built and
bench-tested against mocks with outdoor flight still pending, so the resting
caption says exactly that rather than implying it flies today.

Motion is CSS rather than SMIL here on purpose: CSS animations can be switched
off by prefers-reduced-motion, and this piece is mostly movement, so there has
to be a way to stop it. The aircraft's base transform is the hover position, so
with animation off the scene reads as a still of the follow.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets" / "brand"
W, H = 1000, 400
GROUND_Y = 340
CYCLE = "20s"

THEMES = {
    "light": dict(bg="#F2F1EE", panel="#FFFFFF", line="#DAD8D3", muted="#6E6B66",
                  ink="#0A0A0A", signal="#E05316"),
    "dark":  dict(bg="#0A0A0A", panel="#131314", line="#2A2A27", muted="#8A8781",
                  ink="#F2F1EE", signal="#E05316"),
}

# Beat boundaries as percentages of the cycle.
B = dict(idle=0, cmd=6, confirm=14, takeoff=21, detect=31, follow=40,
         linkloss=58, rtl=68, land=82, rest=90)

CAPTIONS = [
    ("c0", 0,  6,  "muted",  "GROUND · operator selects Mission 2 — follow"),
    ("c1", 6,  14, "signal", 'RUN{"id":2}  →  915 MHz SF7'),
    ("c2", 14, 21, "signal", "ACK{accepted}  →  CONFIRM  →  ARMED   ·   two-step arm gate"),
    ("c3", 21, 31, "ink",    "AUTO.TAKEOFF  →  hover"),
    ("c4", 31, 40, "ink",    "OAK-D  →  person detected   ·   {x,y,z} over UDP 5005"),
    ("c5", 40, 58, "signal", "OFFBOARD velocity follow   ·   keep 3 m   ·   telemetry home over LoRa"),
    ("c6", 58, 68, "signal", "link lost > 4 s   →   failsafe"),
    ("c7", 68, 82, "ink",    "AUTO.RTL  →  return to launch"),
    ("c8", 82, 90, "ink",    "AUTO.LAND  →  disarm"),
    ("c9", 90, 100, "muted", "Target system — Mission 2 in docs/ROADMAP.md · "
                             "bench-tested against mocks, outdoor flight pending"),
]


def window(name, start, end):
    """A steps(1,end) keyframe that shows an element only within [start, end)."""
    if start == 0:
        return (f"    @keyframes {name} {{ 0%,{end-0.1:g}% {{opacity:1}} "
                f"{end:g}%,100% {{opacity:0}} }}")
    if end >= 100:
        return (f"    @keyframes {name} {{ 0%,{start-0.1:g}% {{opacity:0}} "
                f"{start:g}%,100% {{opacity:1}} }}")
    return (f"    @keyframes {name} {{ 0%,{start-0.1:g}% {{opacity:0}} "
            f"{start:g}%,{end-0.1:g}% {{opacity:1}} {end:g}%,100% {{opacity:0}} }}")


def build(theme_name):
    t = THEMES[theme_name]
    mono = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
    grot = "Helvetica Neue,Helvetica,Arial,sans-serif"

    caps = "\n".join(
        f'    <text id="{i}" x="60" y="382" fill="{t[c]}" font-family="{mono}" '
        f'font-size="13" letter-spacing="1.1">{s}</text>'
        for i, _, _, c, s in CAPTIONS)
    cap_css = "\n".join(f"    #{i} {{ animation: k{i} {CYCLE} steps(1,end) infinite }}"
                        for i, _, _, _, _ in CAPTIONS)
    cap_kf = "\n".join(window(f"k{i}", a, b) for i, a, b, _, _ in CAPTIONS)

    style = f"""  <style>
    #drone, #walker {{ transform-box: view-box; transform-origin: 0 0 }}
    /* Base position is the follow leg, not the pad: with animation off this is
       the frame the reader is left with, so the camera cone has to point at
       the person rather than at empty sky. */
    #drone  {{ transform: translate(620px, 150px);
              animation: flight {CYCLE} ease-in-out infinite }}
    #walker {{ transform: translate(780px, 0px);
              animation: walk {CYCLE} linear infinite }}

    /* The flight path. Holds on the pad, climbs, follows, drifts on after the
       link drops, then returns and lands. */
    @keyframes flight {{
      0%,{B['takeoff']}%  {{ transform: translate(300px, 320px) }}
      {B['detect']}%,{B['follow']}% {{ transform: translate(300px, 150px) }}
      {B['linkloss']}%    {{ transform: translate(620px, 150px) }}
      {B['rtl']}%         {{ transform: translate(620px, 150px) }}
      {B['land']}%        {{ transform: translate(300px, 150px) }}
      {B['rest']}%,100%   {{ transform: translate(300px, 320px) }}
    }}
    @keyframes walk {{
      0%,{B['follow']}%   {{ transform: translate(780px, 0px) }}
      {B['rtl']}%,100%    {{ transform: translate(880px, 0px) }}
    }}

    #rotorL, #rotorR, #rfGround circle, #rfDrone circle {{
      transform-box: fill-box; transform-origin: center }}
    #rotorL, #rotorR {{ animation: spin .34s linear infinite }}
    @keyframes spin {{ 0%,100% {{ transform: scaleX(1) }} 50% {{ transform: scaleX(.26) }} }}

    #rfGround {{ opacity: 0; animation: kRf {CYCLE} steps(1,end) infinite }}
    #rfDrone  {{ opacity: 0; animation: kTlm {CYCLE} steps(1,end) infinite }}
    #cone     {{ opacity: 0; animation: kCone {CYCLE} steps(1,end) infinite }}
    #lock     {{ opacity: 0; animation: kLock {CYCLE} steps(1,end) infinite }}
    #linkX    {{ opacity: 0; animation: kX {CYCLE} steps(1,end) infinite }}
    #armed    {{ opacity: 0; animation: kArm {CYCLE} steps(1,end) infinite }}
    #rfGround circle, #rfDrone circle {{ animation: ping 1.4s linear infinite }}
    #rfGround circle:nth-child(2), #rfDrone circle:nth-child(2) {{ animation-delay: .46s }}
    #rfGround circle:nth-child(3), #rfDrone circle:nth-child(3) {{ animation-delay: .92s }}
    @keyframes ping {{ 0% {{ transform: scale(1); opacity: .8 }}
                      100% {{ transform: scale(7.6); opacity: 0 }} }}

{window('kRf',   B['cmd'],      B['takeoff'])}
{window('kTlm',  B['follow'],   B['linkloss'])}
{window('kCone', B['detect'],   B['rtl'])}
{window('kLock', B['detect']+2, B['rtl'])}
{window('kX',    B['linkloss'], B['rtl'])}
{window('kArm',  B['confirm'],  B['rest'])}

{cap_css}
{cap_kf}

    /* This piece is almost entirely movement, so reduced motion gets a still:
       the aircraft parks at its base transform (hover) with the camera on. */
    @media (prefers-reduced-motion: reduce) {{
      #drone, #walker, #rotorL, #rotorR,
      #rfGround circle, #rfDrone circle {{ animation: none }}
      #rfGround, #rfDrone, #linkX {{ display: none }}
      #cone, #lock, #armed {{ opacity: 1; animation: none }}
      #ticker text {{ animation: none; opacity: 0 }}
      #c9 {{ opacity: 1 }}
    }}
  </style>"""

    def rf(rid, extra=""):
        return (f'<g id="{rid}"{extra} fill="none" stroke="{t["signal"]}" '
                f'stroke-width="1.6"><circle r="6"/><circle r="6"/><circle r="6"/></g>')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     role="img" aria-label="Venator concept of operations: a laptop commands the drone over 915 MHz LoRa, it takes off, follows a person at 3 m, and returns home when the link drops">
  <title>Venator — concept of operations (target system)</title>
{style}
  <rect width="{W}" height="{H}" fill="{t['bg']}"/>

  <text x="60" y="44" fill="{t['muted']}" font-family="{grot}" font-size="11"
    font-weight="600" letter-spacing="3.4">CONCEPT OF OPERATIONS</text>
  <text x="60" y="64" fill="{t['ink']}" font-family="{grot}" font-size="15" font-weight="600">
    Mission 2 — command from a laptop, follow a person, come home on link loss</text>

  <path d="M40 {GROUND_Y}H960" stroke="{t['line']}" stroke-width="1.5"/>
  <path d="M276 {GROUND_Y}h48" stroke="{t['muted']}" stroke-width="3"/>
  <text x="300" y="{GROUND_Y+18}" fill="{t['muted']}" font-family="{mono}" font-size="10"
    text-anchor="middle" letter-spacing="1">PAD</text>

  <!-- ground station -->
  <rect x="60" y="260" width="150" height="80" fill="{t['panel']}" stroke="{t['line']}" stroke-width="1.5"/>
  <text x="74" y="284" fill="{t['ink']}" font-family="{grot}" font-size="13"
    font-weight="600" letter-spacing="2">GROUND</text>
  <text x="74" y="304" fill="{t['muted']}" font-family="{mono}" font-size="10.5">gcs_client.py</text>
  <text x="74" y="320" fill="{t['muted']}" font-family="{mono}" font-size="10.5">laptop · any OS</text>
  <path d="M196 260v-34" stroke="{t['muted']}" stroke-width="1.5"/>
  <g transform="translate(196,222)">{rf('rfGround')}</g>
  <g id="armed" transform="translate(74,332)">
    <circle r="4" cx="4" cy="-4" fill="{t['signal']}"/>
    <text x="14" y="0" fill="{t['signal']}" font-family="{mono}" font-size="10"
      letter-spacing="1.4">ARMED</text>
  </g>

  <!-- the person being followed -->
  <g id="walker">
    <g transform="translate(0,{GROUND_Y})" fill="{t['ink']}">
      <circle cx="0" cy="-42" r="7"/>
      <path d="M-6 -34h12l3 20h-6l-2 14h-4l-2-14h-6z"/>
    </g>
    <g id="lock" transform="translate(0,{GROUND_Y})" fill="none" stroke="{t['signal']}" stroke-width="1.6">
      <path d="M-20-58h-10v10M20-58h10v10M-20 8h-10V-2M20 8h10V-2"/>
    </g>
  </g>

  <!-- the aircraft -->
  <g id="drone">
    <g id="cone" fill="{t['signal']}" opacity=".1">
      <path d="M0 14 L150 190 L-40 190Z" fill="{t['signal']}" opacity=".07"/>
      <path d="M0 14 L150 190 L-40 190Z" fill="none" stroke="{t['signal']}"
        stroke-width="1" opacity=".32" stroke-dasharray="4 4"/>
    </g>
    {rf('rfDrone', ' transform="translate(0,-16)"')}
    <path d="M-34 -4h68" stroke="{t['ink']}" stroke-width="3"/>
    <path d="M-34 -4l-6-10M34 -4l6-10" stroke="{t['ink']}" stroke-width="2.5"/>
    <rect x="-16" y="-8" width="32" height="16" rx="2" fill="{t['ink']}"/>
    <circle cx="0" cy="12" r="6" fill="{t['ink']}"/>
    <circle cx="0" cy="12" r="2.4" fill="{t['bg']}"/>
    <ellipse id="rotorL" cx="-40" cy="-15" rx="19" ry="2.6" fill="{t['muted']}"/>
    <ellipse id="rotorR" cx="40" cy="-15" rx="19" ry="2.6" fill="{t['muted']}"/>
  </g>

  <g id="linkX" transform="translate(470,132)">
    <path d="M-12-12l24 24M12-12l-24 24" stroke="{t['signal']}" stroke-width="3"/>
    <text x="0" y="34" fill="{t['signal']}" font-family="{mono}" font-size="11"
      text-anchor="middle" letter-spacing="1.4">LINK LOST</text>
  </g>

  <g id="ticker">
{caps}
  </g>
</svg>
"""
    return svg


for name in ("light", "dark"):
    p = ROOT / f"conops-{name}.svg"
    p.write_text(build(name))
    print(f"{p.name}: {p.stat().st_size} bytes")
