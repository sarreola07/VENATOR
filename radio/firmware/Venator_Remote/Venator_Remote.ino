/*
 * Venator handheld remote — Heltec WiFi LoRa 32 (V3) + rotary encoder.
 *
 * A standalone ground station: no laptop. It speaks the Venator C2 protocol
 * (docs/PROTOCOL.md) over the same 915 MHz link as the Wireless Stick bridge on
 * the Jetson, so drone/c2_server.py cannot tell it from ground/gcs_client.py.
 *
 *   turn knob   choose            click knob   select / confirm
 *   BACK button cancel / re-link  in flight:   click = STOP (land now),
 *                                              BACK  = ABORT (land now)
 *
 * Menu (ids are drone/c2_server.py's):
 *   1 Test each motor   2 Test all motors   8 Hover 3 ft   7 Drone status
 *
 * Safety lives on the drone, not here: the server refuses motor tests unless
 * props are declared OFF, and the hover unless props are ON and GPS has a 3D
 * fix. This remote adds a local confirm before anything moves, and the hover
 * launches only on a 3 s HOLD of the knob after the drone has accepted it. In
 * flight it pings every second; if those stop, the drone lands by itself.
 *
 * The link is not authenticated (radio/auth.py is not implemented here), so run
 * the server without a key while using this remote. See docs/SECURITY.md.
 *
 * Build with FQBN Heltec-esp32:esp32:heltec_wifi_lora_32_V3 against the Heltec
 * ESP32 board package and the Heltec ESP32 Dev-Boards library -- the same
 * toolchain as LoRa_Transceiver. Commands are in README.md next to this file.
 */
#include "LoRaWan_APP.h"
#include "HT_SSD1306Wire.h"
#include <Preferences.h>     // NVS: the setup wizard's encoder-direction flag

// ---- radio: identical to LoRa_Transceiver.ino, or the two cannot hear each other
#define RF_FREQUENCY     915000000
#define TX_OUTPUT_POWER  14
#define LORA_SF          7
#define LORA_SYNCWORD    0x12
#define MAX_LINE         240

// ---- controls (found with a pin scan of this remote; encoder + is on 3V3)
#define PIN_ENC_A   1
#define PIN_ENC_B   2
#define PIN_KNOB    3       // encoder push switch, active low
#define PIN_BACK    4       // the separate button, active low
#define STEPS_PER_DETENT 4  // KY-040 style: one full quadrature cycle per click

#ifndef Vext
#define Vext 36
#endif

// ---- timings
#define HELLO_EVERY_MS     3000
#define IDLE_PING_MS       5000
#define FLIGHT_PING_MS     1000    // server lands if it hears nothing for LINK_LOSS_S (4 s)
#define LINK_STALE_MS     12000
#define ACK_TIMEOUT_MS    10000    // the hover's GPS check alone can take 2 s
#define DONE_TIMEOUT_MS   90000    // the sequential test is ~20 s on a quad
#define LAUNCH_HOLD_MS     3000
#define CONFIRM_WINDOW_MS 45000    // < the server's PENDING_CONFIRM_S (60 s)
#define CONFIRM_RETRY_MS   5000    // no word from the drone after CONFIRM -> resend
#define CONFIRM_TRIES         3    // then ABORT: the drone never said it launched
#define DRAW_MS             120

static SSD1306Wire display(0x3c, 500000, SDA_OLED, SCL_OLED, GEOMETRY_128_64, RST_OLED);
static RadioEvents_t RadioEvents;

// ---------------------------------------------------------------------------
// Menu
// ---------------------------------------------------------------------------
enum Kind { MOTORS, FLIGHT, INFO };
struct Item { int id; const char *name; Kind kind; };
static const Item MENU[] = {
    {1, "Test each motor", MOTORS},
    {2, "Test all motors", MOTORS},
    {8, "Hover 3 ft",      FLIGHT},
    {7, "Drone status",    INFO},
};
static const int MENU_N = sizeof(MENU) / sizeof(MENU[0]);

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
// WIZARD is appended so every existing enumerator keeps its value.
enum State { LINKING, MENU_VIEW, LOCAL_CONFIRM, WAIT_ACK, WAIT_DONE,
             FLY_CONFIRM, FLYING, RESULT, WIZARD };
static State state = LINKING;
static uint32_t stateAt = 0;

