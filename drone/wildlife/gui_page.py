#!/usr/bin/env python3
"""The operator GUI's single page: markup, style and script.

Separate from gui_server.py because the old inline STREAM_PAGE in
camera_publisher.py was 58 lines and already at the edge of readable; a field
interface is several hundred.

Design notes that are not obvious from the code
-----------------------------------------------
Dark is forced, and red/amber dominant. This gets read at night by someone who
then has to look up and find a drone: blue and white light destroy scotopic
adaptation for tens of minutes, deep red barely touches it. There is no
prefers-color-scheme light branch on purpose - a white screen here is a
usability fault, not a preference.

Boxes are drawn on a canvas over the video rather than burned into the frame.
The Jetson has no hardware encoder, so burning them in would cost a decode and
a re-encode of every frame; this way the overlay is crisp at any zoom, layers
can be toggled, and the host cost is zero. The trade is that the video and the
detection stream are independent, so boxes can lead or lag the picture by about
one frame (~100 ms at 10 fps). That is the right trade, but it is a trade.

The status and alert panel is built to work with **no video at all**. Past
about 100 m the Wi-Fi link is gone while LoRa still carries status, and that is
the normal operating case rather than an error - so the video pane degrades to
a dimmed last frame with a clear banner, and everything else keeps working.
"""

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>VENATOR</title>
<style>
:root{
  --bg:#05070a; --panel:#0c1016; --line:#1b222c;
  --fg:#d8d2c6;            /* never pure white */
  --muted:#7d8694;
  --amber:#ffcf4d;         /* animal */
  --orange:#ff5f1f;        /* accent, alerts */
  --magenta:#ff3fa4;       /* person - highest salience, stays distinct under red light */
  --cyan:#4fd6d6;          /* vehicle */
  --ok:#5fd38d; --warn:#ffcf4d; --bad:#ff5f5f;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
body{padding-bottom:calc(64px + env(safe-area-inset-bottom))}
#redfilter{position:fixed;inset:0;pointer-events:none;z-index:50;background:#f00;
  opacity:0;mix-blend-mode:multiply;transition:opacity .2s}
#dimmer{position:fixed;inset:0;pointer-events:none;z-index:51;background:#000;opacity:0}

/* --- alert banner: sticky, no auto-dismiss, explicit ack --- */
#alerts{position:sticky;top:0;z-index:40}
.alert{background:#2a0a0a;border-bottom:2px solid var(--bad);padding:10px 14px;
  display:flex;gap:10px;align-items:center;animation:pulse 1.4s ease-in-out infinite}
@keyframes pulse{0%,100%{background:#2a0a0a}50%{background:#3d0d0d}}
@media (prefers-reduced-motion:reduce){.alert{animation:none}}
/* --- vest search: what the aircraft is looking for, above everything else --- */
#search{display:none;flex-wrap:wrap;align-items:baseline;gap:4px 12px;
  padding:10px 14px;background:#11141a;font-variant-numeric:tabular-nums}
#search.on{display:flex}
#search b{letter-spacing:.04em}
#search.found b{color:#ffe600}
#search .d{color:var(--muted);font-size:12px}
/* view-only visitors can look at everything and change nothing */
.viewonly #snap,.viewonly #lb-foot,.viewonly .shot .v{display:none}
/* --- confidence chart: only shown during a search --- */
#conf{display:none;border-bottom:1px solid var(--line);padding:0 8px 8px;background:var(--panel)}
#conf.on{display:block}
#conf .head{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:8px 2px 4px}
#conf .ttl{font-weight:600;margin-right:auto}
#conf .head button{padding:4px 10px;font-size:12px}
#plot{position:relative}
#chart{display:block;width:100%;height:150px;touch-action:pan-y}
#ctip{display:none;position:absolute;top:4px;background:rgba(2,3,5,.92);
  border:1px solid var(--line);border-radius:6px;padding:5px 8px;font-size:12px;
  pointer-events:none;font-variant-numeric:tabular-nums;white-space:nowrap}
#ctip .row{display:flex;align-items:center;gap:6px}
#ctip .row b{min-width:34px;text-align:right}
#ctip .row span{color:var(--muted)}
#legend{display:flex;flex-wrap:wrap;gap:3px 12px;padding:4px 2px 0;font-size:12px}
.key{display:inline-flex;align-items:center;gap:5px}
.key i,#ctip i{display:inline-block;width:14px;height:2px;border-radius:1px}
.key.more{color:var(--muted)}
#snaps .bar{display:flex;align-items:center;gap:8px;padding:10px 2px 4px;font-size:12px;color:var(--muted)}
#snaps .bar button{margin-left:auto;padding:4px 10px;font-size:12px}
.snap{border-top:1px solid var(--line);padding:8px 2px}
.snap .when{font-size:12px;color:var(--muted);margin-bottom:4px}
.snap img{display:block;width:100%;border-radius:4px;background:var(--bg)}
.snap table{width:100%;border-collapse:collapse;margin-top:6px;font-size:12px;
  font-variant-numeric:tabular-nums}
.snap th{color:var(--muted);font-weight:500;text-align:right;padding:2px 4px}
.snap td{text-align:right;padding:2px 4px;border-top:1px solid var(--line)}
.snap th:first-child,.snap td:first-child{text-align:left}
.alert b{color:var(--bad);letter-spacing:.04em}
.alert .meta{color:var(--muted);font-size:12px}
.alert button{margin-left:auto}

/* --- video --- */
#stage{position:relative;background:#000;aspect-ratio:16/9;width:100%;overflow:hidden}
#stage img{width:100%;height:100%;object-fit:contain;display:block}
#stage canvas{position:absolute;inset:0;width:100%;height:100%}
#nolink{position:absolute;inset:0;display:none;place-items:center;text-align:center;
  background:rgba(5,7,10,.72);color:var(--warn);padding:16px;font-size:13px}
