/*
 * Venator LoRa transceiver — half-duplex transparent bridge.
 *
 * Flash this SAME sketch on BOTH Heltec Wireless Stick V3 sticks (the one on the
 * Jetson and the one on the laptop). It replaces the old one-way LoRa_TX.ino
 * and LoRa_RX.ino so the link works in BOTH directions on each stick.
 *
 * Behaviour — a transparent line bridge:
 *   - A line typed/sent to USB serial (ending in '\n') is transmitted over
 *     915 MHz LoRa verbatim.
 *   - Any packet received over the air is printed to USB serial verbatim,
 *     followed by a newline.
 *
 * That lets the Venator C2 protocol (newline-delimited JSON) pass straight
 * through in both directions. Radio parameters are identical to the original
 * working sketches (915 MHz, SF7, syncword 0x12), so range/behaviour are
 * unchanged — only the direction handling is new.
 *
 * The onboard 64x32 OLED shows link health (packet counts, RSSI/SNR and seconds
 * since the last packet), so a stick tells you whether the link is alive without
 * a computer attached. Set USE_OLED to 0 to get back the exact radio-only
 * behaviour.
 *
 * Build with FQBN Heltec-esp32:esp32:heltec_wireless_stick_V3 against the Heltec
 * ESP32 board package and the Heltec ESP32 Dev-Boards library. The commands and
 * the two-ended link test are in firmware/README.md.
 */
#include "LoRaWan_APP.h"

#define USE_OLED 1           // 0 = radio only, byte-for-byte the previous behaviour
#ifndef OLED_SIMPLE          // 1 = big WAIT / LINK UP / NO LINK plus one detail line,
#define OLED_SIMPLE 0        // for a stick read from a distance. Pick per stick with
#endif                       // --build-property compiler.cpp.extra_flags=-DOLED_SIMPLE=1

#define RF_FREQUENCY     915000000   // Hz  (must match on both sticks)
#define TX_OUTPUT_POWER  14          // dBm
#define LORA_SF          7           // spreading factor
#define LORA_SYNCWORD    0x12
#define MAX_LINE         240         // keep under the LoRa payload limit (255)

static RadioEvents_t RadioEvents;

static volatile bool txBusy = false;     // true while a packet is transmitting
static char   line[MAX_LINE + 1];        // USB-serial line being assembled
static size_t lineLen  = 0;
static bool   lineReady = false;         // a full line is waiting to send

#if USE_OLED
// ---- onboard OLED -----------------------------------------------------------
// The Wireless Stick V3 carries a 0.49" 64x32 SSD1306 on I2C; the board package
// defines its pins. It is powered from the Vext rail, which is OFF at boot --
// without VextON() the panel stays dark and looks exactly like dead hardware.
#include "HT_SSD1306Wire.h"

// The layout below is sized for the 64x32 panel. Driven as 128x64 (the WiFi
// LoRa 32 V3 setting) it shows only a 64x32 window from the middle of the frame,
// so refuse to build for any other board rather than flash a garbled screen.
#if DISPLAY_WIDTH != 64 || DISPLAY_HEIGHT != 32
#error "OLED layout is for the Wireless Stick V3 (64x32). Build with FQBN Heltec-esp32:esp32:heltec_wireless_stick_V3, or set USE_OLED 0."
#endif

#ifndef Vext
#define Vext 36              // V3's Vext control line, if the variant omits it
#endif

#define DISPLAY_MS    250    // redraw at most 4x/s: a full frame costs ~20-30 ms
                             // of I2C, and stalling Radio.IrqProcess() drops packets

static SSD1306Wire display(0x3c, 500000, SDA_OLED, SCL_OLED,
                           GEOMETRY_64_32, RST_OLED);

static uint32_t rxCount = 0, txCount = 0;
static int16_t  lastRssi = 0;
static int8_t   lastSnr  = 0;
static uint32_t lastRxMs = 0;    // millis() of the last packet received
static uint32_t lastDraw = 0;

static void VextON(void) {
    pinMode(Vext, OUTPUT);
    digitalWrite(Vext, LOW);     // LOW enables the OLED power rail
}