// ---- commissioning wizard, for a newly built remote ------------------------
// Entered only by holding BACK through boot, so a flown unit is untouched. It
// walks the controls in order and then proves the radio; it deliberately cannot
// *edit* the radio parameters, which must stay identical to
// LoRa_Transceiver.ino or the two ends go deaf to each other.
enum WizStep { WZ_INTRO, WZ_CLICK, WZ_CW, WZ_CCW, WZ_BACK, WZ_RADIO, WZ_DONE };
static WizStep  wizStep = WZ_INTRO;
static int      wizCwSeen = 0, wizCcwSeen = 0;
static bool     wizInvertFound = false;
static uint32_t wizStepAt = 0, wizHelloAt = 0;
static char     wizNote[48] = "";

static int sel = 0;                // selected menu index
static const Item *active = nullptr;
static uint32_t seq = 0, waitSeq = 0;

// what the drone last told us
static bool  haveDrone = false, propsOff = false, armed = false;
static float batt = 0, alt = 0;
static char  gps[16] = "?", fcName[12] = "?", phase[16] = "";
static char  reason[160] = "", result[160] = "", lastLog[96] = "";
static bool  resultGood = false;
static bool  flightStarted = false;   // the drone has said something since CONFIRM
static int   confirmTries = 0;
static uint32_t confirmAt = 0;

// link health
static uint32_t lastRxMs = 0, lastTxMs = 0, lastHelloMs = 0;
static int16_t  lastRssi = 0;
static uint32_t rxCount = 0;

static void setState(State s) { state = s; stateAt = millis(); }

// ---------------------------------------------------------------------------
// Rotary encoder (interrupt driven, so a 20 ms OLED frame cannot lose clicks)
// ---------------------------------------------------------------------------
static portMUX_TYPE encMux = portMUX_INITIALIZER_UNLOCKED;
static volatile int8_t encQuarter = 0;
static volatile int    encDetents = 0;
static volatile uint8_t encPrev = 3;
// Transition table, index (old AB << 2) | new AB. On this remote clockwise
// runs AB 11 -> 01 -> 00 -> 10 -> 11, which this table counts as +1.
static const int8_t QDEC[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};

static void IRAM_ATTR onEncoder() {
    uint8_t ab = (digitalRead(PIN_ENC_A) << 1) | digitalRead(PIN_ENC_B);
    portENTER_CRITICAL_ISR(&encMux);
    encQuarter = encQuarter + QDEC[(encPrev << 2) | ab];
    encPrev = ab;
    if (encQuarter >= STEPS_PER_DETENT)       { encDetents = encDetents + 1; encQuarter = 0; }
    else if (encQuarter <= -STEPS_PER_DETENT) { encDetents = encDetents - 1; encQuarter = 0; }
    portEXIT_CRITICAL_ISR(&encMux);
}

// On a hand-soldered encoder A and B get swapped about half the time, which
// silently inverts the knob. The wizard measures the direction and stores the
// correction in NVS, so a mis-wired unit works without a resolder or a
// per-unit recompile.
static Preferences prefs;
static bool encInvert = false;

static int takeDetents() {
    portENTER_CRITICAL(&encMux);
    int d = encDetents;
    encDetents = 0;
    portEXIT_CRITICAL(&encMux);
    return encInvert ? -d : d;
}

// Raw detents, ignoring encInvert. Only the wizard uses this: it is measuring
// the sign, so it must not read through the correction it is trying to derive.
static int takeDetentsRaw() {
    portENTER_CRITICAL(&encMux);
    int d = encDetents;
    encDetents = 0;
    portEXIT_CRITICAL(&encMux);
    return d;
}

// ---------------------------------------------------------------------------
// Buttons: debounced, with press start time so a HOLD can be measured
// ---------------------------------------------------------------------------
// Methods, not free functions: the Arduino builder hoists prototypes above
// the struct, and a free function taking Button& then fails to compile.
struct Button {
    uint8_t pin; bool down; bool raw; uint32_t changedAt; uint32_t downAt;
    bool clicked; bool held; State downIn;