#nolink.on{display:grid}
#stage.stale img{filter:grayscale(1) brightness(.45)}

/* --- chips --- */
#chips{display:flex;gap:6px;overflow-x:auto;padding:8px 10px;scrollbar-width:none;
  border-bottom:1px solid var(--line)}
#chips::-webkit-scrollbar{display:none}
.chip{flex:0 0 auto;background:var(--panel);border:1px solid var(--line);
  border-radius:999px;padding:5px 11px;font-size:12px;white-space:nowrap}
.chip s{text-decoration:none;color:var(--muted);margin-right:5px}
.chip.ok b{color:var(--ok)} .chip.warn b{color:var(--warn)} .chip.bad b{color:var(--bad)}

/* --- track list --- */
h2{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
  margin:16px 12px 6px}
#tracks{margin:0 8px}
.trk{display:flex;gap:10px;align-items:baseline;padding:8px 10px;
  border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
.trk.gone{opacity:.4}
.trk .cls{font-weight:600;min-width:62px}
.trk .cls.animal{color:var(--amber)} .trk .cls.person{color:var(--magenta)}
.trk .cls.vehicle{color:var(--cyan)}
.trk .d{color:var(--muted);font-size:12px}
.trk .r{margin-left:auto;color:var(--muted);font-size:12px}
.empty{color:var(--muted);padding:10px;font-size:13px}

/* --- filmstrip --- */
#film{display:flex;gap:6px;overflow-x:auto;padding:4px 8px 10px;scrollbar-width:none}
#film::-webkit-scrollbar{display:none}
.shot{flex:0 0 auto;width:104px}
.shot img{width:104px;height:59px;object-fit:cover;background:#000;
  border:1px solid var(--line);border-radius:4px;display:block}
.shot .t{font-size:10px;color:var(--muted);margin-top:2px;text-align:center}
.shot .v{display:flex;gap:4px;margin-top:3px}
.shot .v button{flex:1;padding:3px 0;font-size:11px}
.shot.judged img{border-color:var(--ok)}
.shot.wrong img{border-color:var(--bad)}

/* --- lightbox: one evidence frame, large, with its boxes drawn on --- */
#lb-wrap{position:fixed;inset:0;z-index:60;display:none;
  background:rgba(2,3,5,.96);flex-direction:column}
#lb-wrap.on{display:flex}
#lb-stage{position:relative;flex:1;min-height:0;display:grid;place-items:center}
#lb-img{max-width:100%;max-height:100%;object-fit:contain;display:block}
#lb-ovl{position:absolute;pointer-events:none}
#lb-head{display:flex;gap:10px;align-items:center;padding:10px 12px;
  padding-top:calc(10px + env(safe-area-inset-top));border-bottom:1px solid var(--line)}
#lb-head .nm{font-variant-numeric:tabular-nums;font-size:13px;color:var(--muted)}
#lb-head button{margin-left:auto}
#lb-meta{padding:8px 12px;border-top:1px solid var(--line);max-height:30vh;overflow-y:auto}
#lb-meta .row{display:flex;gap:10px;align-items:baseline;padding:4px 0;
  font-variant-numeric:tabular-nums;font-size:13px}
#lb-meta .row .cls{font-weight:600;min-width:62px}
#lb-meta .row .cls.animal{color:var(--amber)} #lb-meta .row .cls.person{color:var(--magenta)}
#lb-meta .row .cls.vehicle{color:var(--cyan)}
#lb-meta .row .d{color:var(--muted)}
#lb-foot{display:flex;gap:8px;padding:9px 12px calc(9px + env(safe-area-inset-bottom));
  border-top:1px solid var(--line)}
#lb-foot button{flex:1}
#lb-foot button.keep.on{border-color:var(--ok);color:var(--ok)}
#lb-foot button.drop.on{border-color:var(--bad);color:var(--bad)}
.shot img{cursor:zoom-in}

/* --- controls --- */
button,select{background:var(--panel);color:var(--fg);border:1px solid var(--line);
  border-radius:8px;padding:9px 13px;font:inherit;font-size:13px;min-height:38px}
button:active{background:#18202b}
button.on{border-color:var(--orange);color:var(--orange)}
#bar{position:fixed;left:0;right:0;bottom:0;z-index:45;display:flex;gap:8px;
  padding:9px 10px calc(9px + env(safe-area-inset-bottom));
  background:rgba(8,11,16,.94);border-top:1px solid var(--line);
  backdrop-filter:blur(8px);overflow-x:auto;scrollbar-width:none}
#bar::-webkit-scrollbar{display:none}
#bar>*{flex:0 0 auto}
label.sl{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--muted)}
input[type=range]{width:88px;accent-color:var(--orange)}
</style></head><body>

<div id="redfilter"></div><div id="dimmer"></div>
<div id="alerts"></div>
<div id="search"></div>

<div id="stage">
  <img id="vid" alt="">
  <canvas id="ovl"></canvas>
  <div id="nolink">
    <div><b>video link lost</b><br>
    <span style="color:var(--muted)">Status below is still live while the page is
    connected. Beyond ~100 m this is normal — fall back to the LoRa link.</span></div>
  </div>
</div>

<div id="conf">
  <div class="head">
    <span class="ttl" id="conf-ttl">Vest match</span>
    <button id="m-match" class="on">match</button>
    <button id="m-person">person</button>
    <button id="csnap">snapshot</button>
  </div>
  <div id="plot"><canvas id="chart" role="img"
    aria-label="Confidence for each person over the last 30 seconds. The same readings are in the Tracks list and in snapshots."></canvas>
    <div id="ctip"></div></div>
  <div id="legend"></div>
  <div id="snaps"></div>
</div>

<div id="chips"></div>

