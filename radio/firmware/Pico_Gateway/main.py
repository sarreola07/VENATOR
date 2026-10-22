# VENATOR Gateway -- Raspberry Pi Pico + REYAX RYLR998 handheld controller.
# Original hardware design and menu code: David Ritter, 10/12/2026.
#
# Speaks the Venator C2 protocol (docs/PROTOCOL.md) to drone/c2_server.py through
# the Wireless Stick V3 bridge (radio/firmware/LoRa_Transceiver), exactly like
# the Heltec remote. The RYLR998 wraps each packet in a 5-byte address header;
# the bridge strips and adds it, so nothing here sees it.
#
# Wiring (unchanged from the original gateway):
#   RYLR998  TXD -> GP1 (UART0 RX)   RXD <- GP0 (UART0 TX)   VDD 3V3, GND
#   SSD1309  SDA GP4, SCL GP5 (optional: without it, the console is the screen)
#   Encoder  A GP6, B GP7, push GP8      Reset/BACK button GP9
#
# Controls: turn = choose, click = select / confirm, BACK = cancel / re-link.
# Hover launches only on a 3 s HOLD after the drone accepts it. In flight:
# click = STOP (land), BACK = ABORT (land). Same safety rules as the Heltec
# remote -- see radio/firmware/Venator_Remote/README.md.
#
# Needs rotary.py, rotary_irq_rp2.py (micropython-rotary) and ssd1309.py on
# the board next to this file.

from machine import Pin, SoftI2C, UART
import utime

# ---- radio: must match the Wireless Stick bridge (915 MHz, SF7, 125 kHz, 4/5,
# preamble 8). NETWORKID 18 is the RYLR998's sync word 0x12, and the only ID
# that allows a preamble other than 12.
RYLR_SETUP = ["AT", "AT+BAND=915000000", "AT+NETWORKID=18",
              "AT+PARAMETER=7,7,1,8", "AT+ADDRESS=1"]

MENU = [  # (server mission id, label, kind)
    (1, "Test each motor", "motors"),
    (2, "Test all motors", "motors"),
    (8, "Hover 3 ft",      "flight"),
    (7, "Drone status",    "info"),
]

HELLO_EVERY_MS, IDLE_PING_MS, FLIGHT_PING_MS = 3000, 5000, 1000
ACK_TIMEOUT_MS, DONE_TIMEOUT_MS = 10000, 90000
LAUNCH_HOLD_MS, CONFIRM_WINDOW_MS = 3000, 45000
CONFIRM_RETRY_MS, CONFIRM_TRIES, LINK_STALE_MS = 5000, 3, 12000

# ---- hardware ----------------------------------------------------------------
uart = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1))

try:
    from ssd1309 import SSD1309_I2C
    oled = SSD1309_I2C(128, 64, SoftI2C(scl=Pin(5), sda=Pin(4), freq=400000))
except Exception as exc:          # no screen wired: run on the console alone
    print("no OLED:", exc)
    oled = None

from rotary_irq_rp2 import RotaryIRQ
from rotary import Rotary
enc = RotaryIRQ(6, 7, min_val=0, max_val=len(MENU) - 1,
                range_mode=Rotary.RANGE_BOUNDED, pull_up=True)


class Button:
    """Debounced active-low button that reports clicks and hold time."""

    def __init__(self, pin):
        self.pin = Pin(pin, Pin.IN, Pin.PULL_UP)
        self.down = False
        self.down_at = 0
        self.held = False
        self.clicked = False
        self._raw, self._changed = False, 0

    def poll(self, now):
        raw = self.pin.value() == 0
        if raw != self._raw:
            self._raw, self._changed = raw, now
        if utime.ticks_diff(now, self._changed) < 30 or raw == self.down:
            return
        self.down = raw
        if raw:
            self.down_at, self.held = now, False
        elif not self.held:
            self.clicked = True

    def take_click(self):
        c, self.clicked = self.clicked, False
        return c


knob, back = Button(8), Button(9)

# ---- RYLR998 link --------------------------------------------------------------
_rx = b""


def at(cmd, wait_ms=600):
    """Send an AT command and return the module's reply (setup only: blocks)."""
    uart.write(cmd + "\r\n")
    t, out = utime.ticks_ms(), b""
    while utime.ticks_diff(utime.ticks_ms(), t) < wait_ms:
        if uart.any():
            out += uart.read()
            if out.endswith(b"\r\n"):
                break
    return out.decode("utf-8", "ignore").strip()


seq = 0