    void poll() {
        bool r = digitalRead(pin) == LOW;
        uint32_t now = millis();
        if (r != raw) { raw = r; changedAt = now; }
        if (now - changedAt < 30 || r == down) return;
        down = r;
        if (down) { downAt = now; downIn = state; held = false; }
        else if (!held) clicked = true;       // a hold is not also a click
    }
    bool takeClick() { bool c = clicked; clicked = false; return c; }
};
static Button knob = {PIN_KNOB, false, false, 0, 0, false, false, LINKING};
static Button back = {PIN_BACK, false, false, 0, 0, false, false, LINKING};

// ---------------------------------------------------------------------------
// Radio
// ---------------------------------------------------------------------------
static volatile bool txBusy = false;
static char outbox[MAX_LINE + 1];
static bool outboxFull = false;
static char inbox[MAX_LINE + 1];
static volatile bool inboxFull = false;

void onTxDone(void)    { txBusy = false; Radio.Rx(0); }
void onTxTimeout(void) { txBusy = false; Radio.Rx(0); }
void onRxTimeout(void) { Radio.Rx(0); }
void onRxError(void)   { Radio.Rx(0); }
void onRxDone(uint8_t *payload, uint16_t size, int16_t rssi, int8_t snr) {
    if (!inboxFull) {
        uint16_t n = size < MAX_LINE ? size : MAX_LINE;
        memcpy(inbox, payload, n);
        inbox[n] = '\0';
        inboxFull = true;
    }
    lastRssi = rssi;
    Radio.Rx(0);
}

// Queue one protocol line. One packet in flight at a time (half duplex).
static void sendLine(const char *line) {
    strncpy(outbox, line, MAX_LINE);
    outbox[MAX_LINE] = '\0';
    outboxFull = true;
    Serial.printf("TX %s\n", line);
}

static void pumpRadio() {
    // The Jetson bridge paces its own sends 0.3 s apart; keep a similar gap so
    // a reply in flight is not stepped on.
    if (outboxFull && !txBusy && millis() - lastTxMs > 150) {
        txBusy = true;
        lastTxMs = millis();
        Radio.Send((uint8_t *)outbox, strlen(outbox));
        outboxFull = false;
    }
}

static uint32_t sendMsg(const char *t, const char *extra = "") {
    char buf[MAX_LINE + 1];
    uint32_t s = ++seq;
    snprintf(buf, sizeof(buf), "{\"t\":\"%s\",\"seq\":%lu%s}", t, (unsigned long)s, extra);
    sendLine(buf);
    return s;
}

// ---------------------------------------------------------------------------
// Minimal JSON field readers -- enough for the server's flat messages
// ---------------------------------------------------------------------------
static const char *findKey(const char *js, const char *key) {
    char pat[24];
    snprintf(pat, sizeof(pat), "\"%s\":", key);
    const char *p = strstr(js, pat);
    return p ? p + strlen(pat) : nullptr;
}

static bool jStr(const char *js, const char *key, char *out, size_t n) {
    const char *p = findKey(js, key);
    if (!p || *p != '"') return false;
    p++;
    size_t i = 0;
    while (*p && *p != '"' && i + 1 < n) {
        if (*p == '\\' && p[1]) {
            p++;
            if (*p == 'u') {                 // json.dumps escapes non-ASCII: show '-'
                out[i++] = '-';
                for (int k = 0; k < 4 && p[1]; k++) p++;
            } else {
                out[i++] = (*p == 'n') ? ' ' : *p;
            }
            p++;
        } else {
            out[i++] = *p++;
        }
    }
    out[i] = '\0';
    return true;
}

static bool jNum(const char *js, const char *key, float *v) {
    const char *p = findKey(js, key);
    if (!p || !(*p == '-' || (*p >= '0' && *p <= '9'))) return false;
    *v = atof(p);
    return true;
}

static bool jBool(const char *js, const char *key, bool *v) {
    const char *p = findKey(js, key);
    if (!p) return false;
    if (!strncmp(p, "true", 4))  { *v = true;  return true; }
    if (!strncmp(p, "false", 5)) { *v = false; return true; }
    return false;
}

static bool isType(const char *js, const char *t) {
    char got[16];
    return jStr(js, "t", got, sizeof(got)) && !strcmp(got, t);
}

// ---------------------------------------------------------------------------
// Protocol: what to do with each message from the drone
// ---------------------------------------------------------------------------
static void showResult(const char *text, bool good) {
    strncpy(result, text, sizeof(result) - 1);
    result[sizeof(result) - 1] = '\0';
    resultGood = good;
    setState(RESULT);
}

