#!/usr/bin/env python3
"""Generate assets/brand/phases-{light,dark}.svg from the roadmap's Status table.

The animation used to hard-code which phases were done. That made it the one
artifact in the repo that could go stale silently: flip a phase in
docs/ROADMAP.md and the picture directly above the table would keep showing the
old state, with nothing failing. Now the table is the only source of state and
this script is the only way the SVG is produced, so the two cannot disagree.

Run it after changing a phase's state:

    python3 tools/gen_phases.py

CI runs it and then `git diff --exit-code`, so a stale committed SVG is a red
build rather than a quiet lie.

Labels and captions live here rather than in the table on purpose: the table
carries state, this file carries how it is drawn. Only state is shared, and
only in one direction.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "ROADMAP.md"
OUT = ROOT / "assets" / "brand"

W, H = 1000, 306
CYCLE = "12s"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
GROT = "Helvetica Neue,Helvetica,Arial,sans-serif"

THEMES = {
    "light": dict(bg="#F2F1EE", line="#DAD8D3", muted="#6E6B66",
                  ink="#0A0A0A", signal="#E05316"),
    "dark":  dict(bg="#0A0A0A", line="#2A2A27", muted="#8A8781",
                  ink="#F2F1EE", signal="#E05316"),
}

ICON = {"✅": "done", "🔵": "wip", "⬜": "todo"}

# phase -> (two-line label, caption). State is NOT here; it comes from the table.
DRAW = {
    "0": (["NVMe +", "restore"],     "0 · NVMe install + project restore"),
    "1": (["C2", "protocol"],        "1 · C2 protocol — newline JSON, handshake, ACK / retransmit"),
    "2": (["laptop", "client"],      "2 · laptop client — runs today with --mock; CI builds .exe and .app"),
    "3": (["Heltec", "firmware"],    "3 · firmware — flashed and validated on real radios, OLED on both sticks"),
    "4": (["Jetson", "C2 server"],   "4 · Jetson server — working over real LoRa, zero-touch boot service"),
    "5": (["GPS +", "waypoints"],    "5 · waypoint flight — built and bench-tested; the GPS is not fitted yet"),
    "6": (["polish +", "avoidance"], "6 · polish and obstacle avoidance — not started"),
}

SUMMARY = {
    "done": "done", "wip": "in progress", "todo": "not started",
}

RAIL_Y, X0, X1 = 152, 96, 904
T0, DT = 0.8, 1.0
pc = lambda sec: round(sec / 12 * 100, 2)


def read_states():
    """phase number -> done|wip|todo, from the Status table. Rows keyed '—' are
    missions rather than phases and are skipped; a phase listed twice must agree."""
    text = ROADMAP.read_text(encoding="utf-8")
    m = re.search(r"^## Status$(.*?)^## ", text, re.S | re.M)
    if not m:
        sys.exit("gen_phases: could not find the '## Status' section in docs/ROADMAP.md")

    found = {}
    for num, icon in re.findall(r"^\|\s*([0-6])\s*\|.*?\|\s*(✅|🔵|⬜)", m.group(1), re.M):
        state = ICON[icon]
        if num in found and found[num] != state:
            sys.exit(f"gen_phases: phase {num} is listed with conflicting states "
                     f"({found[num]} and {state}) in docs/ROADMAP.md")
        found[num] = state

    missing = sorted(set(DRAW) - set(found))
    if missing:
        sys.exit(f"gen_phases: no row in the Status table for phase(s) {', '.join(missing)}. "
                 f"Add them, or update DRAW in this file.")
    extra = sorted(set(found) - set(DRAW))
    if extra:
        sys.exit(f"gen_phases: the table has phase(s) {', '.join(extra)} that this script "
                 f"does not know how to draw. Add them to DRAW.")
    return found


def build(theme_name, states):
    t = THEMES[theme_name]
    order = sorted(DRAW)
    step = (X1 - X0) / (len(order) - 1)
    nodes, css, kf, caps = [], [], [], []

    for i, num in enumerate(order):
        lab, cap = DRAW[num]
        state = states[num]
        x = X0 + i * step
        at = pc(T0 + i * DT)

        if state == "done":
            body = (f'<circle cx="{x}" cy="{RAIL_Y}" r="17" fill="{t["ink"]}"/>'
                    f'<text x="{x}" y="{RAIL_Y+5}" fill="{t["bg"]}" font-family="{MONO}" '
                    f'font-size="14" text-anchor="middle" font-weight="700">{num}</text>')
        elif state == "wip":
            body = (f'<circle id="pulse{i}" cx="{x}" cy="{RAIL_Y}" r="17" fill="none" '
                    f'stroke="{t["signal"]}" stroke-width="2"/>'
                    f'<circle cx="{x}" cy="{RAIL_Y}" r="17" fill="{t["bg"]}" '
                    f'stroke="{t["signal"]}" stroke-width="2.6"/>'
                    f'<text x="{x}" y="{RAIL_Y+5}" fill="{t["signal"]}" font-family="{MONO}" '
                    f'font-size="14" text-anchor="middle" font-weight="700">{num}</text>')
            css.append(f"    #pulse{i} {{ transform-box: fill-box; transform-origin: center;"
                       f" animation: ring 1.8s ease-out infinite }}")
        else:
            body = (f'<circle cx="{x}" cy="{RAIL_Y}" r="17" fill="{t["bg"]}" '
                    f'stroke="{t["muted"]}" stroke-width="1.6" stroke-dasharray="4 4"/>'
                    f'<text x="{x}" y="{RAIL_Y+5}" fill="{t["muted"]}" font-family="{MONO}" '
                    f'font-size="14" text-anchor="middle">{num}</text>')

        lc = {"wip": t["signal"], "done": t["ink"], "todo": t["muted"]}[state]
        labels = "".join(
            f'<text x="{x}" y="{RAIL_Y + 44 + j*15}" fill="{lc}" font-family="{MONO}" '
            f'font-size="11.5" text-anchor="middle">{s}</text>' for j, s in enumerate(lab))

        # data-state is what the CI check reads: intent, not styling.
        nodes.append(f'  <g id="n{i}" data-phase="{num}" data-state="{state}" '
                     f'opacity="0">{body}{labels}</g>')
        css.append(f"    #n{i} {{ animation: k{i} {CYCLE} steps(1,end) infinite }}")
        kf.append(f"    @keyframes k{i} {{ 0%,{at-0.01:g}% {{opacity:0}} "
                  f"{at:g}%,100% {{opacity:1}} }}")

        nxt = pc(T0 + (i + 1) * DT)
        caps.append((f"c{i}", at, nxt if i < len(order) - 1 else pc(T0 + len(order) * DT + 0.4),
                     t["muted"], cap))

    tally = {k: sum(1 for v in states.values() if v == k) for k in ("done", "wip", "todo")}
    summary = " · ".join(f"{tally[k]} {SUMMARY[k]}" for k in ("done", "wip", "todo") if tally[k])
    t_sum = pc(T0 + len(order) * DT + 0.4)
    caps.append(("cs", t_sum, 100, t["ink"],
                 f"{summary} — the link works end to end; flight is what is left"))

    cap_el = "\n".join(
        f'    <text id="{i}" x="96" y="282" fill="{c}" font-family="{MONO}" font-size="13"'
        f' letter-spacing="0.8">{s}</text>' for i, _, _, c, s in caps)
    cap_css = "\n".join(f"    #{i} {{ animation: t{i} {CYCLE} steps(1,end) infinite }}"
                        for i, *_ in caps)
    cap_kf = "\n".join(
        (f"    @keyframes t{i} {{ 0%,{a-0.01:g}% {{opacity:0}} {a:g}%,100% {{opacity:1}} }}"
         if b >= 100 else
         f"    @keyframes t{i} {{ 0%,{a-0.01:g}% {{opacity:0}} {a:g}%,{b-0.01:g}% {{opacity:1}} "
         f"{b:g}%,100% {{opacity:0}} }}")
        for i, a, b, _, _ in caps)

    legend = ""
    for j, (g, txt) in enumerate([("done", "done"), ("wip", "in progress"), ("todo", "not started")]):
        lx = 648 + j * 118
        if g == "done":
            glyph = f'<circle cx="{lx}" cy="46" r="7" fill="{t["ink"]}"/>'
        elif g == "wip":
            glyph = f'<circle cx="{lx}" cy="46" r="7" fill="none" stroke="{t["signal"]}" stroke-width="2.2"/>'
        else:
            glyph = (f'<circle cx="{lx}" cy="46" r="7" fill="none" stroke="{t["muted"]}" '
                     f'stroke-width="1.5" stroke-dasharray="3 3"/>')
        legend += glyph + (f'<text x="{lx+13}" y="50" fill="{t["muted"]}" font-family="{MONO}" '
                           f'font-size="11">{txt}</text>')

    aria = "; ".join(f"phase {n} {states[n]}" for n in order)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     role="img" aria-label="Venator phase status: {aria}">
  <title>Venator — phase status</title>
  <!-- Generated by tools/gen_phases.py from the Status table in docs/ROADMAP.md.
       Do not edit by hand: CI regenerates this and fails if it differs. -->
  <style>
    @keyframes ring {{ 0% {{ transform: scale(1); opacity: .8 }}
                      100% {{ transform: scale(2.1); opacity: 0 }} }}
    #sumbar {{ animation: ks {CYCLE} steps(1,end) infinite }}
    @keyframes ks {{ 0%,{t_sum-0.01:g}% {{opacity:0}} {t_sum:g}%,100% {{opacity:1}} }}
    #ticker text {{ opacity: 0 }}
    #cs {{ opacity: 1 }}
{chr(10).join(css)}
{chr(10).join(kf)}
{cap_css}
{cap_kf}
    @media (prefers-reduced-motion: reduce) {{
      [id^="pulse"] {{ animation: none; opacity: 0 }}
      [id^="n"], #sumbar {{ animation: none; opacity: 1 }}
      #ticker text {{ animation: none; opacity: 0 }}
      #cs {{ opacity: 1 }}
    }}
  </style>
  <rect width="{W}" height="{H}" fill="{t['bg']}"/>

  <text x="96" y="40" fill="{t['muted']}" font-family="{GROT}" font-size="11"
    font-weight="600" letter-spacing="3.4">PHASE STATUS</text>
  <text x="96" y="62" fill="{t['ink']}" font-family="{GROT}" font-size="15" font-weight="600">
    Where the project actually is</text>
  {legend}

  <path d="M{X0} {RAIL_Y}H{X1}" stroke="{t['line']}" stroke-width="1.5"/>
{chr(10).join(nodes)}

  <g id="sumbar" opacity="0">
    <path d="M96 240H904" stroke="{t['line']}" stroke-width="1"/>
  </g>

  <g id="ticker">
{cap_el}
  </g>
</svg>
"""


def main():
    states = read_states()
    print("gen_phases: read from docs/ROADMAP.md ->",
          ", ".join(f"{k}={states[k]}" for k in sorted(states)))
    for name in THEMES:
        path = OUT / f"phases-{name}.svg"
        path.write_text(build(name, states), encoding="utf-8")
        print(f"gen_phases: wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
