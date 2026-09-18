#!/usr/bin/env python3
"""Add the live-link animation to the Venator system diagram.

The static artwork is left alone: this only lifts the caption line (it becomes
the ticker's resting frame) and appends two groups. Everything that moves lives
inside #packets or #ticker, so prefers-reduced-motion switches the whole thing
off and leaves exactly the diagram we have today.

One 8s cycle tells one true story: a command leaves GROUND over 915 MHz LoRa,
the Jetson relays it to the Pixhawk over MAVLink, and the reply comes back the
same way.

The two themes light a packet differently on purpose. On black a blurred core
reads as a glow; on white the same blur reads as a drop shadow, which the brand
rules out. So paper gets a crisp dot inside an expanding ring instead.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets" / "brand"

# The static diagram, with its palette tokenised. It lives here rather than
# being read back off disk: the old version of this script injected animation
# into the file it had already animated, so running it twice corrupted the
# asset. Generating from a constant makes it idempotent.
BASE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 214" width="900" height="214">
  <rect width="900" height="214" fill="__BG__"/>
  <rect x="40" y="34" width="220" height="120" fill="__PANEL__" stroke="__LINE__" stroke-width="1.5"/><text x="58" y="64" fill="__INK__" font-family="Helvetica Neue,Helvetica,Arial,sans-serif" font-size="15" font-weight="600" letter-spacing="2.4">GROUND</text><text x="58" y="90" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="12.5">ground/gcs_client.py</text><text x="58" y="109" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="12.5">laptop · any OS</text><text x="58" y="128" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="12.5">menu, commands, replies</text>
  <rect x="340" y="34" width="220" height="120" fill="__PANEL__" stroke="__LINE__" stroke-width="1.5"/><text x="358" y="64" fill="__INK__" font-family="Helvetica Neue,Helvetica,Arial,sans-serif" font-size="15" font-weight="600" letter-spacing="2.4">DRONE</text><text x="358" y="90" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="12.5">drone/c2_server.py</text><text x="358" y="109" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="12.5">Jetson Orin Nano</text><text x="358" y="128" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="12.5">missions · camera · checks</text>
  <rect x="640" y="34" width="220" height="120" fill="__PANEL__" stroke="__LINE__" stroke-width="1.5"/><text x="658" y="64" fill="__INK__" font-family="Helvetica Neue,Helvetica,Arial,sans-serif" font-size="15" font-weight="600" letter-spacing="2.4">AIRFRAME</text><text x="658" y="90" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="12.5">Pixhawk 2.4.8</text><text x="658" y="109" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="12.5">PX4 v1.13.3</text><text x="658" y="128" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="12.5">hexarotor</text>
  <path d="M260 94h72" stroke="__SIGNAL__" stroke-width="2" opacity="1"/><path d="M331 88l8 6-8 6" fill="__SIGNAL__" opacity="1"/><text x="300.0" y="78" fill="__SIGNAL__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11.5" text-anchor="middle" letter-spacing="1.4" opacity="1">915 MHz</text><text x="300.0" y="118" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11" text-anchor="middle">LoRa SF7</text>
  <path d="M560 94h72" stroke="__INK__" stroke-width="2" opacity=".8"/><path d="M631 88l8 6-8 6" fill="__INK__" opacity=".8"/><text x="600.0" y="78" fill="__INK__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11.5" text-anchor="middle" letter-spacing="1.4" opacity=".8">MAVLink</text><text x="600.0" y="118" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11" text-anchor="middle">USB</text>
  <text x="40" y="192" fill="__MUTED__" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="11.5" letter-spacing="1.2">radio/protocol.py — newline JSON, one packet per message, spoken by both ends</text>
</svg>"""

BASE_PALETTE = {
    "light": dict(BG="#F2F1EE", PANEL="#FFFFFF", LINE="#DAD8D3",
                  MUTED="#6E6B66", INK="#0A0A0A", SIGNAL="#E05316"),
    "dark":  dict(BG="#0A0A0A", PANEL="#131314", LINE="#2A2A27",
                  MUTED="#8A8781", INK="#F2F1EE", SIGNAL="#E05316"),
}


def static_base(theme):
    """The un-animated diagram for a theme."""
    out = BASE
    for k, v in BASE_PALETTE[theme].items():
        out = out.replace(f"__{k}__", v)
    return out

THEMES = {
    "dark":  dict(muted="#8A8781", text="#F2F1EE", signal="#E05316", glow=True,  flash=1.5),
    "light": dict(muted="#6E6B66", text="#0A0A0A", signal="#E05316", glow=False, flash=2.5),
}