static void handleLine(const char *js) {
    Serial.printf("RX %s\n", js);
    if (js[0] != '{') return;
    lastRxMs = millis();
    rxCount++;
    float f;
    bool b;
    float seqf = -1;
    jNum(js, "seq", &seqf);

    if (isType(js, "HELLO_ACK")) {
        haveDrone = true;
        if (jBool(js, "props_off", &b)) propsOff = b;
        if (jBool(js, "armed", &b)) armed = b;
        if (jNum(js, "batt", &f)) batt = f;
        jStr(js, "gps", gps, sizeof(gps));
        jStr(js, "fc", fcName, sizeof(fcName));
        if (state == LINKING) setState(MENU_VIEW);
        return;
    }
    if (isType(js, "LOG")) {
        jStr(js, "text", lastLog, sizeof(lastLog));
        if (state == FLYING) flightStarted = true;
        return;
    }
    if (isType(js, "STATUS")) {
        if (state == FLYING) flightStarted = true;
        if (jNum(js, "alt", &f)) alt = f;
        if (jBool(js, "armed", &b)) armed = b;
        jStr(js, "phase", phase, sizeof(phase));
        return;
    }
    if (isType(js, "ACK") && state == WAIT_ACK && (uint32_t)seqf == waitSeq) {
        bool accepted = false, confirm = false;
        jBool(js, "accepted", &accepted);
        jBool(js, "confirm_required", &confirm);
        reason[0] = '\0';
        jStr(js, "reason", reason, sizeof(reason));
        if (!accepted) {
            char t[180];
            snprintf(t, sizeof(t), "REFUSED: %s", reason);
            showResult(t, false);
        } else if (confirm) {
            setState(FLY_CONFIRM);
        } else {
            lastLog[0] = '\0';
            setState(WAIT_DONE);
        }
        return;
    }
    if (isType(js, "DONE") && (state == WAIT_DONE || state == FLYING)) {
        char r[150] = "";
        jStr(js, "result", r, sizeof(r));
        showResult(r, strncmp(r, "FAILED", 6) != 0);
        return;
    }
    // PONG and anything else only refresh lastRxMs (done above).
}

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------
static void drawHeader() {
    char buf[32];
    display.setFont(ArialMT_Plain_10);
    display.setTextAlignment(TEXT_ALIGN_LEFT);
    uint32_t age = millis() - lastRxMs;
    if (rxCount == 0)                 snprintf(buf, sizeof(buf), "no link yet");
    else if (age < LINK_STALE_MS)     snprintf(buf, sizeof(buf), "LINK %ddB", (int)lastRssi);
    else                              snprintf(buf, sizeof(buf), "NO LINK %lus", (unsigned long)(age / 1000));
    display.drawString(0, 0, buf);
    if (haveDrone) {
        display.setTextAlignment(TEXT_ALIGN_RIGHT);
        if (batt > 0.5f) snprintf(buf, sizeof(buf), "%.1fV", batt);
        else             snprintf(buf, sizeof(buf), "no batt");
        display.drawString(128, 0, buf);
        display.setTextAlignment(TEXT_ALIGN_LEFT);
    }
    display.drawHorizontalLine(0, 12, 128);
}

static void drawBody(const char *title, const char *text) {
    display.setFont(ArialMT_Plain_16);
    display.drawString(0, 13, title);
    display.setFont(ArialMT_Plain_10);
    display.drawStringMaxWidth(0, 31, 128, text);
}