def send(t, **fields):
    """One protocol message to the drone. Returns its seq."""
    global seq
    seq += 1
    body = '{"t":"%s","seq":%d' % (t, seq)
    for k, v in fields.items():
        body += ',"%s":%s' % (k, ('"%s"' % v) if isinstance(v, str) else v)
    body += "}"
    # AT+SEND waits for the radio, which keeps us half-duplex like the stick.
    uart.write("AT+SEND=0,%d,%s\r\n" % (len(body), body))
    print("TX", body)
    return seq


def poll_radio():
    """Next protocol message from the drone as a dict, or None.
    The RYLR998 reports a packet as +RCV=<addr>,<len>,<data>,<rssi>,<snr>."""
    global _rx, last_rx, rssi
    if uart.any():
        _rx += uart.read()
    while b"\r\n" in _rx:
        line, _rx = _rx.split(b"\r\n", 1)
        if not line.startswith(b"+RCV="):
            if line.startswith(b"+ERR"):
                print("RYLR998", line)
            continue
        try:
            addr, n, rest = line[5:].split(b",", 2)
            n = int(n)
            data, tail = rest[:n], rest[n + 1:].split(b",")
            rssi = int(tail[0])
            import json
            msg = json.loads(data)
        except Exception:
            continue
        last_rx = utime.ticks_ms()
        print("RX", data)
        return msg
    return None


# ---- state ---------------------------------------------------------------------
state, state_at = "linking", utime.ticks_ms()
sel, active = 0, None
wait_seq = 0
drone = {}                 # last HELLO_ACK
reason = result = last_log = ""
result_good = False
alt, phase = 0.0, ""
flight_started, confirm_tries, confirm_at = False, 0, 0
last_rx = last_tx = last_hello = 0
rssi = None


def set_state(s):
    global state, state_at
    state, state_at = s, utime.ticks_ms()


def show_result(text, good):
    global result, result_good
    result, result_good = text, good
    set_state("result")


def handle(m):
    global reason, last_log, alt, phase, flight_started, drone
    t = m.get("t")
    if t == "HELLO_ACK":
        drone = m
        if state == "linking":
            set_state("menu")
    elif t == "LOG":
        last_log = m.get("text", "")
        if state == "flying":
            flight_started = True
    elif t == "STATUS":
        alt, phase = m.get("alt", 0.0), m.get("phase", "")
        if state == "flying":
            flight_started = True
    elif t == "ACK" and state == "wait_ack" and m.get("seq") == wait_seq:
        reason = m.get("reason", "")
        if not m.get("accepted"):
            show_result("REFUSED: " + reason, False)
        elif m.get("confirm_required"):
            set_state("fly_confirm")
        else:
            last_log = ""
            set_state("wait_done")
    elif t == "DONE" and state in ("wait_done", "flying"):
        r = str(m.get("result", ""))
        show_result(r, not r.startswith("FAILED"))


def step(now):
    """Advance the state machine once."""
    global sel, active, wait_seq, last_hello, flight_started, confirm_tries, confirm_at
    global alt, phase, last_log
    click, bclick = knob.take_click(), back.take_click()
    idle = utime.ticks_diff(now, last_tx)

    if state == "linking":
        if bclick or utime.ticks_diff(now, last_hello) > HELLO_EVERY_MS:
            last_hello = now
            send("HELLO", proto=1)
    elif state == "menu":
        sel = enc.value()
        if bclick:
            send("HELLO", proto=1)
        elif idle > IDLE_PING_MS:
            send("PING")
        if click:
            active = MENU[sel]
            set_state("local_confirm")
    elif state == "local_confirm":
        if bclick:
            set_state("menu")
        elif click:
            # Never retried: the server does not dedupe RUN.
            wait_seq = send("RUN", id=active[0])
            set_state("wait_ack")
    elif state == "wait_ack":
        if utime.ticks_diff(now, state_at) > ACK_TIMEOUT_MS:
            show_result("No answer from the drone. Nothing confirmed it ran.", False)
    elif state == "wait_done":
        if utime.ticks_diff(now, state_at) > DONE_TIMEOUT_MS:
            show_result("No DONE from the drone. Check it first.", False)
    elif state == "fly_confirm":
        if knob.down and not knob.held and utime.ticks_diff(now, knob.down_at) >= LAUNCH_HOLD_MS \
                and utime.ticks_diff(knob.down_at, state_at) > 0:
            knob.held = True
            send("CONFIRM")
            alt, phase, last_log = 0.0, "", ""
            flight_started, confirm_tries, confirm_at = False, 1, now
            set_state("flying")
        elif bclick or utime.ticks_diff(now, state_at) > CONFIRM_WINDOW_MS:
            send("ABORT")
            show_result("Cancelled. Nothing launched.", True)
    elif state == "flying":
        if not flight_started and utime.ticks_diff(now, confirm_at) > CONFIRM_RETRY_MS:
            if confirm_tries < CONFIRM_TRIES:
                confirm_tries, confirm_at = confirm_tries + 1, now
                send("CONFIRM")    # safe: the drone ignores it once flying
            else:
                send("ABORT")
                show_result("The drone never confirmed the launch. ABORT sent.", False)
        elif bclick:
            send("ABORT")
        elif click:
            send("STOP")
        elif idle > FLIGHT_PING_MS:
            send("PING")
    elif state == "result":
        if click or bclick:
            send("HELLO", proto=1)
            enc.set(value=sel)
            set_state("menu")


