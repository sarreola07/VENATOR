#!/usr/bin/env python3
"""
The captive-portal landing page: the first thing a phone sees on joining.

Deliberately NOT gui_page.render(). When a phone decides a network has a login
page it opens that page in a restricted browser - Apple calls it the Captive
Network Assistant - and three things the operator GUI depends on do not survive
in there:

  * **MJPEG does not paint reliably.** And worse, drone/wildlife/gui_server.py's
    _mjpeg() holds a thread and one of MAX_VIEWERS stream slots for the life of
    the connection, so a captive sheet killed mid-stream leaks a slot until the
    socket timeout expires.
  * **EventSource is torn down** when the sheet closes, with the same slot
    problem. The ": ping" keepalive in the GUI is commented "keeps iOS honest"
    for Safari proper; the captive sheet is worse.
  * **Cookies set in the sheet never reach Safari**, so the GUI's usual
    token-to-cookie handoff cannot work from here.

So this page polls a single still frame, fetches status once a second, and its
one job is to hand the operator to the real browser - with the token in the
href, because that is the only thing that crosses the boundary.

There is no browser sniffing anywhere. The portal is a different *route*
(/portal) from the GUI (/), so anything that arrives here came via a probe
redirect by construction.

Stdlib only.
"""

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>Venator Drone</title>
<style>
/* docs/BRAND.md's tokens, the same as the camera page and the product page. */
:root{
  --ink:#0A0A0A; --panel:#131314; --line:#2A2A27; --muted:#8A8781;
  --paper:#F2F1EE; --signal:#E05316; --amber:#D9A441;
  --sans:"Helvetica Neue",Helvetica,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--ink);color:var(--paper);font:15px/1.5 var(--sans)}
body{padding:0 0 calc(18px + env(safe-area-inset-bottom));
  padding-top:env(safe-area-inset-top);max-width:560px;margin:0 auto}
header{display:flex;align-items:center;gap:14px;height:56px;padding:0 16px;
  border-bottom:1px solid var(--line)}
header svg{width:118px;height:21px;display:block}
h1{margin:0;font-size:11px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted);font-weight:400}
.sub{padding:16px 16px 0;display:flex;flex-direction:column;gap:4px}
.sub .k{font-size:11px;font-weight:700;letter-spacing:.24em;text-transform:uppercase;color:var(--muted);line-height:1}
.sub b{font-size:20px;font-weight:700;letter-spacing:-.02em;line-height:1.1}

#shot{position:relative;background:#000;aspect-ratio:16/9;overflow:hidden;margin-top:14px}
#shot img{width:100%;height:100%;object-fit:contain;display:block}
#wait{position:absolute;inset:0;display:grid;place-items:center;
  color:var(--muted);font:12px var(--mono);letter-spacing:.08em;text-transform:uppercase;text-align:center;padding:16px}
#shot.live #wait{display:none}

#chips{display:flex;gap:6px;overflow-x:auto;padding:10px 16px;scrollbar-width:none;
  border-bottom:1px solid var(--line)}
#chips::-webkit-scrollbar{display:none}
.chip{flex:0 0 auto;border:1px solid var(--line);padding:5px 10px;font-size:11px;white-space:nowrap;
  display:inline-flex;gap:6px;align-items:baseline}
.chip s{text-decoration:none;color:var(--muted);font:9px var(--mono);letter-spacing:.1em;text-transform:uppercase}
.chip b{font:11px var(--mono);font-weight:400}
.chip.warn,.chip.bad{border-color:var(--amber)} .chip.warn b,.chip.bad b{color:var(--amber);text-transform:uppercase}

.go{display:block;margin:16px 16px 10px;padding:16px 18px;text-align:center;
  background:var(--paper);color:var(--ink);font-weight:700;font-size:12.5px;
  letter-spacing:.12em;text-transform:uppercase;text-decoration:none;border:1.5px solid var(--paper)}
.go:active{transform:translateY(1px)}
.hint{margin:0 16px;color:var(--muted);font-size:13px;text-align:center}
.hint b{color:var(--paper);font-family:var(--mono);font-weight:400}
footer{margin:18px 16px 0;padding-top:12px;border-top:1px solid var(--line);
  color:var(--muted);font:11px var(--mono)}