static void draw() {
    char buf[96];
    uint32_t now = millis();
    display.clear();
    drawHeader();
    switch (state) {
    case LINKING:
        snprintf(buf, sizeof(buf), "Looking for the drone... BACK retries now.");
        drawBody("VENATOR", buf);
        break;
    case WIZARD:
        switch (wizStep) {
        case WZ_INTRO:
            drawBody("Setup", "Click the knob to start. BACK exits.");
            break;
        case WZ_CLICK:
            drawBody("1/5 knob", "Click works.");
            break;
        case WZ_CW:
            snprintf(buf, sizeof(buf), "Turn the knob CLOCKWISE  %d/3", abs(wizCwSeen));
            drawBody("2/5 turn", buf);
            break;
        case WZ_CCW:
            snprintf(buf, sizeof(buf), "Now turn it ANTICLOCKWISE  %d/3", abs(wizCcwSeen));
            drawBody("3/5 turn", buf);
            break;
        case WZ_BACK:
            snprintf(buf, sizeof(buf), "%s. Press BACK.", wizNote);
            drawBody("4/5 BACK", buf);
            break;
        case WZ_RADIO:
            snprintf(buf, sizeof(buf), "Calling the drone... BACK skips.");
            drawBody("5/5 radio", buf);
            break;
        case WZ_DONE:
            snprintf(buf, sizeof(buf), "Link %ddB. %s. Click to start.",
                     (int)lastRssi, wizNote);
            drawBody("Ready", buf);
            break;
        }
        break;
    case MENU_VIEW: {
        snprintf(buf, sizeof(buf), "props %s | gps %s", propsOff ? "OFF" : "ON", gps);
        display.drawString(0, 13, buf);
        int first = sel > 1 ? (sel - 1 < MENU_N - 3 ? sel - 1 : MENU_N - 3) : 0;
        if (first < 0) first = 0;
        for (int row = 0; row < 3 && first + row < MENU_N; row++) {
            int i = first + row, y = 26 + row * 13;
            if (i == sel) {
                display.fillRect(0, y, 128, 13);
                display.setColor(BLACK);
            }
            display.drawString(3, y, MENU[i].name);
            display.setColor(WHITE);
        }
        break;
    }
    case LOCAL_CONFIRM:
        if (active->kind == MOTORS)
            drawBody("Spin motors?", "Props must be OFF.  Click = GO   BACK = cancel");
        else if (active->kind == FLIGHT)
            drawBody("Hover 3 ft?", "Click = ask the drone. It checks props + GPS first.  BACK = cancel");
        else
            drawBody(active->name, "Click = ask   BACK = cancel");
        break;
    case WAIT_ACK:
        snprintf(buf, sizeof(buf), "Sent %s. Waiting for the drone (%lus)",
                 active->name, (unsigned long)((now - stateAt) / 1000));
        drawBody("Sending...", buf);
        break;
    case WAIT_DONE:
        snprintf(buf, sizeof(buf), "%lus  %s", (unsigned long)((now - stateAt) / 1000),
                 lastLog[0] ? lastLog : active->name);
        drawBody(active->kind == MOTORS ? "SPINNING" : "Running", buf);
        break;
    case FLY_CONFIRM: {
        uint32_t left = CONFIRM_WINDOW_MS - (now - stateAt);
        display.setFont(ArialMT_Plain_16);
        display.drawString(0, 13, "HOLD = LAUNCH");
        display.setFont(ArialMT_Plain_10);
        snprintf(buf, sizeof(buf), "hold knob 3 s. BACK cancels (%lus)", (unsigned long)(left / 1000));
        display.drawString(0, 31, buf);
        if (!(knob.down && knob.downIn == FLY_CONFIRM)) {
            display.drawStringMaxWidth(0, 43, 128, reason);   // what the drone will do
        } else {
            uint32_t held = now - knob.downAt;
            int w = held >= LAUNCH_HOLD_MS ? 128 : (int)(128UL * held / LAUNCH_HOLD_MS);
            display.drawRect(0, 56, 128, 8);
            display.fillRect(0, 56, w, 8);
        }
        break;
    }
    case FLYING:
        snprintf(buf, sizeof(buf), "ALT %.2fm", alt);
        display.setFont(ArialMT_Plain_16);
        display.drawString(0, 13, buf);
        display.setFont(ArialMT_Plain_10);
        snprintf(buf, sizeof(buf), "%s  click=STOP  BACK=ABORT", phase[0] ? phase : "arming");
        display.drawString(0, 31, buf);
        display.drawStringMaxWidth(0, 43, 128, lastLog);
        break;
    case RESULT:
        drawBody(resultGood ? "DONE" : "NOT DONE", result);
        break;
    }
    display.display();
}

