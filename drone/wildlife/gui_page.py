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

<div id="stage">
  <img id="vid" alt="">
  <canvas id="ovl"></canvas>
  <div id="nolink">
    <div><b>video link lost</b><br>
    <span style="color:var(--muted)">Status below is still live while the page is
    connected. Beyond ~100 m this is normal — fall back to the LoRa link.</span></div>
  </div>
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
const TOKEN = __TOKEN__, QUALITIES = __QUALITIES__;
const q = s => document.querySelector(s);
const auth = u => u + (u.includes('?') ? '&' : '?') + (TOKEN ? 'k=' + TOKEN : '');
const api = (p, body) => fetch(auth(p), body ? {
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
  ctx.lineWidth = 2; ctx.font = '600 12px ui-sans-serif,system-ui,sans-serif';
  for (const d of dets){
    const c = COLOUR[d.c] || '#fff';
    const x = ox + d.b[0]*w, y = oy + d.b[1]*h;
    const bw = (d.b[2]-d.b[0])*w, bh = (d.b[3]-d.b[1])*h;
    ctx.strokeStyle = c; ctx.strokeRect(x, y, bw, bh);
    if (!showLab) continue;
    const z = d.xyz ? d.xyz[2].toFixed(1) + ' m' : '';
    const idtag = d.id !== undefined ? `#${d.id} ` : '';
    const txt = `${idtag}${d.c} ${Math.round(d.p*100)}% ${z}`;
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
      const raw = d.raw ? ` <span class="d">(${d.raw})</span>` : '';
      const id = d.id !== undefined ? `<span class="d">#${d.id}</span>` : '';
      const dw = d.dwell ? `<span class="d">${d.dwell.toFixed(0)} s</span>` : '';
      const gone = d.st && d.st !== 'TRACKED' ? ' gone' : '';
      return `<div class="trk${gone}">${id}<span class="cls ${d.c}">${d.c}</span>${raw}
        <span class="d">${Math.round(d.p*100)}%</span>
        ${dw}<span class="d">${len}</span><span class="r">${z}</span></div>`;
    }).join('');
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
    <span class="meta">${Math.round((a.conf||0)*100)}% &middot;
      ${a.dwell ? a.dwell.toFixed(0)+' s' : ''}
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
    const c = COLOUR[d.c] || '#fff';
    const x = d.b[0]*ir.width, y = d.b[1]*ir.height;
    const bw = (d.b[2]-d.b[0])*ir.width, bh = (d.b[3]-d.b[1])*ir.height;
    lbCtx.lineWidth = 3; lbCtx.strokeStyle = c; lbCtx.strokeRect(x, y, bw, bh);
    const txt = `${d.c} ${Math.round(d.p*100)}%` + (d.xyz ? ` ${d.xyz[2].toFixed(1)} m` : '');
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
    draw(); renderTracks();
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


def render(token, cfg, qualities):
    """The page, with the token and quality rungs baked in.

    json.dumps for both: a token is hex and the rungs are numbers, but
    interpolating anything into a <script> without encoding it is the kind of
    shortcut that stops being safe the moment someone makes the token
    configurable.
    """
    import json
    return (PAGE
            .replace("__TOKEN__", json.dumps(token))
            .replace("__QUALITIES__", json.dumps(
                {k: [list(v[0]), v[1], v[2]] for k, v in qualities.items()})))
