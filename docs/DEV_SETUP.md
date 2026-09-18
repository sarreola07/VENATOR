# Developing across two computers (and two Claude sessions)

How to work on the Venator C2 link when the two ends of that link are two
different machines — an **Ubuntu box** standing in for the Jetson, and a
**MacBook** as the ground station — with a Claude session on each.

Using Ubuntu for the drone side is deliberate and worth the trouble: the Jetson
Orin Nano runs Ubuntu 24.04, so the stand-in shares its serial naming
(`/dev/serial/by-id/`, `/dev/ttyUSB0`), its `dialout` permission model and its
venv layout. Rung 3 below — moving the server onto the real Jetson — is then
close to a no-op, which is the whole point.

## First: which Claude can see your LoRa stick?

This is the thing that catches everyone, so it goes first.

| Where Claude runs | Sees your USB LoRa stick? |
|---|---|
| **Claude Code on the web** (claude.ai/code) | **No.** Every web session runs in a throwaway Linux container in the cloud, with a fresh `git clone` of this repo. No USB, no serial ports, no route to your machine — `ls /dev/ttyUSB*` there comes back empty. |
| **Claude Code CLI** on the MacBook | Yes — same machine, same `/dev`, same ports. |
| **Claude Code CLI** on the Ubuntu box | Yes, once you are in the `dialout` group. |

A web session also cannot tell which computer you are typing into. The browser
is yours; the container is not. So "I'm on the MacBook" changes nothing about
what a web session can reach — only which machine you install the CLI on.