// ---------------------------------------------------------------------------
// The state machine
// ---------------------------------------------------------------------------
static void runRemote() {
    uint32_t now = millis();
    int turn = takeDetents();
    bool click = knob.takeClick();
    bool backClick = back.takeClick();

    switch (state) {
    case WIZARD:
        // Unreachable: loop() routes WIZARD to runWizard() instead. Named
        // explicitly so this switch stays exhaustive and the compiler keeps
        // warning if a future state is added without being handled here.
        break;
    case LINKING:
        if (backClick || now - lastHelloMs > HELLO_EVERY_MS) {
            lastHelloMs = now;
            sendMsg("HELLO", ",\"proto\":1");
        }
        break;

    case MENU_VIEW:
        if (turn) sel = constrain(sel + turn, 0, MENU_N - 1);
        if (backClick) {                       // refresh the drone's status
            lastHelloMs = now;
            sendMsg("HELLO", ",\"proto\":1");
        } else if (now - lastTxMs > IDLE_PING_MS && !outboxFull) {
            sendMsg("PING");
        }
        if (click) { active = &MENU[sel]; setState(LOCAL_CONFIRM); }
        break;

    case LOCAL_CONFIRM:
        if (backClick) setState(MENU_VIEW);
        else if (click) {
            char extra[16];
            snprintf(extra, sizeof(extra), ",\"id\":%d", active->id);
            // Never retried: the server does not dedupe RUN, so a resend could
            // run a motor test twice.
            waitSeq = sendMsg("RUN", extra);
            setState(WAIT_ACK);
        }
        break;

    case WAIT_ACK:
        if (now - stateAt > ACK_TIMEOUT_MS)
            showResult("No answer from the drone. Nothing confirmed it ran.", false);
        break;

    case WAIT_DONE:
        if (now - stateAt > DONE_TIMEOUT_MS)
            showResult("No DONE from the drone. Check it before the next test.", false);
        break;

    case FLY_CONFIRM:
        if (knob.down && knob.downIn == FLY_CONFIRM && !knob.held
                && now - knob.downAt >= LAUNCH_HOLD_MS) {
            knob.held = true;                  // so releasing is not also a click
            sendMsg("CONFIRM");
            alt = 0; phase[0] = '\0'; lastLog[0] = '\0';
            flightStarted = false; confirmTries = 1; confirmAt = now;
            setState(FLYING);
        } else if (backClick || now - stateAt > CONFIRM_WINDOW_MS) {
            sendMsg("ABORT");                  // drops the prepared flight on the drone
            showResult("Cancelled. Nothing launched.", true);
        }
        break;

    case FLYING:
        // A CONFIRM lost on the air leaves the drone waiting and us "flying".
        // Resending is safe: once a flight is under way the drone ignores
        // CONFIRM, and once it is over nothing is pending to launch.
        if (!flightStarted && now - confirmAt > CONFIRM_RETRY_MS) {
            if (confirmTries < CONFIRM_TRIES) {
                confirmTries++; confirmAt = now;
                sendMsg("CONFIRM");
            } else {
                sendMsg("ABORT");              // lands it if it did launch unheard
                showResult("The drone never confirmed the launch. ABORT sent.", false);
            }
            break;
        }
        if (backClick) sendMsg("ABORT");
        else if (click) sendMsg("STOP");
        else if (now - lastTxMs > FLIGHT_PING_MS && !outboxFull) sendMsg("PING");
        break;

    case RESULT:
        if (click || backClick) {
            sendMsg("HELLO", ",\"proto\":1");   // refresh battery / props / GPS
            setState(MENU_VIEW);
        }
        break;
    }
}

// ---------------------------------------------------------------------------
// Commissioning wizard
// ---------------------------------------------------------------------------
static void wizGo(WizStep s) { wizStep = s; wizStepAt = millis(); }

