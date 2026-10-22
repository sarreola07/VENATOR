# Mission

> **Venator is an autonomous aircraft commanded over a radio link that needs no
> infrastructure — no internet, no cellular, no ground control software — to
> search an area, find the people in it, and stay in contact when the network is
> gone.**

*Fence an area, sweep it, find who is in it, come home.*

## Why it matters

Every tool that matters in a disaster assumes a network that a disaster removes.
Phones need a tower, drones need a ground station on Wi-Fi, mapping needs the
internet. When the infrastructure is down — or was never there, over open land,
at night, past the last road — the equipment that was supposed to help stops
being equipment and becomes weight.

Venator treats that as the normal operating condition rather than the exception.
There is no tower to lose, because there was never a tower. A laptop, a 915 MHz
radio and the aircraft are the whole system.

## Three pillars

### 1. Off-grid command and control

A laptop talks to the aircraft over 915 MHz LoRa. The ground station sends a
command, the Jetson runs it against the flight controller, and the reply comes
back the same way. No QGroundControl, no GUI, no internet.

The link is not a diagram. It is validated on hardware: 20 of 20 packets, 0%
loss, about 435 ms round trip, and motor tests commanded from a handheld remote
with no network of any kind — no laptop, no phone, no access point. The
operator holds a radio with a knob and a screen, and the aircraft answers.

`drone/c2_server.py` · `radio/protocol.py` · `radio/firmware/Venator_Remote`

### 2. Search and rescue

Fence an area. Sweep every metre inside it. The OAK-D Pro reads spatial depth,
so a person is found by shape and distance rather than by a radio they are
carrying — which matters, because the people who most need finding are the ones
with nothing on them.

Hold station over someone who is not moving, send their coordinates home, and
keep going. Follow someone who is moving. Then return with the track and every
detection.

`drone/wildlife/` · `assets/brand/conops-light.svg`

### 3. Off-grid communication

The radio that flies the aircraft also carries text. `radio/phone_relay.py`
passes messages between two phones over the same 915 MHz link, with no cell
service in between — so the team searching stays in contact with the team
coordinating, on hardware already in the air.

A second handheld runs on entirely different silicon (a Raspberry Pi Pico with
a REYAX RYLR998, speaking the same protocol), which is the proof that the link
is a protocol rather than one vendor's radio.

`radio/phone_relay.py` · `radio/firmware/Pico_Gateway` · `assets/brand/mesh-light.svg`

## Saying it out loud

The one-sentence version, for someone who asks what it is:

> It is a drone you can fly and talk through when there is no internet, no cell
> service and no ground station — to search an area and find the people in it.

The nine-word version, which is the one worth remembering:

> **Fence an area, sweep it, find who is in it, come home.**

---

For engineering status — what is built, what is bench-tested, and what is next —
see [ROADMAP.md](ROADMAP.md). This document is about why the project exists;
that one is about where it is.