<h2>Tracks</h2>
<div id="tracks"><div class="empty">nothing detected</div></div>

<h2>Evidence <span id="filmn" style="color:var(--muted)"></span></h2>
<div id="film"></div>

<div id="lb-wrap">
  <div id="lb-head">
    <span class="nm" id="lb-name"></span>
    <button id="lb-prev" title="older">&lsaquo;</button>
    <button id="lb-next" title="newer">&rsaquo;</button>
    <button id="lb-boxes" class="on">boxes</button>
    <button id="lb-close">close</button>
  </div>
  <div id="lb-stage"><img id="lb-img" alt=""><canvas id="lb-ovl"></canvas></div>
  <div id="lb-meta"></div>
  <div id="lb-foot">
    <button class="keep" id="lb-ok">&check; correct</button>
    <button class="drop" id="lb-no">&cross; wrong</button>
  </div>
</div>

<div id="bar">
  <select id="q" title="video quality"></select>
  <button id="bx" class="on">boxes</button>
  <button id="lb" class="on">labels</button>
  <button id="red">red</button>
  <label class="sl">dim <input type="range" id="dim" min="0" max="85" value="0"></label>
  <button id="snap">mark</button>
</div>

<script>
const TOKEN = __TOKEN__, QUALITIES = __QUALITIES__, VIEW_ONLY = __VIEW_ONLY__;
const q = s => document.querySelector(s);
document.body.classList.toggle('viewonly', VIEW_ONLY);
const auth = u => u + (u.includes('?') ? '&' : '?') + (TOKEN ? 'k=' + TOKEN : '');
// A view-only visitor's writes would only earn a 403 and a growing delay. Quality
// and alert dismissal still work for them, because both are also local.
const api = (p, body) => (VIEW_ONLY && body) ? Promise.resolve() : fetch(auth(p), body ? {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)} : {});

/* ---------- video ---------- */
let quality = 'hi', lastFrame = 0;
const vid = q('#vid'), stage = q('#stage');
function loadVideo(){
  quality = q('#q').value;
  // Cache-bust so a reconnect does not resume the old multipart response.
  vid.src = auth('/live.mjpg?q=' + quality + '&_=' + Date.now());
}
const qsel = q('#q');
for (const name in QUALITIES){
  const [[w,h],qa] = QUALITIES[name];
  qsel.add(new Option(`${w}×${h} q${qa}`, name));
}
qsel.onchange = () => { loadVideo(); api('/api/config', {quality:qsel.value}); };
vid.onload = vid.onloadeddata = () => { lastFrame = Date.now(); };
// MJPEG delivers one long-lived response; onload fires per part in most
// browsers but not reliably, so treat "detections arriving" as liveness too.
setInterval(() => {
  const stale = Date.now() - lastFrame > 4000;
  stage.classList.toggle('stale', stale);
  q('#nolink').classList.toggle('on', stale);
}, 1000);
vid.onerror = () => setTimeout(loadVideo, 2000);

