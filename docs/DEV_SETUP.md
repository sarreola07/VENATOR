# Developing across two computers (and two Claude sessions)

How to work on the Venator C2 link when the two ends of that link are two
different machines, with a Claude session on each.

## First: which Claude can see your LoRa stick?

This is the thing that catches everyone, so it goes first.

| Where Claude runs | Sees your USB LoRa stick? |
|---|---|
| **Claude Code on the web** (claude.ai/code) | **No.** Every web session runs in a throwaway Linux container in the cloud, with a fresh `git clone` of this repo. It has no USB, no serial ports, and no route to your machine — `ls /dev/cu.*` there comes back empty. |
| **Claude Code CLI**, installed and run on your Mac | Yes — same machine, same `/dev`, same ports. |
| **Claude Code CLI**, installed and run on the second computer | Yes, likewise. |

A web session also cannot tell which computer you are typing into. The browser
is yours; the container is not. So "I'm on the Mac" changes nothing about what
a web session can reach — only about which machine you should install the CLI
on next.

**Consequence:** anything that touches the radio, the Pixhawk or the camera has
to run from a **local** Claude Code session on that machine. Install the CLI
(`npm install -g @anthropic-ai/claude-code`, or see
<https://code.claude.com/docs>) on each machine that holds hardware.

## The setup that works: one author, two hands

Three sessions, with one job each. The point is that **only one session writes
code**, so you never merge two Claudes against each other.

```
                    ┌──────────────────────────────┐
                    │  Claude Code on the web      │   writes code, pushes
                    │  (cloud container, no USB)   │   branch: claude/...
                    └───────────────┬──────────────┘
                                    │ git push
                            ┌───────┴────────┐
                     git pull│                │git pull
        ┌───────────────────▼──┐          ┌──▼───────────────────┐
        │ Mac                  │          │ Machine B            │
        │ Claude Code CLI      │          │ Claude Code CLI      │
        │ gcs_client.py        │          │ jetson_c2_server.py  │
        │ + Heltec stick       │          │ + Heltec stick       │
        └──────────┬───────────┘          └──────────┬───────────┘
                   └────────── 915 MHz LoRa ─────────┘
```

- **Web session** — reads the whole repo, writes the code, pushes to the
  feature branch. It cannot test against hardware, so it should not guess:
  give it the output your local sessions produce.
- **Mac session** — the ground station. Pulls, runs `gcs_client.py` and
  `link_test.py`, pastes the output back.
- **Machine B session** — the drone side. Pulls, runs `jetson_c2_server.py`
  and `link_test.py`. Machine B is whatever is standing in for the Jetson today
  (a Windows box, a second Mac, a Linux laptop) and becomes the real Jetson
  later without any code change.

The two local Claudes **cannot message each other.** They share exactly two
channels, and that is enough:

1. **Git** — for code. One pushes, the other pulls.
2. **The LoRa link itself** — for messages. That is what `link_test.py --chat`
   is for (below), and it is the same link the drone commands ride on.

### If both sessions need to write code

Sometimes the hardware side needs a fix on the spot. Then split ownership by
file so two Claudes never touch the same one:

| File | Owner |
|---|---|
| `gcs_client.py` | Mac session |
| `jetson_c2_server.py`, `missions.py`, `camera_publisher.py` | Machine B session |
| `c2_protocol.py`, `docs/PROTOCOL.md` | **One session at a time, never both** |
| `firmware/` | Whoever has the Arduino IDE open |

`c2_protocol.py` is the one file both ends import, and the whole point of it is
that the two ends cannot drift. Change it in one place, push, and have the other
side pull **before** it runs anything. A protocol change deployed to only one end
looks exactly like a broken radio.

Have each local session `git pull` at the start of every work block and push
small commits, so the other side is never more than a few minutes stale.

## Bring-up ladder

Do these in order. Each rung removes one variable, so when something breaks you
know which one it was.

### Rung 0 — both sticks on one computer

Flash both Heltec sticks with `firmware/LoRa_Transceiver/LoRa_Transceiver.ino`
(see [../firmware/README.md](../firmware/README.md)), plug both into the same
machine, and prove the radios talk before any networking is involved:

```bash
python3 link_test.py --list                     # find both sticks
python3 link_test.py --listen --port <port-A> & # one terminal
python3 link_test.py --send   --port <port-B>   # the other
```

You want `Link OK ✓`. If this fails, it is the radios or the firmware — nothing
further up the ladder will work.

### Rung 1 — two computers, radio only

One stick per machine, ideally in different rooms so you also learn the range.

```bash
# Machine B
python3 link_test.py --listen

# Mac
python3 link_test.py --send --count 20
```

The Mac prints per-packet round-trip times and a loss summary, and exits `0`
only if loss is within `--allow-loss` (20% by default). That exit code is what
makes it useful to a Claude session: it can run the command, read the result and
decide, with no human interpreting a scrolling serial monitor.

To send free text across, which is the quickest way to confirm a human-visible
message really crosses the gap, run this on **both** machines and type:

```bash
python3 link_test.py --chat
```

### Rung 2 — the real protocol, still no drone

`jetson_c2_server.py` defaults to a **mock flight controller**, so Machine B
needs neither a Pixhawk nor pymavlink — only `pyserial`:

```bash
# Machine B — stands in for the Jetson
python3 jetson_c2_server.py --lora-port <port> --props-off

# Mac — the real ground station
python3 gcs_client.py
```

The Mac should handshake and draw the mission menu the *server* advertises. At
this point everything except the drone is real: the protocol, the radio, both
programs. Mock missions return `ok (mock)`, and the props/GPS interlocks refuse
flight missions exactly as they will in the field.

### Rung 3 — move the server to the Jetson

Same command, real machine:

```bash
# On the Jetson
./venv/bin/python jetson_c2_server.py --props-off
```

`--lora-port` can now be left off: the Jetson resolves the stick through
`/dev/serial/by-id/`, which survives a `ttyUSB0` → `ttyUSB1` replug. Nothing on
the Mac changes — it is already talking to the finished thing.

### Rung 4 — add the Pixhawk

Add `--real` to connect the flight controller (see the main
[README](../README.md) for the props and GPS interlocks, and keep `--props-off`
until you mean it). Add `--props-on` only when you are actually flying.

## Per-machine notes

**Mac** — the stick appears as `/dev/cu.usbserial-XXXX`. Use the `cu.` name, not
the `tty.` one; `tty.*` blocks on carrier detect and will look like a dead
radio. Recent macOS has a built-in CP210x driver, so no install is normally
needed. Only `pyserial` is required on this side:

```bash
python3 -m venv venv && ./venv/bin/pip install pyserial
```

**Windows (if Machine B is a PC)** — ports are `COM3`, `COM5` and so on; check
Device Manager under Ports (COM & LPT). You may need Silicon Labs' CP210x VCP
driver. Pass the port explicitly: `--lora-port COM5`.

**Linux / Jetson** — add yourself to the `dialout` group (`setup.sh` does this)
or every port open fails with `Permission denied`.

**All three** — the Heltec reboots when a program opens its serial port, and
only one program may hold a port at a time. If a test reports nothing arriving,
the usual cause is an Arduino Serial Monitor still open on that stick.

## What to hand the web session

A cloud session cannot run any of the above, so it is only as good as what you
paste back. The useful things are the full `link_test.py` summary block, the
server's log lines, and the exact error text — not a description of them. With
those it can find the bug; without them it is guessing at hardware it cannot see.
