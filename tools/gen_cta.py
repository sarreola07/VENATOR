#!/usr/bin/env python3
"""The README call-to-action button — cyberpunk HUD treatment.

GitHub strips <style> and style attributes from README HTML, so a link cannot be
animated directly. An <img> pointing at an SVG can be, because the animation
lives inside the image. Wrapping it in <a> keeps it clickable.

This one deliberately breaks BRAND.md's "anything that reads as decoration is
wrong": the glow, scanlines and glitch are decoration. It is the one surface
where that is the point, so it is quarantined to this asset and nothing else.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets" / "brand"
W, H = 400, 92
GROT = "Helvetica Neue,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
SIG = "#E05316"
HOT = "#FF7A3D"          # a hotter tint of Signal for the neon core

THEMES = {   # the panel stays dark in both schemes; neon needs something to burn against
    "light": dict(panel="#0A0A0A", text="#F2F1EE", dim="#6E6B66"),
    "dark":  dict(panel="#131314", text="#F2F1EE", dim="#8A8781"),
}

# Chamfered HUD panel: top-left and bottom-right corners cut.
CUT = 20
PANEL = (f"M{CUT} 1 H{W-1} V{H-CUT-1} L{W-CUT-1} {H-1} H1 V{CUT+1} Z")
TXT_X, TXT_Y = 60, 48
SUB_Y = 70
SUB = "#9A968F"


def build(theme):
    t = THEMES[theme]

    def label(fill, extra=""):
        return (f'<text x="{TXT_X}" y="{TXT_Y}" fill="{fill}" font-family="{GROT}" '
                f'font-size="19" font-weight="700" letter-spacing="2.9"{extra}>SYSTEM OVERVIEW</text>')

    scan = "".join(f'<path d="M0 {y}H{W}" stroke="{t["text"]}" stroke-width="1" opacity=".05"/>'
                   for y in range(3, H, 4))
    chev = "".join(
        f'<path id="cv{i}" d="M{332 + i*15} 37l9 9-9 9" fill="none" stroke="{SIG}" '
        f'stroke-width="2.6" stroke-linecap="square"/>' for i in range(3))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     role="img" aria-label="System overview — an animated walkthrough">
  <title>System overview</title>
  <style>
    #sweep {{ transform-box: view-box; transform-origin: 0 0;
             animation: sweep 3.6s cubic-bezier(.35,0,.2,1) infinite }}
    @keyframes sweep {{
      0%       {{ transform: translateX(-40px); opacity: 0 }}
      10%      {{ opacity: 1 }}
      55%      {{ opacity: 1 }}
      64%,100% {{ transform: translateX({W + 40}px); opacity: 0 }}
    }}
    #edge {{ animation: burn 2.4s ease-in-out infinite }}
    @keyframes burn {{ 0%,100% {{ opacity: .95 }} 50% {{ opacity: .55 }} }}

    #dot {{ transform-box: fill-box; transform-origin: center;
           animation: beat 1.6s ease-in-out infinite }}
    @keyframes beat {{ 0%,100% {{ transform: scale(1) }} 50% {{ transform: scale(.66) }} }}
    #halo {{ transform-box: fill-box; transform-origin: center;
            animation: halo 1.6s ease-out infinite }}
    @keyframes halo {{ 0% {{ transform: scale(1); opacity:.6 }}
                      70%,100% {{ transform: scale(3.6); opacity:0 }} }}

    #cur {{ animation: blink 1.05s steps(1,end) infinite }}
    @keyframes blink {{ 0%,55% {{ opacity: 1 }} 56%,100% {{ opacity: 0 }} }}

    #cv0, #cv1, #cv2 {{ animation: chase 1.5s ease-in-out infinite }}
    #cv1 {{ animation-delay: .16s }}
    #cv2 {{ animation-delay: .32s }}
    @keyframes chase {{ 0%,100% {{ opacity: .22 }} 22% {{ opacity: 1 }} }}

    /* Glitch: a short tear every few seconds, not a constant wobble. */
    #gTop, #gBot, #gGhost {{ opacity: 0 }}
    #gTop {{ transform-box: view-box; transform-origin: 0 0;
            animation: gtop 5.2s steps(1,end) infinite }}
    #gBot {{ transform-box: view-box; transform-origin: 0 0;
            animation: gbot 5.2s steps(1,end) infinite }}
    #gGhost {{ transform-box: view-box; transform-origin: 0 0;
              animation: gghost 5.2s steps(1,end) infinite }}
    @keyframes gtop {{ 0%,71% {{opacity:0; transform:translateX(0)}}
      72% {{opacity:1; transform:translateX(-5px)}}
      74% {{opacity:1; transform:translateX(3px)}}
      76%,100% {{opacity:0; transform:translateX(0)}} }}
    @keyframes gbot {{ 0%,71% {{opacity:0; transform:translateX(0)}}
      72% {{opacity:1; transform:translateX(4px)}}
      74% {{opacity:1; transform:translateX(-3px)}}
      76%,100% {{opacity:0; transform:translateX(0)}} }}
    @keyframes gghost {{ 0%,70.9% {{opacity:0}}
      71% {{opacity:.85; transform:translate(2px,-1px)}}
      76%,100% {{opacity:0}} }}

    @media (prefers-reduced-motion: reduce) {{
      #sweep, #halo, #gTop, #gBot, #gGhost {{ display: none }}
      #edge, #dot, #cur, #cv0, #cv1, #cv2 {{ animation: none; opacity: 1 }}
    }}
  </style>
  <defs>
    <clipPath id="panelClip"><path d="{PANEL}"/></clipPath>
    <clipPath id="halfTop"><rect x="0" y="0" width="{W}" height="{TXT_Y-7}"/></clipPath>
    <clipPath id="halfBot"><rect x="0" y="{TXT_Y-7}" width="{W}" height="{TXT_Y+6}"/></clipPath>
    <filter id="neon" x="-25%" y="-60%" width="150%" height="220%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="3.2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="soft" x="-25%" y="-60%" width="150%" height="220%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="2"/>
    </filter>
  </defs>

  <path d="{PANEL}" fill="{t['panel']}"/>
  <g clip-path="url(#panelClip)">
    {scan}
    <g id="sweep">
      <rect x="0" y="0" width="3" height="{H}" fill="{HOT}" filter="url(#soft)" opacity=".9"/>
      <rect x="0" y="0" width="1.4" height="{H}" fill="#FFFFFF" opacity=".9"/>
    </g>
  </g>

  <path id="edge" d="{PANEL}" fill="none" stroke="{SIG}" stroke-width="2" filter="url(#neon)"/>

  <circle id="halo" cx="34" cy="42" r="5.5" fill="{SIG}"/>
  <circle id="dot" cx="34" cy="42" r="5.5" fill="{HOT}" filter="url(#neon)"/>

  {label(t['text'])}
  <text x="{TXT_X}" y="{SUB_Y}" fill="{SUB}" font-family="{MONO}" font-size="11.5"
    letter-spacing="1.4">animated · 60 seconds</text>
  <g id="gGhost">{label(SIG)}</g>
  <g id="gTop" clip-path="url(#halfTop)">{label(t['text'])}</g>
  <g id="gBot" clip-path="url(#halfBot)">{label(t['text'])}</g>

  <rect id="cur" x="296" y="33" width="10" height="18" fill="{HOT}" filter="url(#neon)"/>
  {chev}
</svg>
"""


for name in ("light", "dark"):
    p = ROOT / f"cta-{name}.svg"
    p.write_text(build(name))
    print(f"{p.name}: {p.stat().st_size} bytes")