/* ---------- box overlay ---------- */
const ovl = q('#ovl'), ctx = ovl.getContext('2d');
const COLOUR = {animal:'#ffcf4d', person:'#ff3fa4', vehicle:'#4fd6d6'};
// The vest search. The target is the only loud thing on screen: everyone else
// fading to grey is the point being demonstrated.
const ROLE = {target:'#ffe600', match:'#ffb000', checking:'#e8edf2', ignored:'#7d8590'};
const boxColour = d => ROLE[d.role] || COLOUR[d.c] || '#fff';
let lastSearch = null;
function roleLabel(d){
  const z = d.xyz ? d.xyz[2].toFixed(1) + ' m' : '';
  const worn = d.vest ? ' ' + d.vest : '';
  const need = lastSearch && lastSearch.vote_need;
  return {target:`TARGET ${z}`, match:`also matches ${z}`,
          checking:`checking ${d.votes||0}/${need||'?'}`,
          ignored:`ignored${worn}`}[d.role];
}
let dets = [], showBox = true, showLab = true;
function sizeCanvas(){
  // Back the canvas at device resolution, or the strokes blur on a phone.
  const r = ovl.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  ovl.width = Math.round(r.width * dpr); ovl.height = Math.round(r.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
addEventListener('resize', () => { sizeCanvas(); draw(); });
function draw(){
  const r = ovl.getBoundingClientRect();
  ctx.clearRect(0, 0, r.width, r.height);
  if (!showBox) return;
  // The video is object-fit:contain, so letterbox bars may exist inside the
  // element. Boxes are normalised to the *frame*, so map through the frame's
  // real on-screen rectangle rather than the element's.
  const ar = (vid.naturalWidth || 16) / (vid.naturalHeight || 9);
  let w = r.width, h = r.width / ar, ox = 0, oy = (r.height - h) / 2;
  if (h > r.height){ h = r.height; w = r.height * ar; oy = 0; ox = (r.width - w) / 2; }
  ctx.font = '600 12px ui-sans-serif,system-ui,sans-serif';
  for (const d of dets){
    const c = boxColour(d);
    const x = ox + d.b[0]*w, y = oy + d.b[1]*h;
    const bw = (d.b[2]-d.b[0])*w, bh = (d.b[3]-d.b[1])*h;
    ctx.lineWidth = d.role === 'target' ? 4 : 2;
    ctx.strokeStyle = c; ctx.strokeRect(x, y, bw, bh);
    if (!showLab) continue;
    const z = d.xyz ? d.xyz[2].toFixed(1) + ' m' : '';
    const idtag = d.id !== undefined ? `#${d.id} ` : '';
    const txt = roleLabel(d) || `${idtag}${d.c} ${Math.round(d.p*100)}% ${z}`;
    const tw = ctx.measureText(txt).width + 8;
    const ty = y > 16 ? y - 16 : y + bh;
    ctx.fillStyle = 'rgba(5,7,10,.78)'; ctx.fillRect(x, ty, tw, 16);
    ctx.fillStyle = c; ctx.fillText(txt, x + 4, ty + 12);
  }
}
q('#bx').onclick = e => { showBox = !showBox; e.target.classList.toggle('on', showBox); draw(); };
q('#lb').onclick = e => { showLab = !showLab; e.target.classList.toggle('on', showLab); draw(); };

/* ---------- tracks ---------- */
function renderTracks(){
  const el = q('#tracks');
  if (!dets.length){ el.innerHTML = '<div class="empty">nothing detected</div>'; return; }
  // Longest-standing first: dwell is the interesting axis once there is
  // tracking, because it separates something passing through from something
  // that has settled - which is the whole basis of the SAR gate.
  el.innerHTML = dets.slice().sort((a,b) => (b.dwell||0) - (a.dwell||0))
    .map(d => {
      const z = d.xyz ? d.xyz[2].toFixed(1) + ' m' : '--';
      const len = d.len_m ? d.len_m.toFixed(1) + ' m' : '';
      const raw = (d.vest || d.raw) ? ` <span class="d">(${d.vest || d.raw})</span>` : '';
      const id = d.id !== undefined ? `<span class="d">#${d.id}</span>` : '';
      const dw = d.dwell ? `<span class="d">${d.dwell.toFixed(0)} s</span>` : '';
      const gone = d.st && d.st !== 'TRACKED' ? ' gone' : '';
      const tone = d.role ? ` style="color:${boxColour(d)}"` : '';
      return `<div class="trk${gone}">${id}<span class="cls ${d.c}"${tone}>${d.role || d.c}</span>${raw}
        <span class="d">${Math.round(d.p*100)}%</span>
        ${dw}<span class="d">${len}</span><span class="r">${z}</span></div>`;
    }).join('');
}

/* ---------- vest search ---------- */
function renderSearch(s){
  const el = q('#search'), on = !!(s && s.target);
  lastSearch = s || null;
  el.classList.toggle('on', on);
  q('#conf').classList.toggle('on', on);
  if (!on) return;
  const name = s.target.toUpperCase() + ' VEST';
  const head = {found:`FOUND: ${name}`, lost:`LOST SIGHT OF ${name}`,
                checking:`CHECKING FOR ${name}`}[s.state] || `SEARCHING FOR ${name}`;
  const bits = [];
  if (s.state === 'found' && s.z) bits.push(s.z.toFixed(1) + ' m away');
  if (s.matches > 1) bits.push(`${s.matches} people match`);
  bits.push(`${s.ignored || 0} ignored`);
  el.classList.toggle('found', s.state === 'found');
  el.innerHTML = `<b>${head}</b><span class="d">${bits.join(' &middot; ')}</span>`;
}

/* ---------- confidence chart ---------- */
// One line per person, the last 30 s, so the decision can be watched: the person
// in the target vest climbs past the threshold while everyone else stays flat.
// Colour follows the vest, not the line's rank, so a person keeps their colour
// as others come and go. Checked against this panel's surface: all three pass
// colour-blind separation and contrast. Yellow is lighter than the usual limit
// for a chart line, on purpose. Dark enough to meet it, it turns olive and can
// no longer be told from red with colour blindness.
const VEST_LINE = {red:'#e5484d', yellow:'#dcb40a', blue:'#4c8dff'};
const NO_VEST = '#6e7681';
const INK = {fg:'#d8d2c6', muted:'#7d8694', grid:'#1b222c', rule:'#3a4452', surface:'#0c1016'};
const CHART_S = 30, MAX_LINES = 5, GAP_S = 1.0;
const METRIC = {match:{i:1, title:'Vest match', name:'vest match'},
                person:{i:2, title:'Person confidence', name:'person'}};
const chart = q('#chart'), cctx = chart.getContext('2d');
const people = new Map();     // track id -> {id, vest, role, pts:[[t, match, person]]}
let metric = 'match', chartNow = 0, crossX = null, legendKey = '', chartTarget = null;

function recordConfidence(ev){
  // A match is against one colour, so a new target makes the old lines meaningless.
  if (ev.search.target !== chartTarget){ people.clear(); chartTarget = ev.search.target; }
  chartNow = ev.t;
  for (const d of ev.d || []){
    if (d.c !== 'person' || d.match === undefined) continue;
    let s = people.get(d.id);
    if (!s){ s = {id:d.id, pts:[]}; people.set(d.id, s); }
    s.vest = d.vest; s.role = d.role;
    // A predicted box is not a reading, so it leaves a gap in the line.
    if (d.st === 'TRACKED' || d.st === 'NEW') s.pts.push([ev.t, d.match, d.p]);
  }
  for (const [id, s] of people){
    while (s.pts.length && s.pts[0][0] < chartNow - CHART_S) s.pts.shift();
    if (!s.pts.length) people.delete(id);
  }
}
const lineColour = s => VEST_LINE[s.vest] || NO_VEST;
const ROLE_ORDER = {target:0, match:1, checking:2};
function shownPeople(){
  return [...people.values()].sort((a,b) =>
    (ROLE_ORDER[a.role] ?? 3) - (ROLE_ORDER[b.role] ?? 3) || a.id - b.id);
}
function drawChart(){
  if (!q('#conf').classList.contains('on')) return;
  const r = chart.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  if (chart.width !== Math.round(r.width*dpr) || chart.height !== Math.round(r.height*dpr)){
    chart.width = Math.round(r.width*dpr); chart.height = Math.round(r.height*dpr);
  }
  const c = cctx, W = r.width, H = r.height;
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.fillStyle = INK.surface; c.fillRect(0, 0, W, H);
  const L = 34, R = 62, T = 8, B = 18, PW = W - L - R, PH = H - T - B;
  const X = t => L + (1 - (chartNow - t) / CHART_S) * PW, Y = v => T + (1 - v) * PH;
  c.font = '11px ui-sans-serif,system-ui,sans-serif'; c.lineWidth = 1;
  c.textBaseline = 'middle'; c.textAlign = 'right';
  for (const v of [0, .5, 1]){
    c.strokeStyle = INK.grid; c.beginPath(); c.moveTo(L, Y(v)); c.lineTo(L + PW, Y(v)); c.stroke();
    c.fillStyle = INK.muted; c.fillText(Math.round(v*100) + '%', L - 6, Y(v));
  }
  c.textAlign = 'left'; c.textBaseline = 'alphabetic';
  c.fillText('30 s ago', L, H - 4);
  c.textAlign = 'right'; c.fillText('now', L + PW, H - 4);
  const need = metric === 'match' && lastSearch && lastSearch.min_share;
  if (need){
    c.strokeStyle = INK.rule; c.beginPath(); c.moveTo(L, Y(need)); c.lineTo(L + PW, Y(need)); c.stroke();
    c.textAlign = 'left'; c.fillStyle = INK.muted;
    c.fillText(`match line ${Math.round(need*100)}%`, L + 4, Y(need) - 4);
  }
  const m = METRIC[metric].i, shown = shownPeople().slice(0, MAX_LINES), ends = [];
  c.lineWidth = 2; c.lineJoin = c.lineCap = 'round';
  for (const s of shown){
    c.strokeStyle = lineColour(s); c.beginPath();
    let prev = null;
    for (const p of s.pts){
      if (prev && p[0] - prev[0] <= GAP_S) c.lineTo(X(p[0]), Y(p[m]));
      else c.moveTo(X(p[0]), Y(p[m]));
      prev = p;
    }
    c.stroke();
    const last = s.pts[s.pts.length - 1];
    ends.push({s, last, x:X(last[0]), y:Y(last[m]), v:last[m]});
  }
  // End dots carry a surface ring so they stay legible where they overlap.
  for (const e of ends){
    c.beginPath(); c.arc(e.x, e.y, 6, 0, 7); c.fillStyle = INK.surface; c.fill();
    c.beginPath(); c.arc(e.x, e.y, 4, 0, 7); c.fillStyle = lineColour(e.s); c.fill();
  }
  // Decoys all sit near zero, so nudge their labels apart rather than overprint.
  c.font = '600 11px ui-sans-serif,system-ui,sans-serif';
  c.textAlign = 'left'; c.textBaseline = 'middle';
  ends.sort((a,b) => a.y - b.y);
  let floor = -Infinity;
  for (const e of ends){ e.ly = Math.max(e.y, floor + 13); floor = e.ly; }
  // Anything pushed off the bottom moves back up, and only as far as it has to,
  // so a label near the top stays where its line is.
  let ceiling = T + PH + 6;
  for (const e of ends.slice().reverse()){
    e.ly = Math.min(e.ly, ceiling); ceiling = e.ly - 13;
  }
  for (const e of ends){
    c.fillStyle = e.s.role === 'target' ? INK.fg : INK.muted;
    c.fillText(`#${e.s.id} ${Math.round(e.v*100)}%`, L + PW + 9, e.ly);
  }
  if (crossX !== null && crossX >= L && crossX <= L + PW){
    c.strokeStyle = INK.rule; c.lineWidth = 1;
    c.beginPath(); c.moveTo(crossX, T); c.lineTo(crossX, T + PH); c.stroke();
    showTip(chartNow - (1 - (crossX - L) / PW) * CHART_S, shown, m, W);
  } else {
    q('#ctip').style.display = 'none';
  }
  renderLegend(shown);
}
function showTip(t, shown, m, W){
  const tip = q('#ctip');
  tip.textContent = '';
  for (const s of shown){
    let best = null;
    for (const p of s.pts) if (!best || Math.abs(p[0]-t) < Math.abs(best[0]-t)) best = p;
    if (!best || Math.abs(best[0]-t) > GAP_S) continue;
    const row = document.createElement('div'); row.className = 'row';
    const key = document.createElement('i'); key.style.background = lineColour(s);
    const val = document.createElement('b'); val.textContent = Math.round(best[m]*100) + '%';
    const who = document.createElement('span');
    who.textContent = `#${s.id} ${s.vest || 'no vest'}`;
    row.append(key, val, who); tip.append(row);
  }
  tip.style.display = tip.childElementCount ? 'block' : 'none';
  const left = crossX + 10 + tip.offsetWidth > W ? crossX - 10 - tip.offsetWidth : crossX + 10;
  tip.style.left = Math.max(0, left) + 'px';
}
function renderLegend(shown){
  const hidden = people.size - shown.length;
  const k = shown.map(s => `${s.id}${s.vest}${s.role}`).join() + hidden;
  if (k === legendKey) return;
  legendKey = k;
  const el = q('#legend');
  el.textContent = '';
  for (const s of shown){
    const key = document.createElement('span'); key.className = 'key';
    const line = document.createElement('i'); line.style.background = lineColour(s);
    const name = document.createElement('span');
    name.textContent = `#${s.id} ${s.vest || 'no vest'}` + (s.role === 'target' ? ' (target)' : '');
    key.append(line, name); el.append(key);
  }
  if (hidden > 0){
    const more = document.createElement('span'); more.className = 'key more';
    more.textContent = `+${hidden} more in Tracks`; el.append(more);
  }
}
const setCross = e => { crossX = e.clientX - chart.getBoundingClientRect().left; drawChart(); };
chart.addEventListener('pointermove', setCross);
chart.addEventListener('pointerdown', setCross);
for (const end of ['pointerleave','pointercancel'])
  chart.addEventListener(end, () => { crossX = null; drawChart(); });
addEventListener('resize', drawChart);
function setMetric(name){
  metric = name;
  q('#conf-ttl').textContent = METRIC[name].title;
  q('#m-match').classList.toggle('on', name === 'match');
  q('#m-person').classList.toggle('on', name === 'person');
  drawChart();
}
q('#m-match').onclick = () => setMetric('match');
q('#m-person').onclick = () => setMetric('person');

/* ---------- confidence snapshots: this phone only, nothing goes to the drone ---------- */
const snaps = [];
const SNAP_COLUMNS = ['track','role','vest','vest match','person','distance'];
q('#csnap').onclick = () => {
  const s = lastSearch || {};
  snaps.unshift({
    t: chartNow, target: s.target, state: s.state, chart: chart.toDataURL('image/png'),
    rows: dets.filter(d => d.c === 'person' && d.match !== undefined).map(d => ({
      id: d.id, role: d.role || '', vest: d.vest || 'no vest', match: d.match, p: d.p,
      z: d.xyz && d.xyz[2] > 0 ? d.xyz[2] : null})),
  });
  if (snaps.length > 20) snaps.pop();
  renderSnaps();
};
const snapTime = t => new Date(t*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
function renderSnaps(){
  const el = q('#snaps');
  el.textContent = '';
  if (!snaps.length) return;
  const bar = document.createElement('div'); bar.className = 'bar';
  const n = document.createElement('span');
  n.textContent = `${snaps.length} snapshot${snaps.length > 1 ? 's' : ''} on this phone`;
  const save = document.createElement('button'); save.textContent = 'save CSV'; save.onclick = saveSnaps;
  bar.append(n, save); el.append(bar);
  for (const s of snaps){
    const card = document.createElement('div'); card.className = 'snap';
    const when = document.createElement('div'); when.className = 'when';
    when.textContent = `${snapTime(s.t)}, ${s.target} vest, ${s.state}`;
    const img = document.createElement('img'); img.src = s.chart; img.alt = 'confidence chart at this moment';
    const table = document.createElement('table');
    const head = table.insertRow();
    for (const name of SNAP_COLUMNS){
      const th = document.createElement('th'); th.textContent = name; head.append(th);
    }
    for (const row of s.rows){
      const tr = table.insertRow();
      for (const v of [`#${row.id}`, row.role, row.vest, Math.round(row.match*100) + '%',
                       Math.round(row.p*100) + '%', row.z ? row.z.toFixed(1) + ' m' : '--'])
        tr.insertCell().textContent = v;
    }
    card.append(when, img, table); el.append(card);
  }
}
function saveSnaps(){
  const lines = ['time,target,state,track,role,vest,vest_match,person_confidence,distance_m'];
  for (const s of snaps.slice().reverse())
    for (const r of s.rows)
      lines.push([new Date(s.t*1000).toISOString(), s.target, s.state, r.id, r.role, r.vest,
                  r.match, r.p, r.z ?? ''].join(','));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([lines.join(String.fromCharCode(10))], {type:'text/csv'}));
  a.download = 'venator-confidence.csv';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* ---------- chips ---------- */
function chip(label, value, cls){
  return `<div class="chip ${cls||''}"><s>${label}</s><b>${value}</b></div>`;
}
function renderChips(s){
  const t = s.temp, w = s.watts, usb = s.usb, rssi = s.link && s.link.rssi;
  // The camera can be absent while the page is perfectly healthy - the OAK
  // has been seen to drop off the USB bus. Say so plainly instead of showing
  // 0 fps and letting the operator guess which half is broken.
  if (s.camera === 'offline'){
    q('#nolink').innerHTML = '<div><b>camera offline</b><br>'
      + '<span style="color:var(--muted)">' + (s.error || '')
      + '<br>Retrying. Evidence review below still works.</span></div>';
    q('#nolink').classList.add('on');
    stage.classList.add('stale');
  }
  const out = [
    s.camera === 'offline'
      ? chip('camera', 'offline', 'bad')
      : chip('fps', (s.fps ?? 0).toFixed(1), s.fps >= 8 ? 'ok' : 'warn'),
    chip('model', s.model || '--'),
    chip('mode', s.pm || '--', (s.pm||'').startsWith('7W') ? 'ok' : 'warn'),
    w != null ? chip('draw', w.toFixed(2) + ' W') : '',
    t != null ? chip('soc', t.toFixed(0) + '°C', t < 70 ? 'ok' : 'bad') : '',
    usb ? chip('usb', usb >= 5000 ? '5 Gb/s' : usb + ' Mb/s',
               usb >= 5000 ? 'ok' : 'warn') : '',
    rssi != null ? chip('rssi', rssi + ' dBm', rssi > -70 ? 'ok' : 'warn') : '',
    chip('gps', (s.gps && s.gps.fix) || '--', 'warn'),
    s.active !== undefined ? chip('tracking', s.active) : '',
    s.saved !== undefined ? chip('saved', s.saved) : '',
    // Distinct objects over the sortie, by tracker id - "3 animals" means
    // three creatures, not three frames that happened to contain one.
    s.counts ? Object.entries(s.counts).map(([k,v]) => chip(k, v, 'ok')).join('') : '',
  ];
  q('#chips').innerHTML = out.join('');
}

/* ---------- alerts: explicit ack, survives reconnect ---------- */
const acked = new Set(JSON.parse(sessionStorage.getItem('acked') || '[]'));
let alerts = [];
function renderAlerts(){
  q('#alerts').innerHTML = alerts.filter(a => !acked.has(a.id)).map(a => `
    <div class="alert"><b>${(a.kind||'alert').replace(/_/g,' ').toUpperCase()}</b>
    <span class="meta">${Math.round((a.conf||0)*100)}%
      ${a.dwell ? '&middot; '+a.dwell.toFixed(0)+' s' : ''}
      ${a.rel ? '&middot; '+a.rel.rng+' m brg '+a.rel.brg+'°' : ''}
      ${a.ll ? '&middot; '+a.ll[0].toFixed(5)+', '+a.ll[1].toFixed(5) : '&middot; no GPS fix'}
    </span><button data-ack="${a.id}">ack</button></div>`).join('');
}
q('#alerts').onclick = e => {
  const id = e.target.dataset && e.target.dataset.ack;
  if (!id) return;
  acked.add(id); sessionStorage.setItem('acked', JSON.stringify([...acked]));
  api('/api/ack', {alert_id:id}); renderAlerts();
};
let beepOk = false;
addEventListener('pointerdown', () => { beepOk = true; }, {once:true});
function notify(){
  if (navigator.vibrate) navigator.vibrate([200,100,200]);
  if (!beepOk) return;            // iOS refuses audio before a user gesture
  try {
    const a = new (window.AudioContext||window.webkitAudioContext)();
    const o = a.createOscillator(), g = a.createGain();
    o.frequency.value = 880; o.connect(g); g.connect(a.destination);
    g.gain.value = .25; o.start(); setTimeout(() => { o.stop(); a.close(); }, 420);
  } catch(_){}
}

/* ---------- evidence filmstrip ---------- */
let shots = [];
function renderFilm(){
  q('#filmn').textContent = shots.length ? '(' + shots.length + ')' : '';
  // Lazy loading matters: browsers cap ~6 connections per origin and MJPEG
  // plus SSE already hold two.
  q('#film').innerHTML = shots.slice(0,40).map(s => {
    const v = s.verdict ? (s.verdict.ok ? 'judged' : 'wrong') : '';
    const ts = new Date(s.t*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
    return `<div class="shot ${v}" data-n="${s.name}">
      <img loading="lazy" src="${auth('/api/evidence/'+s.name)}" alt="">
      <div class="t">${ts} ${(s.classes||[]).join(',')}</div>
      <div class="v"><button data-ok="1">✓</button><button data-ok="0">✗</button></div>
    </div>`;
  }).join('');
}
q('#film').onclick = e => {
  const shot = e.target.closest('.shot'); if (!shot) return;
  const name = shot.dataset.n;
  const b = e.target.closest('button');
  if (!b) { openShot(shots.findIndex(x => x.name === name)); return; }
  const ok = b.dataset.ok === '1';
  judge(name, ok);
};

/* ---------- lightbox: one frame, large, with its boxes drawn on ---------- */
// The saved JPEG deliberately has no boxes burned into it - the camera's
// encoder writes the frame untouched - so the sidecar's normalised
// coordinates are replayed here. They are the same 16:9 crop the network saw,
// so they map onto the full-size image with no transform, exactly as on the
// live canvas.
let lbIdx = -1, lbName = null, lbBoxes = true;
const lbImg = q('#lb-img'), lbOvl = q('#lb-ovl'), lbCtx = lbOvl.getContext('2d');

// New frames are unshifted onto `shots`, so an index taken a moment ago points
// at a different picture once one arrives. The open frame is therefore tracked
// by name and the index re-derived - otherwise the image silently changes under
// whoever is reviewing it.
function syncLb(){
  if (lbName === null) return;
  const i = shots.findIndex(x => x.name === lbName);
  if (i < 0) { closeShot(); return; }
  lbIdx = i;
}

function openShot(i){
  if (i < 0 || i >= shots.length) return;
  lbIdx = i;
  const s = shots[i];
  lbName = s.name;
  q('#lb-name').textContent = s.name;
  lbImg.src = auth('/api/evidence/' + s.name);
  q('#lb-wrap').classList.add('on');
  const dets = s.detections || [];
  q('#lb-meta').innerHTML = dets.length ? dets.map(d => {
      const z = d.xyz ? d.xyz[2].toFixed(2) + ' m away' : '';
      const len = d.len_m ? d.len_m.toFixed(2) + ' m long' : '';
      const raw = d.raw ? ` <span class="d">(model said ${d.raw})</span>` : '';
      return `<div class="row"><span class="cls ${d.c}">${d.c}</span>${raw}
        <span class="d">${Math.round(d.p*100)}%</span>
        <span class="d">${z}</span><span class="d">${len}</span></div>`;
    }).join('')
    : '<div class="row"><span class="d">no detection record — this frame '
      + 'predates the sidecar files</span></div>';
  const v = s.verdict;
  q('#lb-ok').classList.toggle('on', !!(v && v.ok));
  q('#lb-no').classList.toggle('on', !!(v && !v.ok));
  drawShot();
}
function drawShot(){
  // Match the canvas to where the image actually sits: object-fit:contain
  // means the rendered box is not the element box.
  const ir = lbImg.getBoundingClientRect(), sr = q('#lb-stage').getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  lbOvl.style.left = (ir.left - sr.left) + 'px';
  lbOvl.style.top = (ir.top - sr.top) + 'px';
  lbOvl.style.width = ir.width + 'px'; lbOvl.style.height = ir.height + 'px';
  lbOvl.width = Math.round(ir.width * dpr); lbOvl.height = Math.round(ir.height * dpr);
  lbCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  lbCtx.clearRect(0, 0, ir.width, ir.height);
  if (!lbBoxes || lbIdx < 0) return;
  for (const d of (shots[lbIdx].detections || [])){
    const c = boxColour(d);
    const x = d.b[0]*ir.width, y = d.b[1]*ir.height;
    const bw = (d.b[2]-d.b[0])*ir.width, bh = (d.b[3]-d.b[1])*ir.height;
    lbCtx.lineWidth = 3; lbCtx.strokeStyle = c; lbCtx.strokeRect(x, y, bw, bh);
    const txt = roleLabel(d) || `${d.c} ${Math.round(d.p*100)}%` + (d.xyz ? ` ${d.xyz[2].toFixed(1)} m` : '');
    lbCtx.font = '600 15px ui-sans-serif,system-ui,sans-serif';
    const tw = lbCtx.measureText(txt).width + 10, ty = y > 20 ? y - 20 : y + bh;
    lbCtx.fillStyle = 'rgba(2,3,5,.82)'; lbCtx.fillRect(x, ty, tw, 20);
    lbCtx.fillStyle = c; lbCtx.fillText(txt, x + 5, ty + 15);
  }
}
lbImg.onload = drawShot;
addEventListener('resize', () => { if (lbIdx >= 0) drawShot(); });

function judge(name, ok){
  api('/api/verdict', {name, ok});
  const s = shots.find(x => x.name === name); if (s) s.verdict = {ok};
  const el = document.querySelector(`.shot[data-n="${name}"]`);
  if (el){ el.classList.toggle('judged', ok); el.classList.toggle('wrong', !ok); }
  if (lbIdx >= 0 && shots[lbIdx] && shots[lbIdx].name === name){
    q('#lb-ok').classList.toggle('on', ok);
    q('#lb-no').classList.toggle('on', !ok);
  }
}
function closeShot(){
  q('#lb-wrap').classList.remove('on'); lbIdx = -1; lbName = null;
}
q('#lb-close').onclick = closeShot;
// Newer frames sit at the start of the array, so "next" walks toward index 0.
q('#lb-prev').onclick = () => openShot(lbIdx + 1);
q('#lb-next').onclick = () => openShot(lbIdx - 1);
q('#lb-boxes').onclick = e => { lbBoxes = !lbBoxes;
  e.target.classList.toggle('on', lbBoxes); drawShot(); };
q('#lb-ok').onclick = () => judge(shots[lbIdx].name, true);
q('#lb-no').onclick = () => judge(shots[lbIdx].name, false);
q('#lb-stage').onclick = e => { if (e.target.id === 'lb-stage') closeShot(); };
addEventListener('keydown', e => {
  if (lbIdx < 0) return;
  if (e.key === 'Escape') closeShot();
  else if (e.key === 'ArrowLeft') openShot(lbIdx + 1);
  else if (e.key === 'ArrowRight') openShot(lbIdx - 1);
});
// Swipe, since this is mostly used one-handed on a phone.
let tx = 0;
q('#lb-stage').addEventListener('touchstart', e => { tx = e.touches[0].clientX; }, {passive:true});
q('#lb-stage').addEventListener('touchend', e => {
  const dx = e.changedTouches[0].clientX - tx;
  if (Math.abs(dx) > 60) openShot(lbIdx + (dx > 0 ? 1 : -1));
}, {passive:true});
q('#snap').onclick = () => api('/api/config', {save:true}).then(loadFilm);
function loadFilm(){
  fetch(auth('/api/evidence?n=40')).then(r => r.json())
    .then(j => { shots = j; renderFilm(); syncLb(); }).catch(()=>{});
}

/* ---------- night vision helpers ---------- */
q('#red').onclick = e => {
  const on = q('#redfilter').style.opacity !== '0.55';
  q('#redfilter').style.opacity = on ? 0.55 : 0;
  e.target.classList.toggle('on', on);
};
q('#dim').oninput = e => { q('#dimmer').style.opacity = e.target.value/100; };

/* ---------- SSE ---------- */
let es;
function connect(){
  es = new EventSource(auth('/events'));
  es.addEventListener('det', e => {
    const d = JSON.parse(e.data);
    dets = d.d || []; lastFrame = Date.now();
    renderSearch(d.search);
    if (d.search && d.search.target) recordConfidence(d);
    draw(); renderTracks(); drawChart();
  });
  es.addEventListener('status', e => renderChips(JSON.parse(e.data)));
  es.addEventListener('alert', e => {
    const a = JSON.parse(e.data);
    if (!alerts.some(x => x.id === a.id)) { alerts.unshift(a); notify(); }
    renderAlerts();
  });
  es.addEventListener('evidence', e => {
    const s = JSON.parse(e.data);
    if (!shots.some(x => x.name === s.name)) shots.unshift(s);
    renderFilm(); syncLb();
  });
  es.onerror = () => { es.close(); setTimeout(connect, 2000); };
}

sizeCanvas(); loadVideo(); connect(); loadFilm();
fetch(auth('/api/status')).then(r => r.json()).then(renderChips).catch(()=>{});
</script></body></html>
"""


def js_literal(value):
    """JSON, safe to paste between <script> tags.

    json.dumps alone is NOT enough, which is easy to miss: it escapes quotes
    and backslashes but leaves `<` and `>` alone, so a value containing
    "</script>" still closes the script block. An HTML parser ends a script at
    the first such sequence anywhere in the text, including inside what the
    JavaScript grammar considers a string literal - so the markup after it is
    parsed as markup.

    `\\u003c` is a valid JavaScript string escape and decodes to the same
    character, so the script sees the original value and the HTML parser never
    sees a closing tag. `&` is escaped too, for the same reason in attribute
    and HTML-entity contexts.
    """
    import json
    return (json.dumps(value)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026"))


def render(token, cfg, qualities, view_only=False):
    """The page, with the token and quality rungs baked in.

    Both go through js_literal rather than bare interpolation: the token is hex
    today and the rungs are numbers, but putting anything unencoded inside a
    <script> is the kind of shortcut that stops being safe the moment the
    format changes.
    """
    return (PAGE
            .replace("__TOKEN__", js_literal(token))
            .replace("__VIEW_ONLY__", js_literal(bool(view_only)))
            .replace("__QUALITIES__", js_literal(
                {k: [list(v[0]), v[1], v[2]] for k, v in qualities.items()})))
