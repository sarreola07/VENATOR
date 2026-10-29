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
:root{
  --bg:#05070a; --panel:#0c1016; --line:#1b222c;
  --fg:#d8d2c6; --muted:#7d8694;
  --amber:#ffcf4d; --orange:#ff5f1f; --magenta:#ff3fa4; --cyan:#4fd6d6;
  --ok:#5fd38d; --warn:#ffcf4d; --bad:#ff5f5f;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--fg);
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
body{padding:0 0 calc(18px + env(safe-area-inset-bottom));
  padding-top:env(safe-area-inset-top);max-width:560px;margin:0 auto}
header{padding:18px 18px 10px}
h1{margin:0;font-size:19px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--orange);font-weight:600}
header p{margin:4px 0 0;color:var(--muted);font-size:13px}

#shot{position:relative;background:#000;aspect-ratio:16/9;overflow:hidden}
#shot img{width:100%;height:100%;object-fit:contain;display:block}
#wait{position:absolute;inset:0;display:grid;place-items:center;
  color:var(--muted);font-size:13px;text-align:center;padding:16px}
#shot.live #wait{display:none}

#chips{display:flex;gap:6px;overflow-x:auto;padding:10px 12px;scrollbar-width:none}
#chips::-webkit-scrollbar{display:none}
.chip{flex:0 0 auto;background:var(--panel);border:1px solid var(--line);
  border-radius:999px;padding:5px 11px;font-size:12px;white-space:nowrap}
.chip s{text-decoration:none;color:var(--muted);margin-right:5px}
.chip.ok b{color:var(--ok)} .chip.warn b{color:var(--warn)} .chip.bad b{color:var(--bad)}

.go{display:block;margin:14px 14px 10px;padding:17px 18px;text-align:center;
  background:var(--orange);color:#05070a;font-weight:700;font-size:17px;
  text-decoration:none;border-radius:12px;letter-spacing:.02em}
.go:active{filter:brightness(.88)}
.hint{margin:0 18px;color:var(--muted);font-size:13px;text-align:center}
.hint b{color:var(--fg);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
footer{margin:18px 18px 0;padding-top:12px;border-top:1px solid var(--line);
  color:var(--muted);font-size:12px}
</style></head><body>

<header>
  <h1>Venator Drone</h1>
  <p>Wildlife and search camera &middot; connected</p>
</header>

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

function chip(label, value, cls){
  return `<div class="chip ${cls||''}"><s>${label}</s><b>${value}</b></div>`;
}
function status(){
  fetch(auth('/api/status')).then(r => r.json()).then(s => {
    const out = [];
    if (s.camera === 'offline'){
      out.push(chip('camera', 'offline', 'bad'));
    } else {
      out.push(chip('camera', 'live', 'ok'));
      if (s.fps != null) out.push(chip('fps', s.fps.toFixed(1), s.fps >= 8 ? 'ok' : 'warn'));
    }
    if (s.counts) for (const [k, v] of Object.entries(s.counts)) out.push(chip(k, v, 'ok'));
    if (s.active) out.push(chip('tracking', s.active));
    if (s.temp != null) out.push(chip('soc', s.temp.toFixed(0) + '°C', s.temp < 70 ? 'ok' : 'bad'));
    if (s.pm) out.push(chip('power', s.pm, String(s.pm).startsWith('7W') ? 'ok' : 'warn'));
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