# ---- screen (8x8 font: 16 columns, 8 rows) -------------------------------------
def wrap(text, width=16, rows=4):
    out, line = [], ""
    for word in str(text).split():
        if len(line) + len(word) + (1 if line else 0) > width:
            out.append(line)
            line = word[:width]
        else:
            line = (line + " " + word) if line else word
    out.append(line)
    return out[:rows]


def draw(now):
    if oled is None:
        return
    fb = oled.framebuf
    fb.fill(0)
    age = utime.ticks_diff(now, last_rx)
    if not last_rx:
        fb.text("no link yet", 0, 0)
    elif age < LINK_STALE_MS:
        fb.text("LINK %ddB" % rssi if rssi is not None else "LINK", 0, 0)
    else:
        fb.text("NO LINK %ds" % (age // 1000), 0, 0)
    if drone.get("batt"):
        fb.text("%.1fV" % drone["batt"], 88, 0)
    fb.hline(0, 9, 128, 1)
    rows = []
    if state == "linking":
        rows = ["VENATOR", "Looking for", "the drone...", "BACK = retry"]
    elif state == "menu":
        fb.text("props %s" % ("OFF" if drone.get("props_off") else "ON"), 0, 12)
        for i, (_, label, _) in enumerate(MENU):
            fb.text((">" if i == sel else " ") + label[:15], 0, 24 + i * 10)
    elif state == "local_confirm":
        rows = (["Spin motors?", "Props must be", "OFF.", "Click=GO BACK=no"]
                if active[2] == "motors" else
                ["Hover 3 ft?", "Drone checks", "props + GPS.", "Click=ask BACK=no"]
                if active[2] == "flight" else
                [active[1] + "?", "", "", "Click=ask BACK=no"])
    elif state == "wait_ack":
        rows = ["Sending...", active[1], "%ds" % (utime.ticks_diff(now, state_at) // 1000)]
    elif state == "wait_done":
        rows = ["SPINNING" if active[2] == "motors" else "Running",
                "%ds" % (utime.ticks_diff(now, state_at) // 1000)] + wrap(last_log, rows=3)
    elif state == "fly_confirm":
        rows = ["HOLD = LAUNCH", "hold knob 3 s", "BACK cancels"] + wrap(reason, rows=2)
        if knob.down:
            held = min(LAUNCH_HOLD_MS, utime.ticks_diff(now, knob.down_at))
            fb.rect(0, 56, 128, 8, 1)
            fb.fill_rect(0, 56, 128 * held // LAUNCH_HOLD_MS, 8, 1)
    elif state == "flying":
        rows = ["ALT %.2fm" % alt, phase or "arming", "click=STOP", "BACK=ABORT"] + wrap(last_log, rows=1)
    elif state == "result":
        rows = ["DONE" if result_good else "NOT DONE"] + wrap(result, rows=4)
    for i, r in enumerate(rows[:5]):
        fb.text(r, 0, 12 + i * 10)
    oled.show()


# ---- main ------------------------------------------------------------------------
def main():
    for cmd in RYLR_SETUP:
        print(cmd, "->", at(cmd))
    last_draw = 0
    global last_tx
    while True:
        now = utime.ticks_ms()
        m = poll_radio()
        if m is not None:
            handle(m)
        knob.poll(now)
        back.poll(now)
        before = seq
        step(now)
        if seq != before:
            last_tx = now
        if utime.ticks_diff(now, last_draw) > 150:
            last_draw = now
            draw(now)
        utime.sleep_ms(5)


main()
