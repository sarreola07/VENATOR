# Venator — mark, palette, type

The look is deliberately plain: near-black, warm greys, one accent that only
appears when something is live. Anything that reads as decoration is wrong.

These are our own marks and colours, in the same register as the defence-tech
houses this borrows its tone from. Nobody else's logo, wordmark or brand colour
is reproduced here, and none should be added.

## The mark

A V of two converging beams — the link between two stations — closing on a node
in the accent colour. The node is the aircraft: the thing the link is about.

| File | Use |
|---|---|
| `assets/brand/lockup-dark.svg` | Mark + wordmark on dark. README hero, slides. |
| `assets/brand/lockup-light.svg` | Mark + wordmark on paper or a light UI. |
| `assets/brand/mark-dark.svg`, `mark-light.svg` | Mark alone, 24 px and up. |
| `assets/brand/favicon.svg` | 16–32 px. Arcs dropped; they turn to mud that small. |
| `assets/brand/social-preview.png` | 1280×640 card for GitHub, Slack, chat unfurls. |
| `assets/brand/system-dark.svg`, `system-light.svg` | The system diagram in the same style. |

Rules that keep it recognisable:

- **Clear space** of at least the mark's own width on every side.
- **Never recolour the mark.** Ink or paper, plus the accent node. No gradients,
  no shadows, no outlines.
- **Below 24 px use the favicon**, not a shrunken lockup.
- **The wordmark is always uppercase** with wide tracking, never re-typed in
  another face — use the SVG.

## Palette

| Token | Hex | Where |
|---|---|---|
| Ink | `#0A0A0A` | Page background (dark), text on paper |
| Panel | `#131314` | Cards, boxes, terminals |
| Line | `#2A2A27` | Hairlines, borders, dividers |
| Muted | `#8A8781` | Secondary text, units, labels |
| Paper | `#F2F1EE` | Text on dark, background (light) |
| Signal | `#E05316` | **Live state only** |

Signal is the whole discipline. It marks the link that is up, the aircraft that
is armed, the packet in flight — never a heading, a border or a button that
merely exists. If it is everywhere, it means nothing.

Light mode swaps Ink and Paper, and uses `#FFFFFF` panels with `#DAD8D3` lines
and `#6E6B66` muted text.

## Type

- **Wordmark and headings:** a neutral grotesk (Helvetica Neue, Inter, Arial),
  600 weight, uppercase, tracked out. Headings state a thing; they don't sell it.
- **Data:** monospace (SF Mono, Menlo, Consolas). Anything a machine produced —
  ports, frequencies, counts, RSSI — is set in mono so it reads as measurement.
- **Body:** the same grotesk at normal weight and tracking.

## Applying it

The web pages served by `radio/phone_relay.py` and the camera stream should use
these tokens rather than inventing their own, so what runs on the bench looks
like what is written about it. The diagram generator in this repo's history shows
the shapes: 1.5 px hairlines, no rounded corners, labels in mono, a single
accent stroke for the radio link.
