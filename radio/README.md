# radio/ — the 915 MHz link

Everything that carries bytes between the drone and the ground: the wire
format, the bench tools, and the firmware on the sticks themselves. Both ends
of every link in this repo speak what is defined here.

| File | What it is |
|---|---|
| `protocol.py` | The Venator C2 wire format: one JSON object per line. Shared by the C2 server, the ground client and the tools below. See [../docs/PROTOCOL.md](../docs/PROTOCOL.md). |
| `link_test.py` | Two-ended link check: ping/pong with round-trip times and a pass/fail exit code. |
| `phone_relay.py` | A chat page in a browser; each message crosses the radio and is confirmed by the far end. |
| `listener.py` | Minimal serial listener, used by the mission menu to receive LoRa commands. |
| `firmware/` | The sketch on the Heltec sticks — see [firmware/README.md](firmware/README.md). |

## The hardware

Two **Heltec Wireless Stick V3** boards (ESP32-S3 + SX1262, 0.49" 64x32 OLED).
They appear as a CP2102 USB-serial port: `/dev/ttyUSB0` on Linux,
`/dev/cu.usbserial-*` on macOS. Radio settings are identical on both and must
stay that way: **915 MHz, SF7, syncword 0x12, 14 dBm**.

## Check a link

```bash
python3 radio/link_test.py --list                 # which port is which stick
python3 radio/link_test.py --listen               # on one machine
python3 radio/link_test.py --send --count 20      # on the other: RTT + loss
```

Exit code 0 means the loss was within `--allow-loss` (20% by default), so it
works in scripts. `--chat` carries typed lines both ways instead.

## Send messages from a browser

```bash
python3 radio/phone_relay.py --names Jetson       # one address per stick
```

It prints a web address per stick. Open it on that computer (`localhost`) or
from a phone on the same Wi-Fi. A message shows **delivered** once the far end
confirms it over the air; after three tries without confirmation it says so.
With both sticks on one computer it runs both ends at once.

The address ends in `?k=` and an access key, because the page is served on every
interface and anyone on the Wi-Fi can reach the port. **A fresh key is generated
each start**, so a bookmark from last time will be refused — copy the address the
relay just printed, or pin one with `--key`:

```bash
python3 radio/phone_relay.py --names Jetson --key ourflight
```

Only one program can hold a stick's serial port, so stop the relay, any serial
monitor, `ground/gcs_client.py`, and on the Jetson the C2 service, before using
another tool on it.

If a stick is unplugged or its USB re-enumerates, the tools here say so once and
reconnect on their own when it comes back — there is no need to restart them.
