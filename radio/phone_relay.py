#!/usr/bin/env python3
"""
Venator LoRa phone relay — text between two phones over the real LoRa link.

Plug both sticks into this computer and run:

    python3 phone_relay.py

It prints one address per stick. Open stick A's address on one phone and stick
B's on the other, with both phones on the same Wi-Fi as this computer. A
message typed on phone 1 travels

    phone 1 -Wi-Fi-> this computer -USB-> stick A ~915 MHz~> stick B -USB-> this computer -Wi-Fi-> phone 2

so every message really crosses the radio link; only the phones' Wi-Fi hop is
shared. The sticks can also sit on different computers, e.g. a laptop and the
Jetson: run the relay on each with that computer's stick, and name it so the
two pages are easy to tell apart:

    python3 phone_relay.py --names Laptop        # page: http://<laptop>:8080/laptop?k=...
    python3 phone_relay.py --names Jetson        # page: http://10.42.0.1:8080/jetson?k=...

Messages go out as protocol LOG lines, so `link_test.py --chat` on the far stick
shows them too. The radio is half-duplex and two people typing will sometimes
transmit at the same moment, so each message carries an id, the receiving relay
answers with an ACK, and the sender retries before marking it "not confirmed".

Stdlib + pyserial only.
"""
import argparse
import html
import json
import re
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


# Runnable from any folder: put the repo root on the import path so the
# sibling packages (radio/, drone/, ground/) import the same modules
# whether this is started by path, by a desktop launcher or by systemd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radio import protocol as p
from radio.link_test import Link, list_ports

MAX_TEXT = 180          # characters per message; the JSON wrapper adds ~40 bytes
MAX_LINE_BYTES = 240    # MAX_LINE in LoRa_Transceiver.ino: longer lines are cut off
ACK_TIMEOUT_S = 3.0     # round trip measures ~0.4 s; leave room for send pacing
MAX_TRIES = 3
KEEP = 200              # messages kept per stick


class Station:
    """One stick: its serial link, message history and unconfirmed sends."""

    def __init__(self, label, port):
        self.label, self.port = label, port
        self.link = Link(port)
        self.lock = threading.Lock()        # guards messages, pending, seen, seq
        self.send_lock = threading.Lock()   # one writer on the serial port at a time
        self.messages = []
        self.pending = {}                   # id -> [message, wire, tries, deadline]
        self.seen = []                      # recent incoming ids, to drop retries
        self.seq = 0
        self.last_rx = None

    def _add(self, **m):
        m["time"] = time.strftime("%H:%M:%S")
        with self.lock:
            self.messages.append(m)
            del self.messages[:-KEEP]
        arrow = {"out": "->", "in": "<-"}.get(m["dir"], "  ")
        print(f"[{m['time']}] {self.label} {arrow} {m['text']}", flush=True)
        return m

    def _radio_send(self, wire):
        with self.send_lock:
            self.link.send(wire)

    def send_text(self, text):
        """Queue a phone's message onto the radio. Returns an error string or None."""
        text = " ".join(text.split())[:MAX_TEXT]
        if not text:
            return "Type a message first."
        mid = secrets.token_hex(3)
        with self.lock:
            self.seq += 1
            wire = p.message(p.LOG, self.seq, id=mid, text=text)
        if len(p.encode(wire).encode("utf-8")) > MAX_LINE_BYTES:
            return "Too long for one LoRa packet. Emoji count as 12 characters."
        m = self._add(dir="out", text=text, status="sending")
        with self.lock:
            # Register before sending: the ACK can arrive before send() returns.
            self.pending[mid] = [m, wire, 1, time.time() + ACK_TIMEOUT_S + 1]
        self._radio_send(wire)
        with self.lock:
            if mid in self.pending:
                self.pending[mid][3] = time.time() + ACK_TIMEOUT_S
        return None

    def run(self):
        """Reader thread: route arrivals and retry sends that went unconfirmed."""
        while True:
            item = self.link.poll()
            if isinstance(item, tuple):             # not protocol: banner, stray text
                self._add(dir="sys", text=f"radio: {item[1]}")
            elif item is not None:
                self.last_rx = time.time()
                self._handle(item)
            else:
                time.sleep(0.02)
            self._retry_due()

    def _handle(self, msg):
        t = msg.get("t")
        if t == p.LOG:
            mid = msg.get("id")
            if mid:
                # Confirm even a repeat: our first ACK may be the packet that was lost.
                self._radio_send(p.message(p.ACK, msg.get("seq", 0), of=p.LOG, id=mid))
                with self.lock:
                    if mid in self.seen:
                        return
                    self.seen.append(mid)
                    del self.seen[:-100]
            self._add(dir="in", text=str(msg.get("text", "")))
        elif t == p.ACK and msg.get("of") == p.LOG:
            with self.lock:
                entry = self.pending.pop(msg.get("id"), None)
            if entry:
                entry[0]["status"] = "delivered"
                print(f"[{time.strftime('%H:%M:%S')}] {self.label}    delivered: "
                      f"{entry[0]['text']}", flush=True)
        else:
            self._add(dir="sys", text=f"({t} seq={msg.get('seq')})")

    def _retry_due(self):
        now = time.time()
        with self.lock:
            due = [e for e in self.pending.values() if now >= e[3]]
        for entry in due:
            m, wire, tries, _ = entry
            if tries >= MAX_TRIES:
                with self.lock:
                    self.pending.pop(wire["id"], None)
                m["status"] = "failed"
                print(f"[{time.strftime('%H:%M:%S')}] {self.label}    NOT confirmed "
                      f"after {tries} tries: {m['text']}", flush=True)
                continue
            entry[2] = tries + 1
            m["status"] = f"retry {tries + 1}/{MAX_TRIES}"
            self._radio_send(wire)
            entry[3] = time.time() + ACK_TIMEOUT_S

    def snapshot(self):
        with self.lock:
            msgs = [dict(m) for m in self.messages]
        age = None if self.last_rx is None else int(time.time() - self.last_rx)
        return {"stick": self.label, "port": self.port, "last_rx": age, "messages": msgs}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__NAME__ LoRa chat</title>
