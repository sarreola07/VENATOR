# LoRa firmware (Heltec WiFi LoRa 32 V3)

## What this is

`LoRa_Transceiver/LoRa_Transceiver.ino` is a **half-duplex transparent bridge**:
a line sent to USB serial goes out over 915 MHz LoRa verbatim, and any packet
received over the air is printed to USB serial verbatim. This lets the Venator
C2 protocol (newline-delimited JSON, see [../docs/PROTOCOL.md](../docs/PROTOCOL.md))
flow in **both directions**.

It replaces the original one-way sketches (`LoRa_TX.ino` + `LoRa_RX.ino`), which
could only send *or* receive — not enough for the "Jetson sends the menu, laptop
sends the choice" handshake.

## Flash it on BOTH sticks

Both the Jetson-side stick and the laptop-side stick run the **same** sketch.

1. Arduino IDE → install the **Heltec ESP32** board package and the **Heltec
   ESP32 LoRaWan** library (same as your originals — they already compile).
2. Board: **Heltec WiFi LoRa 32(V3)**.
3. Open `LoRa_Transceiver/LoRa_Transceiver.ino`, select the stick's port, Upload.
4. Repeat for the second stick.

Radio parameters (must be identical on both, and they are): 915 MHz, SF7,
syncword `0x12`, 14 dBm.

## Test the two-way link (before touching the drone)

1. Plug both sticks into one computer (or two).
2. Open a serial monitor on each at **115200 baud**, line ending = **Newline**.
3. Type a line into stick A's monitor and press Enter → it appears on stick B.
4. Type a line into stick B → it appears on stick A.

If both directions work, the link is ready for the GCS client and the Jetson
C2 server. A quick protocol sanity check: type

```
{"t":"HELLO","seq":1}
```

into one monitor; the other should print that exact line.

### Or test it without a human at each keyboard

`../link_test.py` runs the same check from the command line and exits `0` or `1`
instead of leaving you to judge what scrolled past — which is what you want over
SSH, in a script, or when a Claude session is driving one end:

```bash
python3 link_test.py --list                  # which port is which stick
python3 link_test.py --listen                # on one machine
python3 link_test.py --send --count 20       # on the other: RTT + loss summary
python3 link_test.py --chat                  # on both: type lines back and forth
```

Close the Arduino Serial Monitor first — only one program can hold a stick's
port at a time. For the two-computer workflow around this, see
[../docs/DEV_SETUP.md](../docs/DEV_SETUP.md).

## The onboard OLED

Each stick's 128x64 panel shows link health, so you can tell at the field whether
the radio is alive without attaching a computer:

```
Venator LoRa 915
TX 12   RX 11
RSSI -47  SNR 9
LINK UP
{"t":"PONG","seq":11
```

- **TX / RX** — packets sent and received since power-up. A TX count that climbs
  while the peer's RX count does not is a one-way link.
- **RSSI / SNR** — signal strength (dBm) and margin (dB) of the last packet.
  These come straight from the radio's `onRxDone`, which previously discarded
  them. Walk the field watching RSSI to find your real range before you fly.
- **LINK UP** — shown while a packet arrived in the last 5 s; otherwise it
  counts the seconds of silence, so a dead link is obvious.
- **Bottom line** — the first 21 characters of the last packet received,
  non-printable bytes shown as `.`.

### Notes

- **The panel is powered from the `Vext` rail, which is off at boot.** If you
  adapt this code and the screen stays dark, that is almost always the cause —
  `VextON()` must run before `display.init()`.
- The driver (`HT_SSD1306Wire.h`) ships with the Heltec ESP32 board package you
  already installed for `LoRaWan_APP.h`. Nothing new to add.
- Drawing is throttled to 4 Hz and skipped while transmitting. A full frame is
  ~20-30 ms of blocking I2C, and stalling `Radio.IrqProcess()` costs packets.
- If the text reads upside down, uncomment `display.flipScreenVertically()` in
  `setup()`.
- **To disable it entirely**, set `#define USE_OLED 0` at the top of the sketch.
  That build is byte-for-byte the radio-only behaviour, with no display code
  compiled in — useful for isolating a fault to the radio.

> Not compiled or flashed here (no ESP32 toolchain on the Jetson). Flash one
> stick first and confirm the two-terminal test still passes before doing the
> second, so you always have one known-good stick to test against.

## Why a transparent bridge (not the old `{"msg":...}` wrapper)

The original TX sketch wrapped each line as `{"msg":"..."}`. The transceiver
sends lines through untouched so the JSON protocol arrives exactly as sent —
the client and Jetson server do all the parsing. Keep the radio a dumb pipe;
the intelligence lives on the computers at each end.
