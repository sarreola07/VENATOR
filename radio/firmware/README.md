# LoRa firmware (Heltec Wireless Stick V3)

## What this is

`LoRa_Transceiver/LoRa_Transceiver.ino` is a **half-duplex transparent bridge**:
a line sent to USB serial goes out over 915 MHz LoRa verbatim, and any packet
received over the air is printed to USB serial verbatim. This lets the Venator
C2 protocol (newline-delimited JSON, see [../docs/PROTOCOL.md](../../docs/PROTOCOL.md))
flow in **both directions**.

It replaces the original one-way sketches (`LoRa_TX.ino` + `LoRa_RX.ino`), which
could only send *or* receive — not enough for the "Jetson sends the menu, laptop
sends the choice" handshake.

## Flash it on BOTH sticks

Both the Jetson-side stick and the laptop-side stick run the **same** sketch.

1. Install the **Heltec ESP32** board package (board manager URL
   `https://resource.heltec.cn/download/package_heltec_esp32_index.json`) and the
   **Heltec ESP32 Dev-Boards** library, which provides `LoRaWan_APP.h` and the
   OLED driver.
2. Board: **Heltec Wireless Stick(V3)**, *not* WiFi LoRa 32(V3). The two share
   the radio and OLED pins, so the wrong one still boots and passes the link test,
   but it drives the 64x32 panel as 128x64 and you only see a window from the
   middle of the screen. With `USE_OLED 1` the sketch refuses to build for any
   other board.
3. Upload speed: **230400**. On these sticks' CP2102, esptool transfers at 460800
   and above failed with `Invalid head of packet ... serial noise or corruption`;
   230400 was clean.
4. Open `LoRa_Transceiver/LoRa_Transceiver.ino`, select the stick's port, Upload.
5. Flash **one** stick and re-run the link test below against the other before
   doing the second, so you always have a known-good stick to test against.

Or from the command line (`--list` below tells you the port):

```bash
FQBN=Heltec-esp32:esp32:heltec_wireless_stick_V3
arduino-cli compile --fqbn $FQBN --output-dir /tmp/venator-fw radio/firmware/LoRa_Transceiver
arduino-cli upload  --fqbn $FQBN --board-options UploadSpeed=230400 \
    --port /dev/cu.usbserial-XXXX --input-dir /tmp/venator-fw radio/firmware/LoRa_Transceiver
```

Uploading from `--input-dir` flashes exactly the binary you just built.

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
SSH, in a script, or in any automated run:

```bash
python3 radio/link_test.py --list                  # which port is which stick
python3 radio/link_test.py --listen                # on one machine
python3 radio/link_test.py --send --count 20       # on the other: RTT + loss summary
python3 radio/link_test.py --chat                  # on both: type lines back and forth
```

Close the Arduino Serial Monitor first — only one program can hold a stick's
port at a time. For the two-computer workflow around this, see
[../docs/DEV_SETUP.md](../../docs/DEV_SETUP.md).

## The onboard OLED

Each stick's 0.49" 64x32 panel shows link health, so you can tell at the field
whether the radio is alive without attaching a computer:

```
T12 R11
-47dB +9
LINK UP
```

- **T / R** — packets sent and received since power-up. A T count that climbs
  while the peer's R count does not is a one-way link. At this size a `0` reads
  a lot like an `O`.
- **dB / SNR** — signal strength (dBm) and margin (dB) of the last packet.
  These come straight from the radio's `onRxDone`, which previously discarded
  them. Walk the field watching RSSI to find your real range before you fly.
  Two sticks side by side on a desk read about `-6dB +12`. Before the first
  packet arrives this line says `no peer yet`.
- **LINK UP** — shown while a packet arrived in the last 5 s; otherwise
  `no rx 12s` (minutes past 1000 s, `no rx 16m`), so a dead link is obvious.

There is no room for the text of the last packet at 64 px wide.

### Simpler screen, for a stick you read from a distance

Build with `OLED_SIMPLE=1` and the stick shows one status word in a bigger font
instead, with a single detail under it:

```
  WAIT          LINK UP        NO LINK
                 -47dB         12s ago
```

`WAIT` means nothing has been received since power-up. The detail line is the
last packet's RSSI while the link is up, and how long it has been silent once it
drops (minutes past 1000 s).

```bash
arduino-cli compile --fqbn $FQBN --output-dir /tmp/venator-fw-simple \
    --build-property "compiler.cpp.extra_flags=-DOLED_SIMPLE=1" radio/firmware/LoRa_Transceiver
```

Then upload with `--input-dir /tmp/venator-fw-simple`. In the Arduino IDE, change
`#define OLED_SIMPLE 0` to `1` instead. Only the screen changes, so a simple-screen
stick and a three-line stick talk to each other normally.

### Notes

- **The panel is powered from the `Vext` rail, which is off at boot.** If you
  adapt this code and the screen stays dark, that is almost always the cause —
  `VextON()` must run before `display.init()`.
- The driver (`HT_SSD1306Wire.h`) comes with the Heltec ESP32 Dev-Boards library,
  alongside `LoRaWan_APP.h`.
- Drawing is throttled to 4 Hz and skipped while transmitting. A full frame is
  ~20-30 ms of blocking I2C, and stalling `Radio.IrqProcess()` costs packets.
- If the text reads upside down, uncomment `display.flipScreenVertically()` in
  `setup()`.
- **To disable it entirely**, set `#define USE_OLED 0` at the top of the sketch.
  That build is byte-for-byte the radio-only behaviour, with no display code
  compiled in — useful for isolating a fault to the radio.

## Why a transparent bridge (not the old `{"msg":...}` wrapper)

The original TX sketch wrapped each line as `{"msg":"..."}`. The transceiver
sends lines through untouched so the JSON protocol arrives exactly as sent —
the client and Jetson server do all the parsing. Keep the radio a dumb pipe;
the intelligence lives on the computers at each end.