CYCLE = "8s"
# Phase boundaries as a fraction of the cycle.
P1 = (0.00, 0.15)   # LoRa    GROUND   -> DRONE     command out
P2 = (0.16, 0.27)   # MAVLink DRONE    -> AIRFRAME  relayed to the flight controller
P3 = (0.31, 0.42)   # MAVLink AIRFRAME -> DRONE     reply
P4 = (0.43, 0.58)   # LoRa    DRONE    -> GROUND    reply home

Y = 94
LORA = (262, 336)   # travel ranges, kept inside the static arrows
MAV = (562, 636)
BOXES = {"ground": 40, "drone": 340, "airframe": 640}

# Arrowheads copied from the static diagram. Return trips light the run but add
# no head: the static forward head is still drawn underneath, and a second one
# pointing back just reads as a muddy double-arrow. The dot carries direction.
HEADS = {"lora": "M331 88l8 6-8 6", "mav": "M631 88l8 6-8 6"}
RUNS = {"lora": "M260 94h72", "mav": "M560 94h72"}


def envelope(stops):
    """Zip (time, value) stops into SMIL keyTimes/values, collapsing duplicate times."""
    out = []
    for t, v in stops:
        if out and abs(out[-1][0] - t) < 1e-9:
            out[-1] = (t, v)
        else:
            out.append((t, v))
    return (";".join(f"{t:g}" for t, _ in out), ";".join(str(v) for _, v in out))


def packet(start, end, x0, x1, colour, rid, theme):
    """A dot that waits at the start, rides the gap during [start, end], then parks."""
    fade = 0.012
    # keyPoints must hold at 0 until `start`, or the dot drifts from t=0.
    ktimes, kpoints = envelope([(0, 0), (start, 0), (end, 1), (1, 1)])
    otimes, ovals = envelope(
        [(0, 0), (start, 0), (start + fade, 1), (end - fade, 1), (end, 0), (1, 0)]
    )
    if theme["glow"]:
        body = (f'\n      <circle r="9" fill="{colour}" opacity=".28"/>'
                f'\n      <circle r="3.2" fill="{colour}" filter="url(#vGlow)"/>')
    else:
        body = (f'\n      <circle r="6" fill="none" stroke="{colour}" stroke-width="1.2" opacity=".4">'
                f'\n        <animate attributeName="r" values="5;10;5" dur="1.1s" repeatCount="indefinite"/>'
                f'\n        <animate attributeName="opacity" values=".45;0;.45" dur="1.1s" repeatCount="indefinite"/>'
                f'\n      </circle>'
                f'\n      <circle r="3.4" fill="{colour}"/>')
    return f"""    <g opacity="0" id="{rid}">
      <animateMotion dur="{CYCLE}" repeatCount="indefinite" calcMode="linear"
        keyPoints="{kpoints}" keyTimes="{ktimes}" path="M{x0},{Y} H{x1}"/>
      <animate attributeName="opacity" dur="{CYCLE}" repeatCount="indefinite"
        values="{ovals}" keyTimes="{otimes}"/>{body}
    </g>"""


def hot_link(start, end, run, head, colour, rid):
    """The run lights up while a packet is on it; only outbound trips light the head."""
    t, v = envelope(
        [(0, 0), (start, 0), (start + 0.02, ".6"), (end - 0.02, ".6"), (end, 0), (1, 0)]
    )
    arrow = f'\n      <path d="{HEADS[run]}" fill="{colour}"/>' if head else ""
    return f"""    <g id="{rid}" opacity="0">
      <animate attributeName="opacity" dur="{CYCLE}" repeatCount="indefinite"
        values="{v}" keyTimes="{t}"/>
      <path d="{RUNS[run]}" stroke="{colour}" stroke-width="2"/>{arrow}
    </g>"""


def arrival(x, at, colour, rid, theme):
    """The receiving box flashes as the packet lands.

    On paper the flash leans on weight, not brightness: an ink outline at the
    static 1.5px is almost indistinguishable from the border already there.
    """
    t, v = envelope([(0, 0), (at - 0.005, 0), (at + 0.005, ".9"), (at + 0.10, 0), (1, 0)])
    return f"""    <rect id="{rid}" x="{x}" y="34" width="220" height="120" fill="none"
      stroke="{colour}" stroke-width="{theme['flash']}" opacity="0">
      <animate attributeName="opacity" dur="{CYCLE}" repeatCount="indefinite"
        values="{v}" keyTimes="{t}"/>
    </rect>"""