**Consequence:** anything touching the radio, the Pixhawk or the camera runs
from a **local** Claude Code session on that machine. Install the CLI
(`npm install -g @anthropic-ai/claude-code`, or see
<https://code.claude.com/docs>) on both the Ubuntu box and the MacBook.

## Who plays which role

```
                     ┌──────────────────────────────┐
                     │ Claude Code on the web       │  writes code,
                     │ (cloud container, no USB)    │  pushes a branch
                     └───────────────┬──────────────┘
                                     │ git push
                    ┌────────────────┴────────────────┐
           git pull │                                 │ git pull
      ┌─────────────▼────────────┐      ┌─────────────▼────────────┐
      │ Ubuntu box               │      │ MacBook                  │
      │ "the Jetson, for now"    │      │ the ground station       │
      │ drone/c2_server.py       │      │ ground/gcs_client.py     │
      │ Heltec on /dev/ttyUSB0   │      │ Heltec on /dev/cu.*      │
      └─────────────┬────────────┘      └─────────────┬────────────┘
                    └────────── 915 MHz LoRa ─────────┘
```

**Ubuntu box → the drone side.** Same OS as the Jetson, and it stays on the
bench the way the Jetson stays on the airframe.

**MacBook → the ground station.** It is the portable one, so it is the machine
that actually goes to the field, and it stays the ground station forever — it
never becomes the Jetson.

Pick this assignment and keep it. Swapping mid-project costs you an afternoon of
"which end was stale?"

## Two Claude sessions, one codebase

Three sessions, one job each. The point is that **only one session writes
code**, so you never merge two Claudes against each other.

- **Web session** — reads the whole repo, writes the code, pushes to the feature
  branch. It cannot test against hardware, so do not let it guess: paste the
  real output back.
- **Ubuntu session** — pulls, runs the server, reports what it logged.
- **MacBook session** — pulls, runs the client, reports what it logged.

The two local Claudes **cannot message each other.** They share exactly two
channels, and that is enough:

1. **Git** — for code. One pushes, the other pulls.
2. **The LoRa link itself** — for messages. That is what `radio/link_test.py --chat`
   is for, and it is the same link the drone commands ride on.

### If both sessions need to write code

Sometimes the hardware side needs a fix on the spot. Then split ownership by
file, so two Claudes never touch the same one:

| File | Owner |
|---|---|
| `ground/gcs_client.py` | MacBook session |
| `drone/c2_server.py`, `drone/missions.py`, `drone/camera_publisher.py` | Ubuntu session |
| `radio/protocol.py`, `docs/PROTOCOL.md` | **One session at a time, never both** |
| `radio/firmware/` | Whoever has the Arduino IDE open |

`radio/protocol.py` is the one file both ends import, and its whole purpose is that
the two ends cannot drift. Change it in one place, push, and pull on the other
**before** running anything. A protocol change deployed to only one end looks
exactly like a broken radio.

Have each local session `git pull` at the start of every work block and push
small commits, so neither side is more than a few minutes stale.

## Bring-up ladder

Do these in order. Each rung removes one variable, so when something breaks you
know which one it was.

### Rung 0 — both sticks in one computer

Flash both Heltec sticks with `radio/firmware/LoRa_Transceiver/LoRa_Transceiver.ino`
(see [../radio/firmware/README.md](../radio/firmware/README.md)), plug both into the *same*
machine, and prove the radios talk before a second computer is involved:

```bash
python3 radio/link_test.py --list                            # names both sticks
python3 radio/link_test.py --listen --port /dev/ttyUSB0 &    # one terminal
python3 radio/link_test.py --send   --port /dev/ttyUSB1      # the other
```

You want `Link OK ✓`. If this fails it is the radios or the firmware, and
nothing further up the ladder will work.

### Rung 1 — two computers, radio only

One stick per machine, ideally in different rooms so you also learn the range.

```bash
# Ubuntu box
python3 radio/link_test.py --listen

# MacBook
python3 radio/link_test.py --send --count 20
```

The Mac prints per-packet round-trip times and a loss summary, and exits `0`
only if loss is within `--allow-loss` (20% by default). That exit code is what
makes this useful to a Claude session: it can run the command, read the verdict
and act, instead of a human interpreting a scrolling serial monitor.

To carry free text across — the quickest way to confirm a human-visible message
really crosses the gap — run this on **both** machines and type:

```bash
python3 radio/link_test.py --chat
```

### Rung 2 — the real protocol, still no drone

`drone/c2_server.py` defaults to a **mock flight controller**, so the Ubuntu
box needs neither a Pixhawk nor pymavlink — only `pyserial`:

```bash
# Ubuntu box — standing in for the Jetson
python3 drone/c2_server.py --props-off

# MacBook — the real ground station
python3 ground/gcs_client.py
```

The Mac should handshake and draw the mission menu the *server* advertises.
Everything except the drone is now real: the protocol, the radio, both programs.
Mock missions return `ok (mock)`, and the props/GPS interlocks refuse flight
missions exactly as they will in the field.

### Rung 3 — move the server to the Jetson

This is where the Ubuntu choice pays off. Same command, real machine:

```bash
./venv/bin/python drone/c2_server.py --props-off
```

`--lora-port auto` resolves through `/dev/serial/by-id/` on both boxes, which
survives a `ttyUSB0` → `ttyUSB1` replug. Nothing on the MacBook changes.

What genuinely differs between your Ubuntu box and the Jetson: the Jetson is
arm64 (so pip fetches different wheels), and it is the only one with the Pixhawk
and the OAK-D attached. The serial layer, the permissions and the code are the
same.

### Rung 4 — add the Pixhawk

Add `--real` to connect the flight controller. Keep `--props-off` until you mean
it; add `--props-on` only when you are actually flying. See the main
[README](../README.md) for the interlocks.

## Per-machine notes

### Ubuntu box

```bash
bash setup.sh          # dialout group + venv; safe with no Pixhawk attached
```

`setup.sh` adds you to `dialout`, which covers both the Pixhawk (`/dev/ttyACM*`)
and the LoRa stick (`/dev/ttyUSB*`). **Log out and back in** for that to take
effect, or every port open fails with `Permission denied`.

If you only want the C2 server and the link test, `pyserial` alone is enough —
`pymavlink` matters only for `--real`.

### MacBook

The stick appears as `/dev/cu.usbserial-XXXX`. Use the `cu.` name, **not** the
`tty.` one: `tty.*` blocks waiting on carrier detect and looks exactly like a
dead radio. Recent macOS usually drives the CP2102 with no install; if no
`/dev/cu.usbserial-*` shows up, add Silicon Labs' CP210x VCP driver.

```bash
python3 -m venv venv
./venv/bin/pip install pyserial        # the client side needs nothing else
./venv/bin/python radio/link_test.py --list
```

### Both

The Heltec reboots when a program opens its serial port, and only one program
may hold a port at a time. If a test reports nothing arriving, the usual cause
is an Arduino Serial Monitor still open on that stick — or a previous run of the
server you forgot to stop, which holds the port exclusively and makes the next
one fail with `Could not exclusively lock port`.

> A Windows PC also works as either end — `radio/link_test.py --list` names the `COM`
> ports, `--lora-port auto` finds the stick by USB ID, and CI already builds
> `VenatorGCS.exe`. Run Claude Code in PowerShell rather than WSL, which cannot
> see COM ports without `usbipd-win`.

## What to hand the web session

A cloud session cannot run any of the above, so it is only as good as what you
paste back. The useful things are the full `radio/link_test.py` summary block, the
server's log lines, and the exact error text — not a description of them. With
those it can find the bug; without them it is guessing at hardware it cannot see.
