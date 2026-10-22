# VENATOR Gateway (Raspberry Pi Pico + REYAX RYLR998)

A second handheld controller: a Pico (MicroPython) with an RYLR998 LoRa module,
an SSD1309 OLED, a rotary encoder and a BACK button. It has the same menu, the
same protocol and the same safety rules as the Heltec remote (see
[../Venator_Remote/README.md](../Venator_Remote/README.md)), and it talks to the
Wireless Stick V3 bridge on the drone.

| Part | Pico pin |
|---|---|
| RYLR998 TXD / RXD | GP1 (UART0 RX) / GP0 (UART0 TX), 3V3, GND |
| SSD1309 SDA / SCL (optional) | GP4 / GP5 |
| Encoder A / B / push | GP6 / GP7 / GP8 |
| BACK (reset) button | GP9 |

## How it reaches the stick

On boot `main.py` sets the RYLR998 to match the bridge: 915 MHz, SF7, 125 kHz,
4/5, preamble 8, and `NETWORKID=18`, which is the RYLR998's name for sync word
0x12. `NETWORKID=18` is also the only ID that allows a preamble other than 12.

The RYLR998 puts a 5-byte header in front of every packet: destination (2 B,
little-endian), source (2 B, little-endian), length. It drops packets that lack
one. `LoRa_Transceiver` strips that header on the way in, and adds one (to
broadcast address 0) on the way out while its last peer used it. Plain-LoRa
peers such as the Heltec remote are unaffected.

## Install

Copy `main.py` to the board, next to `rotary.py`, `rotary_irq_rp2.py`
(micropython-rotary) and `ssd1309.py`, which are already on it. With mpremote:

```bash
mpremote connect /dev/cu.usbmodemXXXX cp radio/firmware/Pico_Gateway/main.py :main.py
```

The USB console logs every packet as `TX ...` / `RX ...`. With no OLED wired,
that console is the only display.
