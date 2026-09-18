#!/usr/bin/env python3
"""Venator — the message net. One transmission, every stick hears it.

12s cycle. The honest shape of radio/phone_relay.py: a Station is one stick with
a serial link, so phones and spare laptops are not on the air at all — they load
a page over local HTTP from the machine that holds the stick. The Jetson holds
one too, so it is a chat node like any other.

'delivered 2 of 2' is the DESIGNED behaviour from ROADMAP open decision 5, not
today's: the relay currently ACKs before its dedup check and carries no `from`,
so with two peers the replies collide. The resting caption says so.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets" / "brand"
W, H = 1000, 400
CYCLE = "12s"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
GROT = "Helvetica Neue,Helvetica,Arial,sans-serif"

THEMES = {
    "light": dict(bg="#F2F1EE", panel="#FFFFFF", line="#DAD8D3", muted="#6E6B66",
                  ink="#0A0A0A", signal="#E05316"),
    "dark":  dict(bg="#0A0A0A", panel="#131314", line="#2A2A27", muted="#8A8781",
                  ink="#F2F1EE", signal="#E05316"),
}

TYPE, UPLINK, CAST, ARRIVE, FANOUT, DELIV, REST = 0, 16, 26, 50, 62, 76, 90
TX = (250, 268)          # the field stick — the only thing transmitting


def build(theme):
    t = THEMES[theme]

    def laptop(x, y, lab, s=1.0, rid=""):
        i = f' id="{rid}"' if rid else ""
        return f"""<g transform="translate({x},{y}) scale({s})">
      <rect x="-22" y="-16" width="44" height="28" rx="2" fill="{t['panel']}" stroke="{t['ink']}" stroke-width="1.6"/>
      <rect{i} x="-18" y="-12" width="36" height="20" fill="{t['signal']}" opacity="0"/>
      <path d="M-29 14h58" stroke="{t['ink']}" stroke-width="2"/>
      <text x="0" y="28" fill="{t['muted']}" font-family="{MONO}" font-size="9"
        text-anchor="middle">{lab}</text></g>"""

    def phone(x, y, lab, s=1.0, rid=""):
        i = f' id="{rid}"' if rid else ""
        return f"""<g transform="translate({x},{y}) scale({s})">
      <rect x="-11" y="-19" width="22" height="38" rx="3.5" fill="{t['panel']}" stroke="{t['ink']}" stroke-width="1.6"/>
      <rect{i} x="-7.5" y="-14" width="15" height="26" fill="{t['signal']}" opacity="0"/>
      <text x="0" y="31" fill="{t['muted']}" font-family="{MONO}" font-size="9"
        text-anchor="middle">{lab}</text></g>"""

    def stick(x, y, rid=""):
        i = f' id="{rid}"' if rid else ""
        return f"""<g transform="translate({x},{y})">
      <rect x="-6" y="-11" width="12" height="22" rx="1.5" fill="{t['ink']}"/>
      <path d="M0 -11v-13" stroke="{t['muted']}" stroke-width="1.5"/>
      <circle{i} r="17" fill="none" stroke="{t['signal']}" stroke-width="2" opacity="0"/></g>"""

    caps = [
        ("m0", TYPE,   UPLINK, "muted",  "field · typing on the relay page  ·  up to 180 characters"),
        ("m1", UPLINK, CAST,   "signal", "phone  →  host over local HTTP  →  its stick"),
        ("m2", CAST,   ARRIVE, "signal", "one transmission  ·  915 MHz SF7  ·  no addressing needed to be heard"),
        ("m3", ARRIVE, FANOUT, "ink",    "ground and Jetson receive it at the same instant"),
        ("m4", FANOUT, DELIV,  "ink",    "each stick hands the text to its own browsers"),
        ("m5", DELIV,  REST,   "signal", "delivered 2 of 2  ·  confirmed per peer, not a bare tick"),
        ("m6", REST,   100,    "muted",  'Designed behaviour — today the relay ACKs before dedup and has '
                                         'no "from". ROADMAP decision 5.'),
    ]
    cap_el = "\n".join(
        f'    <text id="{i}" x="56" y="378" fill="{t[c]}" font-family="{MONO}" '
        f'font-size="12.5" letter-spacing="1">{s}</text>' for i, _, _, c, s in caps)
    cap_css = "\n".join(f"    #{i} {{ animation: k{i} {CYCLE} steps(1,end) infinite }}"
                        for i, *_ in caps)

    def win(name, a, b):
        if a == 0:
            return f"    @keyframes {name} {{ 0%,{b-0.1:g}% {{opacity:1}} {b:g}%,100% {{opacity:0}} }}"
        if b >= 100:
            return f"    @keyframes {name} {{ 0%,{a-0.1:g}% {{opacity:0}} {a:g}%,100% {{opacity:1}} }}"
        return (f"    @keyframes {name} {{ 0%,{a-0.1:g}% {{opacity:0}} {a:g}%,{b-0.1:g}% "
                f"{{opacity:1}} {b:g}%,100% {{opacity:0}} }}")

    cap_kf = "\n".join(win(f"k{i}", a, b) for i, a, b, _, _ in caps)

    rings = "".join(f'<circle r="12" fill="none" stroke="{t["signal"]}" stroke-width="2" '
                    f'vector-effect="non-scaling-stroke"/>' for _ in range(3))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     role="img" aria-label="Venator message net: a phone sends a message through the machine holding a LoRa stick, one 915 MHz transmission reaches the ground station and the Jetson at once">
  <title>Venator — the message net</title>
  <style>
    #msg {{ transform-box: view-box; transform-origin: 0 0;
           transform: translate(250px, 200px); opacity: 0;
           animation: hop {CYCLE} linear infinite, kMsg {CYCLE} steps(1,end) infinite }}
    @keyframes hop {{
      0%,{TYPE+9}%  {{ transform: translate(112px, 196px) }}
      {UPLINK+5}%   {{ transform: translate(250px, 196px) }}
      {CAST-1}%,100%{{ transform: translate(250px, 250px) }}
    }}
{win('kMsg', TYPE + 4, CAST)}

    /* The wavefront. Stroke is kept off the transform so a 40x scale does not
       turn a 2px hairline into a slab. */
    #air {{ transform-box: view-box; transform-origin: {TX[0]}px {TX[1]}px;
           opacity: 0; animation: kAir {CYCLE} steps(1,end) infinite }}
    #air circle {{ transform-box: fill-box; transform-origin: center;
                  animation: cast 2s cubic-bezier(.2,.6,.4,1) infinite }}
    #air circle:nth-child(2) {{ animation-delay: .66s }}
    #air circle:nth-child(3) {{ animation-delay: 1.32s }}
    @keyframes cast {{ 0% {{ transform: scale(1); opacity: .9 }}
                      100% {{ transform: scale(42); opacity: 0 }} }}
{win('kAir', CAST, ARRIVE + 4)}

    #hitG, #hitD {{ animation: kHit {CYCLE} steps(1,end) infinite }}
{win('kHit', ARRIVE, FANOUT + 6)}

    #scrGL, #scrGP, #scrJ, #scrFL, #scrFP {{ animation: kScr {CYCLE} steps(1,end) infinite }}
    @keyframes kScr {{ 0%,{FANOUT-0.1:g}% {{opacity:0}} {FANOUT:g}%,{REST-0.1:g}% {{opacity:.28}}
                      {REST:g}%,100% {{opacity:0}} }}
    #scrFP {{ animation: kType {CYCLE} steps(1,end) infinite }}
    @keyframes kType {{ 0%,{UPLINK+4:g}% {{opacity:.28}} {UPLINK+4.1:g}%,100% {{opacity:0}} }}

    #bubble {{ animation: kBub {CYCLE} steps(1,end) infinite }}
{win('kBub', TYPE + 2, CAST)}
    #deliv {{ animation: kDel {CYCLE} steps(1,end) infinite }}
{win('kDel', DELIV, REST)}

    #ticker text {{ opacity: 0 }}
    #m6 {{ opacity: 1 }}
{cap_css}
{cap_kf}

    @media (prefers-reduced-motion: reduce) {{
      #msg, #air, #air circle {{ animation: none }}
      #air, #msg, #bubble, #deliv {{ display: none }}
      #hitG, #hitD {{ opacity: 0; animation: none }}
      #scrGL, #scrGP, #scrJ {{ opacity: .28; animation: none }}
      #scrFL, #scrFP {{ opacity: 0; animation: none }}
      #ticker text {{ animation: none; opacity: 0 }}
      #m6 {{ opacity: 1 }}
    }}
  </style>
  <rect width="{W}" height="{H}" fill="{t['bg']}"/>

  <text x="56" y="42" fill="{t['muted']}" font-family="{GROT}" font-size="11"
    font-weight="600" letter-spacing="3.4">THE MESSAGE NET</text>
  <text x="56" y="62" fill="{t['ink']}" font-family="{GROT}" font-size="15" font-weight="600">
    One transmission on 915 MHz — every stick on the channel hears it</text>

  <!-- FIELD -->
  <rect x="56" y="92" width="290" height="205" fill="{t['panel']}" stroke="{t['line']}" stroke-width="1.5"/>
  <text x="74" y="118" fill="{t['ink']}" font-family="{GROT}" font-size="12"
    font-weight="600" letter-spacing="2.2">FIELD</text>
  {phone(112, 196, "phone", 1.0, "scrFP")}
  {laptop(250, 196, "phone_relay.py", 1.0, "scrFL")}
  <path d="M130 196h95" stroke="{t['ink']}" stroke-width="1.2" stroke-dasharray="3 3"/>
  <path d="M250 214v34" stroke="{t['ink']}" stroke-width="1.2"/>
  {stick(*TX)}
  <g id="bubble" transform="translate(112,150)">
    <rect x="-52" y="-16" width="150" height="26" rx="3" fill="{t['panel']}"
      stroke="{t['signal']}" stroke-width="1.3"/>
    <text x="-44" y="2" fill="{t['ink']}" font-family="{MONO}" font-size="10">"patrol clear, all ok"</text>
  </g>
  <g id="deliv" transform="translate(250,300)">
    <text x="0" y="0" fill="{t['signal']}" font-family="{MONO}" font-size="11"
      text-anchor="middle" letter-spacing="1.2">delivered 2 of 2</text>
  </g>

  <g id="air" transform="translate({TX[0]},{TX[1]})">{rings}</g>

  <!-- GROUND -->
  <rect x="640" y="92" width="304" height="96" fill="{t['panel']}" stroke="{t['line']}" stroke-width="1.5"/>
  <text x="658" y="116" fill="{t['ink']}" font-family="{GROT}" font-size="12"
    font-weight="600" letter-spacing="2.2">GROUND</text>
  {stick(688, 150, "hitG")}
  {laptop(790, 146, "laptop", 0.85, "scrGL")}
  {phone(898, 144, "phone", 0.8, "scrGP")}
  <path d="M700 150h56M820 146h50" stroke="{t['ink']}" stroke-width="1.2" stroke-dasharray="3 3"/>

  <!-- DRONE -->
  <rect x="640" y="206" width="304" height="96" fill="{t['panel']}" stroke="{t['line']}" stroke-width="1.5"/>
  <text x="658" y="230" fill="{t['ink']}" font-family="{GROT}" font-size="12"
    font-weight="600" letter-spacing="2.2">DRONE</text>
  {stick(688, 264, "hitD")}
  {laptop(790, 260, "Jetson", 0.85, "scrJ")}
  <path d="M700 264h56" stroke="{t['ink']}" stroke-width="1.2" stroke-dasharray="3 3"/>
  <g transform="translate(898,262) scale(.9)">
    <path d="M-17 -2h34" stroke="{t['ink']}" stroke-width="2.4"/>
    <path d="M-17 -2l-3 -5M17 -2l3 -5" stroke="{t['ink']}" stroke-width="2"/>
    <rect x="-8" y="-4" width="16" height="8" rx="1.5" fill="{t['ink']}"/>
    <ellipse cx="-20" cy="-7.5" rx="9" ry="1.4" fill="{t['muted']}"/>
    <ellipse cx="20" cy="-7.5" rx="9" ry="1.4" fill="{t['muted']}"/>
  </g>

  <g id="msg">
    <rect x="-7" y="-7" width="14" height="14" rx="2.5" fill="{t['signal']}"/>
  </g>

  <text x="470" y="330" fill="{t['muted']}" font-family="{MONO}" font-size="9.5"
    text-anchor="middle">a phone is never on the air —</text>
  <text x="470" y="344" fill="{t['muted']}" font-family="{MONO}" font-size="9.5"
    text-anchor="middle">it loads a page from the machine holding the stick</text>

  <g id="ticker">
{cap_el}
  </g>
</svg>
"""


for name in ("light", "dark"):
    p = ROOT / f"mesh-{name}.svg"
    p.write_text(build(name))
    print(f"{p.name}: {p.stat().st_size} bytes")