:focus-visible{outline:2px solid var(--signal);outline-offset:2px}
</style></head><body>

<header>
  <svg viewBox="0 0 470 84" role="img" aria-label="Venator"><g fill="#F2F1EE"><path d="M60 2 65.5 15 64 42 60 56 56 42 54.5 15Z"/><path d="M8 6 46 21 46 32 8 17Z"/><path d="M112 6 74 21 74 32 112 17Z"/><path d="M18 34 60 80 102 34 86 34 60 63 34 34Z"/></g><text x="152" y="46" fill="#F2F1EE" font-family="Helvetica Neue,Helvetica,Arial,sans-serif" font-size="34" font-weight="700" letter-spacing="11">VENATOR</text><text x="154" y="66" fill="#9A968F" font-family="Helvetica Neue,Helvetica,Arial,sans-serif" font-size="10.5" letter-spacing="4.6">AUTONOMOUS FLIGHT SYSTEMS</text></svg>
  <h1>Search camera</h1>
</header>
<div class="sub">
  <span class="k">Connected</span>
  <b>You are on the drone's network</b>
</div>

<div id="shot">
  <img id="img" alt="">
  <div id="wait">waiting for the camera&hellip;</div>
</div>

<div id="chips"></div>

<a class="go" id="go" href="#">Open the live camera</a>

<p class="hint">If this button does nothing, open your browser and go to
<b>venator.com</b></p>

<footer id="foot"></footer>

<script>
const TOKEN = __TOKEN__;
const auth = u => u + (u.includes('?') ? '&' : '?') + (TOKEN ? 'k=' + TOKEN : '');

// The full GUI, in the REAL browser. The token goes in the href because a
// cookie set inside a captive sheet never reaches Safari, so this link is the
// only thing that carries authentication across the boundary.
document.getElementById('go').href =
  'http://venator.com/' + (TOKEN ? '?k=' + TOKEN : '');

// A still frame on a timer, not a stream: a restricted WebView may not render
// multipart/x-mixed-replace at all, and an MJPEG connection that gets killed
// when the sheet closes would hold one of the server's viewer slots until its
// socket timeout expires.
const img = document.getElementById('img');
const shot = document.getElementById('shot');
img.onload = () => shot.classList.add('live');
img.onerror = () => shot.classList.remove('live');
function refresh(){ img.src = auth('/snapshot.jpg') + '&_=' + Date.now(); }
refresh();
setInterval(refresh, 2000);

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function chip(label, value, cls){
  return `<div class="chip ${cls||''}"><s>${esc(label)}</s><b>${esc(value)}</b></div>`;
}
function status(){
  fetch(auth('/api/status')).then(r => r.json()).then(s => {
    const out = [];
    if (s.camera){
      out.push(chip('camera', s.camera, 'bad'));
    } else {
      out.push(chip('camera', 'live'));
      if (s.fps != null) out.push(chip('fps', s.fps.toFixed(1), s.fps >= 8 ? '' : 'warn'));
    }
    if (s.search) out.push(chip('searching', s.search + ' vest'));
    if (s.counts) for (const [k, v] of Object.entries(s.counts)) out.push(chip(k, v));
    if (s.active) out.push(chip('tracking', s.active));
    if (s.temp != null) out.push(chip('soc', s.temp.toFixed(0) + '°C', s.temp < 70 ? '' : 'bad'));
    if (s.pm) out.push(chip('power', s.pm, String(s.pm).startsWith('7W') ? '' : 'warn'));
    document.getElementById('chips').innerHTML = out.join('');
    document.getElementById('foot').textContent =
      (s.model || '') + (s.frames ? ' · ' + s.frames + ' frames this flight' : '');
  }).catch(() => {});
}
status();
setInterval(status, 2000);
</script></body></html>
"""


def render(token, snapshot=None):
    """The portal page, with the token baked in.

    `snapshot` is accepted so the caller can pass hub.snapshot() if the page
    ever wants server-rendered state; today everything is fetched client-side
    so a stale first paint is impossible.

    Shares gui_page.js_literal rather than calling json.dumps directly - see
    the note there for why json.dumps alone does not make a value safe to put
    between <script> tags.
    """
    import gui_page
    return PAGE.replace("__TOKEN__", gui_page.js_literal(token))