static void runWizard() {
    uint32_t now = millis();
    int d = takeDetentsRaw();

    switch (wizStep) {
    case WZ_INTRO:
        if (knob.takeClick()) wizGo(WZ_CLICK);
        break;
    case WZ_CLICK:
        // Getting here already proved the knob switch. Hold the confirmation on
        // screen long enough to read before asking for the next input.
        if (now - wizStepAt > 900) { wizCwSeen = 0; wizGo(WZ_CW); }
        break;
    case WZ_CW:
        wizCwSeen += d;
        if (abs(wizCwSeen) >= 3) { wizCcwSeen = 0; wizGo(WZ_CCW); }
        break;
    case WZ_CCW:
        wizCcwSeen += d;
        if (abs(wizCcwSeen) >= 3) {
            // Clockwise must count up. If it counted down while anticlockwise
            // counted up, A/B are swapped -- record it rather than ask for a
            // resolder. Any other combination means one channel is dead or
            // stuck, which inverting would hide, so leave it alone and say so.
            wizInvertFound = (wizCwSeen < 0 && wizCcwSeen > 0);
            bool consistent = (wizCwSeen > 0 && wizCcwSeen < 0) || wizInvertFound;
            if (consistent) {
                encInvert = wizInvertFound;
                prefs.begin("venator", false);
                prefs.putBool("encInvert", encInvert);
                prefs.end();
                snprintf(wizNote, sizeof(wizNote), "%s",
                         wizInvertFound ? "A/B swapped, fixed in software"
                                        : "direction correct");
            } else {
                snprintf(wizNote, sizeof(wizNote), "CHECK WIRING: A or B stuck");
            }
            wizGo(WZ_BACK);
        }
        break;
    case WZ_BACK:
        if (back.takeClick()) { rxCount = 0; wizHelloAt = 0; wizGo(WZ_RADIO); }
        break;
    case WZ_RADIO:
        if (now - wizHelloAt > HELLO_EVERY_MS) { wizHelloAt = now; sendMsg("HELLO"); }
        if (rxCount > 0) wizGo(WZ_DONE);
        break;
    case WZ_DONE:
        if (knob.takeClick()) setState(LINKING);
        break;
    }

    // BACK leaves the wizard from any step except the two that use it.
    if (wizStep != WZ_BACK && wizStep != WZ_DONE && back.takeClick()) setState(LINKING);
}

// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    Mcu.begin(HELTEC_BOARD, SLOW_CLK_TPYE);

    pinMode(Vext, OUTPUT);
    digitalWrite(Vext, LOW);                   // OLED rail is off at boot
    delay(100);
    display.init();
    display.flipScreenVertically();            // rotated 180° for how this remote is held
    display.setFont(ArialMT_Plain_10);

    pinMode(PIN_ENC_A, INPUT_PULLUP);
    pinMode(PIN_ENC_B, INPUT_PULLUP);
    pinMode(PIN_KNOB, INPUT_PULLUP);
    pinMode(PIN_BACK, INPUT_PULLUP);
    encPrev = (digitalRead(PIN_ENC_A) << 1) | digitalRead(PIN_ENC_B);
    attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), onEncoder, CHANGE);
    attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), onEncoder, CHANGE);

    prefs.begin("venator", true);              // read-only
    encInvert = prefs.getBool("encInvert", false);
    prefs.end();

    RadioEvents.TxDone    = onTxDone;
    RadioEvents.TxTimeout = onTxTimeout;
    RadioEvents.RxDone    = onRxDone;
    RadioEvents.RxTimeout = onRxTimeout;
    RadioEvents.RxError   = onRxError;
    Radio.Init(&RadioEvents);
    Radio.SetChannel(RF_FREQUENCY);
    Radio.SetTxConfig(MODEM_LORA, TX_OUTPUT_POWER, 0, 0, LORA_SF, 1, 8,
                      false, true, 0, 0, false, 3000);
    Radio.SetRxConfig(MODEM_LORA, 0, LORA_SF, 1, 0, 8, 0,
                      false, 0, true, 0, 0, false, true);
    Radio.SetSyncWord(LORA_SYNCWORD);
    Radio.Rx(0);

    Serial.println("Venator remote ready.");
    // Holding BACK through boot runs the commissioning wizard. Nothing else
    // reaches it, so a remote that is already flying behaves exactly as before.
    if (digitalRead(PIN_BACK) == LOW) {
        Serial.println("BACK held at boot - setup wizard.");
        wizGo(WZ_INTRO);
        setState(WIZARD);
    } else {
        setState(LINKING);
    }
}

void loop() {
    static uint32_t lastDraw = 0;
    Radio.IrqProcess();
    if (inboxFull) {
        char line[MAX_LINE + 1];
        strcpy(line, inbox);
        inboxFull = false;
        handleLine(line);
    }
    knob.poll();
    back.poll();
    if (state == WIZARD) runWizard();
    else                 runRemote();
    pumpRadio();
    // Redraw last and never mid-transmit: a 128x64 frame is ~20 ms of I2C.
    if (!txBusy && millis() - lastDraw >= DRAW_MS) {
        lastDraw = millis();
        draw();
    }
}