#if OLED_SIMPLE
// One status word in the 16 px font, with a single small detail under it:
//   WAIT                  nothing received since power-up
//   LINK UP  / -47dB      a packet arrived in the last 5 s; RSSI of the last one
//   NO LINK  / 12s ago    the peer has gone quiet
static void drawStatus(void) {
    char buf[16];
    uint32_t age = (millis() - lastRxMs) / 1000;   // rollover-safe, as below
    display.clear();
    display.setTextAlignment(TEXT_ALIGN_CENTER);
    display.setFont(ArialMT_Plain_16);
    if (rxCount == 0) {
        display.drawString(32, 0, "WAIT");
    } else {
        display.drawString(32, 0, age <= 5 ? "LINK UP" : "NO LINK");
        if (age <= 5)        snprintf(buf, sizeof(buf), "%ddB", (int)lastRssi);
        else if (age < 1000) snprintf(buf, sizeof(buf), "%lus ago", (unsigned long)age);
        else                 snprintf(buf, sizeof(buf), "%lum ago", (unsigned long)(age / 60));
        display.setFont(ArialMT_Plain_10);
        display.drawString(32, 19, buf);
    }
    display.display();
}
#else
// Three lines of ~10 characters at 10 px spacing -- all a 64x32 panel holds:
//   T12 R11      packets sent / received
//   -47dB +9     RSSI and SNR of the last packet
//   LINK UP      or "no rx 12s" once the peer goes quiet
static void drawStatus(void) {
    char buf[32];
    display.clear();
    display.setFont(ArialMT_Plain_10);

    snprintf(buf, sizeof(buf), "T%lu R%lu",
             (unsigned long)txCount, (unsigned long)rxCount);
    display.drawString(0, 0, buf);

    if (rxCount == 0) {
        display.drawString(0, 10, "no peer yet");
    } else {
        snprintf(buf, sizeof(buf), "%ddB %+d", (int)lastRssi, (int)lastSnr);
        display.drawString(0, 10, buf);

        // Unsigned arithmetic, so this stays correct across the millis() rollover.
        uint32_t age = (millis() - lastRxMs) / 1000;
        if (age <= 5)        snprintf(buf, sizeof(buf), "LINK UP");
        else if (age < 1000) snprintf(buf, sizeof(buf), "no rx %lus", (unsigned long)age);
        else                 snprintf(buf, sizeof(buf), "no rx %lum", (unsigned long)(age / 60));
        display.drawString(0, 20, buf);
    }
    display.display();
}
#endif  // OLED_SIMPLE
#endif  // USE_OLED

static void startRx() {
    Radio.Rx(0);                         // continuous receive
}

static void sendLine(const char *buf, size_t len) {
    txBusy = true;
#if USE_OLED
    txCount++;
#endif
    Radio.Send((uint8_t *)buf, len);     // leaves Rx; onTxDone returns to Rx
}

// ---- radio callbacks --------------------------------------------------------
void onTxDone(void)    { txBusy = false; startRx(); }
void onTxTimeout(void) { txBusy = false; startRx(); }
void onRxTimeout(void) { startRx(); }
void onRxError(void)   { startRx(); }

void onRxDone(uint8_t *payload, uint16_t size, int16_t rssi, int8_t snr) {
    for (uint16_t i = 0; i < size; i++) {
        Serial.write(payload[i]);        // print received bytes verbatim
    }
    Serial.write('\n');
#if USE_OLED
    // rssi/snr were previously discarded; they are the most useful thing the
    // radio knows about the link, so keep the latest for the display.
    rxCount++;
    lastRssi = rssi;
    lastSnr  = snr;
    lastRxMs = millis();
#endif
    startRx();                           // re-arm the receiver
}

// ---- setup / loop -----------------------------------------------------------
void setup() {
    Serial.begin(115200);
    Mcu.begin(HELTEC_BOARD, SLOW_CLK_TPYE);

#if USE_OLED
    VextON();                            // OLED rail is off at boot
    delay(100);                          // let it settle before I2C
    display.init();
    // display.flipScreenVertically();   // uncomment if the text reads upside down
    display.setFont(ArialMT_Plain_10);
    display.clear();
    display.drawString(0, 0, "Venator");
    display.drawString(0, 10, "LoRa 915");
    display.drawString(0, 20, "init...");
    display.display();
#endif

    RadioEvents.TxDone    = onTxDone;
    RadioEvents.TxTimeout = onTxTimeout;
    RadioEvents.RxDone    = onRxDone;
    RadioEvents.RxTimeout = onRxTimeout;
    RadioEvents.RxError   = onRxError;
    Radio.Init(&RadioEvents);

    Radio.SetChannel(RF_FREQUENCY);
    // Identical TX + RX config to the original working sketches.
    Radio.SetTxConfig(MODEM_LORA, TX_OUTPUT_POWER, 0, 0, LORA_SF, 1, 8,
                      false, true, 0, 0, false, 3000);
    Radio.SetRxConfig(MODEM_LORA, 0, LORA_SF, 1, 0, 8, 0,
                      false, 0, true, 0, 0, false, true);
    Radio.SetSyncWord(LORA_SYNCWORD);

    startRx();                           // default state: listening
    Serial.println("Venator LoRa transceiver ready (half-duplex bridge).");
}

void loop() {
    Radio.IrqProcess();

    // Assemble one line from USB serial without blocking. We pause reading once
    // a full line is ready so nothing is dropped while a previous send is in
    // flight (the protocol is stop-and-wait, so this rarely stalls).
    while (Serial.available() && !lineReady) {
        char c = (char)Serial.read();
        if (c == '\n') {
            if (lineLen > 0) { line[lineLen] = '\0'; lineReady = true; }
        } else if (c != '\r' && lineLen < MAX_LINE) {
            line[lineLen++] = c;
        }
    }

    // Transmit the assembled line once the radio is idle.
    if (lineReady && !txBusy) {
        sendLine(line, lineLen);
        lineLen = 0;
        lineReady = false;
    }

#if USE_OLED
    // Redraw last and sparingly. A full frame is ~20-30 ms of blocking I2C, so
    // doing this every pass -- or mid-transmit -- would cost packets. The radio
    // always gets serviced first.
    if (!txBusy && (uint32_t)(millis() - lastDraw) >= DISPLAY_MS) {
        lastDraw = millis();
        drawStatus();
    }
#endif
}
