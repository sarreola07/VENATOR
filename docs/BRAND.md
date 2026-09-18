# Venator — mark, palette, type

The look is deliberately plain: near-black, warm greys, one accent that only
appears when something is live. Anything that reads as decoration is wrong.

These are our own marks and colours, in the same register as the defence-tech
houses this borrows its tone from. Nobody else's logo, wordmark or brand colour
is reproduced here, and none should be added.

## The mark

Two swept wings over a heavy V: an aircraft seen head-on, and the letter the
project is named for. It is built to be recognised across a room at a
symposium, so it is solid, symmetrical and monochrome — no strokes to thin out,
no accent inside the mark.

| File | Use |
|---|---|
| `assets/brand/lockup-dark.svg` | Mark + wordmark on dark. README hero, slides. |
| `assets/brand/lockup-light.svg` | Mark + wordmark on paper or a light UI. |
| `assets/brand/mark-dark.svg`, `mark-light.svg` | Mark alone, 24 px and up. |
| `assets/brand/favicon.svg` | 16–32 px. The V alone; the wings close up below ~20 px. |
| `assets/brand/social-preview.png` | 1280×640 card for GitHub, Slack, chat unfurls. |
| `assets/brand/system-dark.svg`, `system-light.svg` | The system diagram, animated. See **Motion**. |
| `assets/brand/conops-dark.svg`, `conops-light.svg` | Concept of operations — Mission 2 end to end, animated. |
| `assets/brand/patrol-*.svg`, `mesh-*.svg` | Waypoint patrol and the message net, animated. |
| `assets/brand/hero-*.svg` | The README hero — a system self-test, ten seconds cold. Dark in both schemes. |
| `assets/brand/phases-*.svg` | Phase status for the roadmap. **Generated** — run `python3 tools/gen_phases.py` after changing a phase's state; CI fails if it is stale. |
| `assets/brand/cta-*.svg` | The animated *System overview* button. Wrap in `<a>`; GitHub strips CSS from README HTML, so the motion has to live inside the image. **The one deliberate exception to the rules below** — see *Motion*. |
| `assets/brand/lockup-stacked-*.svg` | Mark above the wordmark — banners, posters, title slides. |
| `assets/brand/png/` | High-resolution PNG exports of all of the above. |

Use the **SVG** anywhere that renders it — README, web pages, slides that accept
it. It stays sharp at any size and is a few kilobytes. Use a **PNG** when
something refuses SVG: a print shop, a poster or banner, Google Slides, a
conference submission form.

| PNG | Size | For |
|---|---|---|
| `venator-mark-{dark,light}-{512,2048}.png` | up to 2048×1434 | The mark alone |
| `venator-lockup-{dark,light}-{1600,3200}.png` | up to 3200×572 | Horizontal lockup, slide headers |
| `venator-lockup-stacked-{dark,light}-{1200,2400}.png` | up to 2400×1560 | Banners, posters, table cards |
| `venator-icon-{white,black}-{32,180,512}.png` | square | App icons, avatars, favicons |
| `social-preview-{1280,2560}.png` | 1280×640, 2560×1280 | Link previews |

Every PNG except the social card has a **transparent background**, so it drops
onto any colour. "dark"/"white" means the ink is near-white, for dark
backgrounds; "light"/"black" means near-black ink, for paper.

Rules that keep it recognisable:

- **Clear space** of at least the mark's own width on every side.
- **Never recolour the mark.** Ink or paper, nothing else. No gradients, no
  shadows, no outlines, and never the accent — that colour reports state, and
  the mark is not a state.
- **Below 24 px use the favicon**, not a shrunken lockup or mark.
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

## Motion

The system diagram is live. One eight-second cycle carries a command from GROUND
to the DRONE over 915 MHz, on to the AIRFRAME over MAVLink, and the reply back
the same way — the round trip the protocol actually makes. A caption underneath
names each leg, then settles on the resting line.

Motion follows the same rule as Signal: it reports something, or it does not
happen. A packet moves because a packet moved. Nothing drifts, spins or breathes
to fill the space.

Two things to know before editing `system-*.svg`:

- **Everything that moves is inside `#packets` and `#ticker`.** A reader with
  `prefers-reduced-motion: reduce` gets the plain diagram, and so does any
  renderer that ignores SMIL. The static artwork underneath is unchanged, which
  is what makes the animation safe to drop.
- **The glow is dark-mode only.** A blurred dark dot on paper is a drop shadow,
  which is on the banned list above. On white, a packet is a crisp dot inside an
  expanding ring, and a box reports an arrival with a heavier border rather than
  a brighter one.

The README shows the light diagram in both colour schemes; `system-dark.svg` is
there for dark slides and dark UI.

### The one exception

`cta-*.svg` breaks almost everything above on purpose: it glows, it has
scanlines, it glitches, and the accent is decoration rather than state. It is a
button whose entire job is to be noticed on a page somebody is scrolling past,
and it is the only asset allowed to work that way. Its panel stays dark in both
colour schemes, because neon needs something to burn against.

Nothing else adopts this treatment. If a second surface ever needs it, that is a
decision to take deliberately, not by copying this file.

## Applying it

The web pages served by `radio/phone_relay.py` and the camera stream should use
these tokens rather than inventing their own, so what runs on the bench looks
like what is written about it. The diagram generator in this repo's history shows
the shapes: 1.5 px hairlines, no rounded corners, labels in mono, a single
accent stroke for the radio link.