<style>
:root{--bg:#f4f4f5;--fg:#18181b;--muted:#71717a;--me:#2563eb;--them:#fff;--line:#e4e4e7;--bad:#dc2626}
@media (prefers-color-scheme:dark){:root{--bg:#0a0a0b;--fg:#fafafa;--muted:#a1a1aa;--them:#27272a;--line:#2e2e33;--bad:#f87171}}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{font:16px/1.4 -apple-system,system-ui,sans-serif;background:var(--bg);color:var(--fg);display:flex;flex-direction:column}
header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:baseline;gap:12px}
header b{font-size:18px}#link{font-size:13px;color:var(--muted)}#link.up{color:#16a34a}
#log{flex:1;overflow-y:auto;padding:12px 16px;display:flex;flex-direction:column;gap:6px}
.m{max-width:80%;padding:8px 12px;border-radius:18px;overflow-wrap:anywhere;white-space:pre-wrap}
.out{align-self:flex-end;background:var(--me);color:#fff;border-bottom-right-radius:4px}
.in{align-self:flex-start;background:var(--them);border:1px solid var(--line);border-bottom-left-radius:4px}
.sys{align-self:center;font-size:12px;color:var(--muted);text-align:center}
.meta{font-size:11px;opacity:.8;margin-top:2px}
.empty{margin:auto;color:var(--muted);text-align:center;font-size:14px}
form{display:flex;gap:8px;padding:10px 16px calc(10px + env(safe-area-inset-bottom));border-top:1px solid var(--line)}
input{flex:1;min-width:0;font:inherit;padding:10px 14px;border-radius:22px;border:1px solid var(--line);background:var(--them);color:var(--fg)}
button{font:inherit;font-weight:600;padding:10px 18px;border-radius:22px;border:0;background:var(--me);color:#fff}
#err{color:var(--bad);font-size:13px;padding:0 16px}#err:empty{display:none}
</style></head><body>
<header><b>__NAME__</b><span id="link">connecting…</span></header>
<div id="log"><div class="empty">Messages you send go out over 915&nbsp;MHz LoRa.</div></div>
<div id="err"></div>
<form id="f"><input id="t" maxlength="__MAX__" placeholder="Message" autocomplete="off" enterkeyhint="send"><button>Send</button></form>
<script>
const K = new URLSearchParams(location.search).get("k"), API = "/api/__ID__/";
const log = document.getElementById("log"), link = document.getElementById("link");
const err = document.getElementById("err"), input = document.getElementById("t");
const LABEL = {sending: "sending…", delivered: "delivered ✓", failed: "not confirmed ✗"};
let last = "";
function render(ms) {
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
  log.replaceChildren(...ms.map(m => {
    const el = document.createElement("div");
    el.className = "m " + m.dir;
    if (m.dir === "sys") { el.textContent = m.time + "  " + m.text; return el; }
    el.textContent = m.text;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = m.time + (m.dir === "out" ? " · " + (LABEL[m.status] || m.status) : "");
    el.appendChild(meta);
    return el;
  }));
  if (atBottom) log.scrollTop = log.scrollHeight;
}
async function refresh() {
  try {
    const d = await (await fetch(API + "messages?k=" + K)).json();
    link.className = d.last_rx !== null && d.last_rx <= 10 ? "up" : "";
    link.textContent = d.last_rx === null ? "no packets yet"
      : d.last_rx <= 10 ? "radio active" : "last packet " + d.last_rx + "s ago";
    const j = JSON.stringify(d.messages);
    if (j !== last && d.messages.length) { last = j; render(d.messages); }
  } catch (e) { link.className = ""; link.textContent = "relay unreachable"; }
}
// Send on Enter explicitly rather than relying on implicit form submission,
// which not every browser or on-screen keyboard performs.
input.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); document.getElementById("f").requestSubmit(); }
});
document.getElementById("f").onsubmit = async e => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  try {
    const r = await fetch(API + "send?k=" + K, {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({text})});
    err.textContent = (await r.json()).error || "";
  } catch (e) { err.textContent = "Could not reach the relay."; input.value = text; }
  refresh();
  input.focus();
};
setInterval(refresh, 1000);
refresh();
</script></body></html>
"""


def make_handler(stations, key):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):       # keep the console for radio traffic
            pass

        def _reply(self, code, body, ctype="application/json"):
            data = (body if isinstance(body, str) else json.dumps(body)).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _parse(self):
            url = urlparse(self.path)
            if parse_qs(url.query).get("k", [""])[0] != key:
                self._reply(403, "Wrong or missing key. Use the address the relay printed.",
                            "text/plain")
                return None
            return [s for s in url.path.split("/") if s]

        def do_GET(self):
            parts = self._parse()
            if parts is None:
                return
            if len(parts) == 1 and parts[0].lower() in stations:
                sid = parts[0].lower()
                page = (PAGE.replace("__NAME__", html.escape(stations[sid].label))
                        .replace("__ID__", sid)
                        .replace("__MAX__", str(MAX_TEXT)))
                self._reply(200, page, "text/html")
            elif len(parts) == 3 and parts[0] == "api" and parts[2] == "messages" \
                    and parts[1].lower() in stations:
                self._reply(200, stations[parts[1].lower()].snapshot())
            elif not parts:
                links = "".join(f'<p><a href="/{sid}?k={key}">{html.escape(st.label)}</a></p>'
                                for sid, st in stations.items())
                self._reply(200, f"<!doctype html><meta name=viewport "
                                 f"content='width=device-width'><h2>LoRa chat</h2>{links}",
                            "text/html")
            else:
                self._reply(404, {"error": "not found"})

        def do_POST(self):
            parts = self._parse()
            if parts is None:
                return
            if not (len(parts) == 3 and parts[0] == "api" and parts[2] == "send"
                    and parts[1].lower() in stations):
                self._reply(404, {"error": "not found"})
                return
            try:
                length = min(int(self.headers.get("Content-Length", 0)), 4096)
                text = str(json.loads(self.rfile.read(length) or b"{}").get("text", ""))
            except (ValueError, AttributeError):
                self._reply(400, {"error": "Bad request."})
                return
            error = stations[parts[1].lower()].send_text(text)
            self._reply(200, {"ok": error is None, "error": error})

    return Handler


def lan_address():
    """The address phones on the same Wi-Fi should use (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
    except OSError:
        return socket.gethostname()


def main():
    ap = argparse.ArgumentParser(description="Text between phones over the LoRa link.")
    ap.add_argument("--ports", nargs="+", metavar="PORT",
                    help="stick serial ports (default: every Heltec stick found)")
    ap.add_argument("--names", nargs="+", metavar="NAME",
                    help="one name per stick, in --ports order, shown on its page and used "
                         "as its address, e.g. --names Jetson (default: Stick A, Stick B, ...)")
    ap.add_argument("--http-port", type=int, default=8080)
    ap.add_argument("--key", default=None,
                    help="access key in the page address (default: random 4 digits)")
    args = ap.parse_args()

    ports = args.ports or sorted(d for d, _desc, heltec in list_ports() if heltec)
    if not ports:
        print("No Heltec stick found. Plug one in, or name it with --ports.")
        return 1
    if args.names:
        if len(args.names) != len(ports):
            print(f"{len(ports)} stick(s) but {len(args.names)} name(s): give one name per "
                  f"stick ({', '.join(ports)}).")
            return 1
        bad = [n for n in args.names if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", n)]
        if bad or len({n.lower() for n in args.names}) != len(args.names):
            print("Names must be unique and use only letters, digits, - and _ "
                  "(they become the page address).")
            return 1
        slugs, labels = [n.lower() for n in args.names], list(args.names)
    else:
        slugs = [chr(ord("a") + i) for i in range(len(ports))]
        labels = [f"Stick {s.upper()}" for s in slugs]
    key = args.key or f"{secrets.randbelow(10000):04d}"

    stations = {}                           # address slug -> Station
    for slug, label, port in zip(slugs, labels, ports):
        try:
            stations[slug] = Station(label, port)
        except Exception as exc:
            print(f"Could not open {port}: {exc}")
            print("Close link_test.py, the Arduino Serial Monitor or anything else "
                  "using the stick first.")
            return 1
        threading.Thread(target=stations[slug].run, daemon=True).start()

    try:
        server = ThreadingHTTPServer(("0.0.0.0", args.http_port), make_handler(stations, key))
    except OSError as exc:
        print(f"Could not listen on port {args.http_port}: {exc}. Try --http-port 8081.")
        return 1

    host = lan_address()
    print("\nLoRa phone relay running. Open one address per phone "
          "(phones on the same Wi-Fi as this computer):\n", flush=True)
    for slug, st in stations.items():
        print(f"  {st.label:<10} {st.port:<24} http://{host}:{args.http_port}/"
              f"{slug}?k={key}", flush=True)
    print("\nCtrl-C to stop.\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        server.server_close()
        for st in stations.values():
            st.link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