def build(theme_name):
    t = THEMES[theme_name]
    src = static_base(theme_name)

    caption = re.search(r'\n\s*<text x="40" y="192".*?</text>', src, re.S)
    if not caption:
        sys.exit("gen_system: the embedded base lost its caption line")
    caption_text = re.search(r">([^<]*)</text>", caption.group(0)).group(1)
    src = src.replace(caption.group(0), "")

    defs = ""
    if t["glow"]:
        defs = """
  <defs>
    <filter id="vGlow" x="-2" y="-2" width="5" height="5">
      <feGaussianBlur in="SourceGraphic" stdDeviation="2.6" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>"""

    style = f"""
  <title>Venator — a command over 915 MHz LoRa, relayed to the flight controller, and the reply home</title>
  <style>
    /* steps(1,end) swaps one caption for the next with no cross-fade, so the
       line reads like a console rather than a slideshow. */
    #ticker text {{ opacity: 0 }}
    #cap0 {{ animation: vt0 {CYCLE} steps(1,end) infinite }}
    #cap1 {{ animation: vt1 {CYCLE} steps(1,end) infinite }}
    #cap2 {{ animation: vt2 {CYCLE} steps(1,end) infinite }}
    #capf {{ animation: vtf {CYCLE} steps(1,end) infinite; opacity: 1 }}
    @keyframes vt0 {{ 0%,15.9% {{opacity:1}} 16%,100% {{opacity:0}} }}
    @keyframes vt1 {{ 0%,15.9% {{opacity:0}} 16%,30.9% {{opacity:1}} 31%,100% {{opacity:0}} }}
    @keyframes vt2 {{ 0%,30.9% {{opacity:0}} 31%,57.9% {{opacity:1}} 58%,100% {{opacity:0}} }}
    @keyframes vtf {{ 0%,57.9% {{opacity:0}} 58%,100% {{opacity:1}} }}

    /* Everything that moves is in #packets, so this leaves the plain diagram. */
    @media (prefers-reduced-motion: reduce) {{
      #packets {{ display: none }}
      #ticker text {{ animation: none; opacity: 0 }}
      #capf {{ opacity: 1 }}
    }}
  </style>{defs}"""

    packets = "\n".join([
        hot_link(*P1, "lora", True,  t["signal"], "hotLora1"),
        hot_link(*P4, "lora", False, t["signal"], "hotLora2"),
        hot_link(*P2, "mav",  True,  t["text"],   "hotMav1"),
        hot_link(*P3, "mav",  False, t["text"],   "hotMav2"),
        arrival(BOXES["drone"], P1[1], t["signal"], "hitDrone", t),
        arrival(BOXES["airframe"], P2[1], t["text"], "hitAirframe", t),
        arrival(BOXES["ground"], P4[1], t["signal"], "hitGround", t),
        packet(*P1, LORA[0], LORA[1], t["signal"], "pkLora1", t),
        packet(*P2, MAV[0], MAV[1], t["text"], "pkMav1", t),
        packet(*P3, MAV[1], MAV[0], t["text"], "pkMav2", t),
        packet(*P4, LORA[1], LORA[0], t["signal"], "pkLora2", t),
    ])

    mono = ('font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" '
            'font-size="11.5" letter-spacing="1.2"')
    lines = [
        ("cap0", t["signal"], 'GROUND  →  {"t":"cmd","seq":41}  →  915 MHz SF7'),
        ("cap1", t["text"],   'DRONE  →  MAVLink  →  Pixhawk  ·  command relayed'),
        ("cap2", t["signal"], '{"t":"ack","seq":41}  →  the reply comes back the same way'),
        ("capf", t["muted"],  caption_text),
    ]
    ticker = "\n".join(
        f'    <text id="{i}" x="40" y="192" fill="{c}" {mono}>{s}</text>' for i, c, s in lines
    )

    out = src.replace(
        "</svg>",
        f'  <g id="packets">\n{packets}\n  </g>\n  <g id="ticker">\n{ticker}\n  </g>\n</svg>',
    )
    open_tag = re.search(r"<svg[^>]*>", out).group(0)
    return out.replace(open_tag, open_tag + style, 1)


for name in ("dark", "light"):
    path = ROOT / f"system-{name}.svg"
    path.write_text(build(name))
    print(f"{path.name}: {path.stat().st_size} bytes")
