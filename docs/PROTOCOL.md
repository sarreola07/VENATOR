# Venator C2 protocol (v1)

The command-and-control protocol between the **laptop client** (`ground/gcs_client.py`)
or the **handheld remote** (`radio/firmware/Venator_Remote`) and the **Jetson server**
(`drone/c2_server.py`). Defined once in [`radio/protocol.py`](../radio/protocol.py)
and imported by both, so they can never drift.

## Wire format

- One JSON object per line, newline-delimited (`\n`).
- Kept small so each message fits one LoRa packet (< ~200 bytes).
- Every message has `t` (type) and `seq` (sequence number).

Example:

```
{"t":"HELLO","seq":1}
{"t":"HELLO_ACK","seq":1,"proto":1,"armed":false,"gps":"no fix","batt":11.4}
```

## Message types

| Type | Direction | Fields | Meaning |
|---|---|---|---|
| `HELLO` | client → jetson | — | link request (handshake) |
| `HELLO_ACK` | jetson → client | `proto,armed,gps,batt,auth,indoor?` | link up + status. `auth` says whether the drone signs, so a one-sided key is reported, not silent; `gps` reads `indoor: position OK` / `indoor: no position` when the server runs with `--indoor` |
| `GET_MENU` | client → jetson | — | request the mission list |
| `MENU` | jetson → client | `item,last` | one mission `{id,name,needs,gps}`; streamed one per packet, `last:true` on the final |
| `RUN` | client → jetson | `id` | run a mission |
| `ACK` | jetson → client | `accepted,reason` / `i` / `uploaded` | accepted/rejected reply |
| `DONE` | jetson → client | `id,result` | mission finished |
| `WP_BEGIN` | client → jetson | `count` | start a waypoint upload |
| `WP` | client → jetson | `i,lat,lon,alt` | one waypoint |
| `WP_END` | client → jetson | — | end of upload |
| `FLY_REQ` | client → jetson | — | ask to fly the uploaded mission; answered `ACK{accepted, confirm_required, reason}` and arms nothing |
| `CONFIRM` | client → jetson | — | launch the flight prepared by `RUN 4/5/8` or `FLY_REQ`; the gates are re-checked first |
| `STOP` | client → jetson | — | in flight (Mission 2 and the hover): land in place now. Otherwise: lands an armed drone no flight is watching |
| `PING`/`PONG` | either | — | liveness |
| `ABORT` | client → jetson | — | in flight: the mission's failsafe now (RTL; the hover lands). Before `CONFIRM`: cancel the prepared flight |
| `LOG` | jetson → client | `text` | line to display |
| `STATUS` | jetson → client | `armed,alt,mode,phase?,rtl,…` | in-flight status, about once a second |
| `LINK` | stick → its own host, serial only | `rssi,snr` | the bridge firmware's reading of the last packet it received. Never goes on the air; `radio/serial_link.py` folds it into its counters and no caller sees it |

## Flows

**Handshake / "connection established":** client sends `HELLO`, waits for
`HELLO_ACK`. That reply is the moment the menu is requested.

**Menu:** client sends `GET_MENU`; the server streams one `MENU` message per
mission (each fits a LoRa packet), the last flagged `last:true`. A full menu in a
single message would exceed the ~255 B LoRa / 240 B firmware limit.

**Run a mission:** `RUN{id}` → `ACK{accepted}`; if accepted, a later `DONE`.
Flight missions are rejected (`accepted:false, reason`) until PX4's own checks
pass (e.g. a GPS fix).

**Launch a flight:** flights (`RUN 4`, `5`, `8`, and `FLY_REQ`) answer
`ACK{accepted:true, confirm_required:true}` and arm nothing. A second message,
`CONFIRM`, launches it. `ABORT` instead cancels it, and a flight not
confirmed within 60 s lapses by itself, so a stray `CONFIRM` later launches
nothing.

**Waypoint upload:** `WP_BEGIN{count}` → `WP{i,lat,lon,alt}` × N (each ACKed) →
`WP_END` → `ACK{uploaded,rejected}`. The Jetson validates coordinates, builds a
PX4 mission, and (Phase 5, with GPS) flies it.

## Reliability

LoRa drops packets and the sticks are half-duplex, so the link is built to lose
any single packet without losing the session. What each end does, as the code
does it (`radio/serial_link.py`, `drone/c2_server.py`, `ground/gcs_client.py`,
`radio/firmware/Venator_Remote`):

- **Opening a port waits for the stick.** The Heltec reboots when its serial
  port is opened and prints `Venator LoRa transceiver ready` about two seconds
  later. Every open, including a reconnect, waits for that banner (or 2.5 s),
  so nothing is written into a rebooting stick. This was the usual cause of a
  session that never linked at all.
- **Commands are retransmitted with the same `seq`.** The laptop resends
  `HELLO`, `GET_MENU`, `RUN`, `WP_*`, `FLY_REQ` every 2 s until the reply comes;
  the handheld resends `RUN` every 4 s, three times. `CONFIRM` is resent when
  the drone has said nothing for 6 s (three tries), `STOP` and `ABORT` every 2 s
  until a `STATUS`, `LOG` or `DONE` shows they arrived (five tries).
- **The server dedupes by `(type, seq)`.** For `RUN`, `CONFIRM`, `FLY_REQ` and
  `WP_*` it remembers the first few replies for 30 s and answers a repeat from
  that cache, so a retransmit never runs a motor test or prepares a flight
  twice. `seq 0` carries no identity and is never deduped.
- **Replies are matched by `seq`.** A reply with another `seq` is someone
  else's and is skipped; `seq 0` (a server-initiated `LOG`, `STATUS`, `DONE`)
  is always accepted.
- **A flight's `DONE` is repeated.** The ground keeps pinging after a flight;
  for 15 s the drone sends the `DONE` again with the next `PONG`s (three at
  most), so a lost `DONE` does not leave the operator waiting.
- **`STATUS` rides on the `PONG`.** In flight the ground pings every second
  and the drone answers; when a status is due it goes right after the `PONG`,
  while the ground is listening. Two free-running one-second timers used to
  collide about a third of the time. Only after two quiet intervals is a
  `STATUS` sent unsolicited (the handheld pings every 5 s when idle).
- **Link loss.** In flight, 4 s without a `PING` is the failsafe (RTL; the
  hover lands). The flight loop drains every queued message each tick, so
  stale pings that piled up during a blocking arm cannot make a dead link look
  alive.
- **Lines are at most 240 bytes after signing.** The firmware cuts longer
  lines and the receiver drops the broken JSON, so the sender refuses them
  instead. Error text is already cut to fit.
- **Nothing on the wire can stop a loop.** A garbled packet, a non-hex
  signature tag, or junk with no newline is dropped and counted; the input
  buffer is capped at 4 KB.
- **Timers are monotonic.** The Jetson has no RTC battery and its clock steps
  when NTP arrives; that step no longer looks like link loss.

Both ends keep counters (`SerialLink.stats()`: received, bad, rejected, sent,
dropped, banner seen, time since the last packet, and RSSI/SNR when the stick
reports them). The laptop prints a diagnosis from them when a handshake fails;
the server logs them every minute while traffic flows and in the `7 Drone
status` reply.

## Firmware note (Phase 3)

The bidirectional Heltec firmware should be a **transparent line bridge**: send
each serial line over the air verbatim and print each received payload to serial
verbatim. Then `SerialTransport` in the client speaks this protocol directly with
no wrapping. (The original one-way firmware wrapped lines as `{"msg":"..."}`;
the transparent bridge drops that wrapper.)
