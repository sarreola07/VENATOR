# Security

Venator is a bench and research project. It is published so the work can be read
and reused, not as a hardened product. This page records what is known to be
weak, so nobody has to rediscover it by reading the source — and so the aircraft
is not flown somewhere it should not be on the assumption that the link is safe.

Everything here is derivable from the code in this repo. None of it is a secret.

## Known limitations

### 1. The command link is not authenticated by default — **critical**

Authentication exists but is **off until you create a key** — see "Turning
authentication on" below. Until then, `drone/c2_server.py` acts on any protocol
message that arrives on its serial port, with no identity and no signature:

```python
if t == p.RUN:        server.run_and_report(msg, link.send)
elif t == p.CONFIRM:  server.run_mission1/2(...)
```

LoRa is a broadcast medium, and the radio parameters are published in this repo
because both ends must agree on them — 915 MHz, SF7, syncword `0x12`, in
[`radio/firmware/LoRa_Transceiver/LoRa_Transceiver.ino`](../radio/firmware/LoRa_Transceiver/LoRa_Transceiver.ino).

**Impact.** Any transmitter within radio range that speaks this protocol is
indistinguishable from the operator's own ground station. That covers arming and
launching, and it covers interrupting a flight that is already underway.

**The two-step arm gate is not a security control.** `RUN` followed by `CONFIRM`
exists so that a single mistaken keypress cannot launch a hexacopter. Both steps
arrive over the same unauthenticated channel, so it stops an accident, not a
person. It was never designed to do more than that.

**What limits the exposure today**

- The server defaults to a mock flight controller with props off; `--real` and
  `--props-on` are both opt-in.
- PX4's own pre-arm checks still apply, including the GPS fix requirement.
- An attacker needs to be within LoRa range, with the right hardware, at the
  right time.

None of those are access control. The first two are off in field configuration,
which is the point of the project.

**Operational guidance until this is fixed**

- Treat the link as open. Fly where an unexpected command could not hurt anyone.
- Keep the aircraft in sight and the transmitter in reach; manual RC override and
  the physical kill path are the real controls right now.
- Do not leave a `--real --props-on` server running unattended.

### Turning authentication on

[`radio/auth.py`](../radio/auth.py) signs every message with a truncated
HMAC-SHA256 over its canonical form, plus a per-message nonce. A receiver with a
key drops anything unsigned, tampered with, replayed, or signed with a different
key, before it reaches the dispatcher. Signing lives in
[`radio/serial_link.py`](../radio/serial_link.py), so every tool that opens a
stick gets it.

**It is off until a key exists**, and with no key the link behaves exactly as it
always did. That is deliberate: it means the code could ship without a flag day.
To switch it on, on **both** machines:

```bash
python3 radio/auth.py --init     # writes ~/.venator/key, mode 0600
python3 radio/auth.py            # shows whether a key is present
```

Copy the file the first machine produced to the same path on the second — the
key must be identical. Restart both ends. Until both have the same key, the end
that has one will reject the other's messages and say so.

The server and the client each state which mode they are in at startup. If you
do not see the link reported as authenticated, it is not.

**What this does not cover.** A packet captured and replayed *later* is refused
only while its nonce is still in the receiver's window (the last 512 messages).
A determined attacker who recorded a `CONFIRM` and replayed it after a restart
would get past that. The props and GPS gates, PX4's own pre-arm checks and
manual RC override remain the other layers. Sender identity — which would let
the arm gate remember which station armed it — is open decision 5 in
[ROADMAP.md](ROADMAP.md).

### 2. Radio traffic is not encrypted — **medium**

Everything on the link is plaintext, including the chat carried by
`radio/phone_relay.py`. Anyone in range with a matching radio can read it.
Separate from the point above: authentication would stop an outsider sending
commands, and would still leave traffic readable.

### 3. Message addressing — **open design issue**

Nothing in the protocol says who a message is from. Beyond the point above, this
has two practical effects once more than two radios are on the channel: delivery
confirmation stops being trustworthy, and one station's `RUN` can be completed by
a different station's `CONFIRM`. The reasoning is written up under "A third
radio: what it takes" in [ROADMAP.md](ROADMAP.md).

## Fixed

| Date | Issue |
|---|---|
| 2026-09-18 | `phone_relay.py` defaulted to a 4-digit access key — 10,000 possibilities on a port bound to every interface. Now 8 random URL-safe characters, compared with `secrets.compare_digest`, with a growing delay after a wrong key. |
| 2026-09-18 | All three serial transports could hold a dead port after a stick re-enumerated, one of them silently. They now report it once and reconnect. Availability rather than access, but it is the difference between a link that is down and one that looks up. |

## Reporting something

Open an issue, or for anything you would rather not post publicly, contact the
repository owner through their GitHub profile. This is a personal project with
no security team and no response-time commitment.

## Scope note

The camera stream and the relay both bind to every interface so a phone on the
same Wi-Fi can reach them. On the Jetson's own hotspot that is the intent. On a
shared or untrusted network it means anyone on that network can reach the port,
and the relay's access key is the only thing in the way.
