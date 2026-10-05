/* The hero sequence, played once.
 *
 * This used to scrub against scroll position. The problem with that was not the
 * scrubbing, it was the arithmetic underneath it: a scroll-driven animation has
 * to reserve its length as document space, and that space sat between the
 * aircraft and the numbers band, which pushed the numbers nearly two screens
 * below the fold. Playing it on a clock costs no page height at all, so the
 * aircraft and the numbers are both on the first screen.
 *
 * What it must never do:
 *   - block first paint. Frame 0 is an ordinary <img> in the markup and paints
 *     whether or not this file runs.
 *   - start before anyone can see it. An IntersectionObserver holds it until
 *     the aircraft is actually on screen, so it is never already over.
 *   - move for a reader who asked for no motion. They get the last frame, the
 *     assembled aircraft, and nothing happens.
 *   - run forever. It plays once, stops on the hold, and releases the loop.
 *
 * The labels are real HTML positioned from data Blender exported, not pixels in
 * the render, and there is a deliberate pause while they are up: the authored
 * beat is only a second and a half, which is not long enough to read four of
 * them.
 */
(function () {
  "use strict";

  var stage = document.querySelector("[data-cine]");
  if (!stage) return;

  var img = stage.querySelector("img");
  var frame = stage.querySelector(".cine-frame");
  var total = parseInt(stage.getAttribute("data-cine"), 10) || 0;
  var path = stage.getAttribute("data-cine-path") || "";
  if (!img || !frame || total < 2) return;

  var last = total - 1;
  var FPS = 24;
  var HOLD_AT = 60;        // mid-way through the labelled beat
  var HOLD_MS = 2200;      // long enough to read four labels

  function name(i) { return "f" + ("00" + i).slice(-3) + ".webp"; }

  var base = path;
  function resolveBase() {
    var m = (img.currentSrc || img.src || "").match(/^(.*\/)f\d{3}\.webp/);
    if (m) base = m[1];
    // The <picture> has chosen its size; it has to go, because while a matching
    // <source> is in the DOM the browser keeps re-selecting from it and any src
    // set here is ignored.
    img.src = base + name(0);
    var pic = img.parentNode;
    if (pic && pic.tagName === "PICTURE") {
      var srcs = pic.getElementsByTagName("source");
      while (srcs.length) pic.removeChild(srcs[0]);
    }
    img.removeAttribute("srcset");
    img.removeAttribute("sizes");
  }

  var labels = null;
  var nodes = [];
  var order = [];
  var sizes = null;

  /* Blender says where each part sits, but on an airframe this compact two
     labels land on top of each other for part of the turn. Each is placed in a
     fixed order and pushed DOWN clear of the ones already placed -- fixed
     order and always downward, so the result is continuous and no label swaps
     places with another mid-play. */
  var ORDER = ["pixhawk", "oakd", "radio", "jetson"];
  var GAP = 4, TAPER = 28;

  function measure() {
    sizes = nodes.map(function (el) {
      var was = el.hidden;
      el.hidden = false;
      var s = { w: el.offsetWidth, h: el.offsetHeight };
      el.hidden = was;
      return s;
    });
  }

  function place(row) {
    var bw = frame.offsetWidth, bh = frame.offsetHeight;
    if (!bw || !bh) return;
    if (!sizes) measure();
    var done = [];
    for (var n = 0; n < order.length; n++) {
      var i = order[n], pt = row && row[i], el = nodes[i];
      if (!pt || !pt[2]) { el.hidden = true; continue; }
      el.hidden = false;
      var x = pt[0] * bw, y = pt[1] * bh;
      for (var pass = 0; pass < 4; pass++) {
        for (var d = 0; d < done.length; d++) {
          var o = done[d];
          var reach = sizes[i].w / 2 + sizes[o.i].w / 2 + TAPER - Math.abs(x - o.x);
          var t = reach / TAPER;
          t = t < 0 ? 0 : (t > 1 ? 1 : t);
          var want = o.y + (sizes[i].h + sizes[o.i].h) / 2 + GAP;
          if (t > 0 && y < want) y += t * (want - y);
        }
      }
      done.push({ i: i, x: x, y: y });
      el.style.left = (x / bw * 100).toFixed(2) + "%";
      el.style.top = (y / bh * 100).toFixed(2) + "%";
    }
  }

  var shown = -1;
  function draw(i) {
    if (i !== shown) { img.src = base + name(i); shown = i; }
    if (labels) place(labels.track[i]);
  }

  // Reduced motion: the assembled aircraft, and nothing moves.
  if (window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    var pic = img.parentNode;
    if (pic && pic.tagName === "PICTURE") {
      var ss = pic.getElementsByTagName("source");
      for (var k = 0; k < ss.length; k++) {
        ss[k].srcset = ss[k].srcset.replace(/f000\.webp/g, name(last));
      }
    }
    img.src = img.src.replace(/f000\.webp/, name(last));
    return;
  }

  var preHold = HOLD_AT / FPS * 1000;
  var t0 = null;
  function step(now) {
    if (t0 === null) t0 = now;
    var ms = now - t0;
    var i;
    if (ms < preHold) i = Math.floor(ms / 1000 * FPS);
    else if (ms < preHold + HOLD_MS) i = HOLD_AT;
    else i = HOLD_AT + Math.floor((ms - preHold - HOLD_MS) / 1000 * FPS);
    if (i >= last) { draw(last); return; }      // stops on the hold, loop ends
    draw(i);
    requestAnimationFrame(step);
  }

  var started = false;
  function play() {
    if (started) return;
    started = true;
    requestAnimationFrame(step);
  }

  var fetched = false;
  function fetchFrames() {
    if (fetched) return;
    fetched = true;
    for (var i = 1; i < total; i++) {
      (function (n) { var im = new Image(); im.src = base + name(n); }(i));
    }
  }

  function begin() {
    resolveBase();
    // Request the sequence and start. Playback deliberately does NOT wait for
    // every frame: the browser serves them in the order asked for, which is the
    // order they are needed, and a frame that has not arrived just leaves the
    // previous one up for a beat. Waiting was worse -- all of this used to hang
    // off window.load, so a single stalled request meant the animation never
    // ran at all.
    fetchFrames();
    play();
  }

  (function () {
    fetch(path + "labels.json").then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (data) {
      if (!data || !data.track) return;
      labels = data;
      var wrap = document.createElement("div");
      wrap.className = "cine-labels";
      data.labels.forEach(function (l) {
        var el = document.createElement("b");
        el.className = "cine-label";
        el.textContent = l.text;
        el.hidden = true;
        wrap.appendChild(el);
        nodes.push(el);
      });
      frame.appendChild(wrap);
      order = ORDER.map(function (id) {
        return data.labels.findIndex(function (l) { return l.id === id; });
      }).filter(function (i) { return i >= 0; });
      data.labels.forEach(function (l, i) {
        if (order.indexOf(i) < 0) order.push(i);
      });
    }).catch(function () { /* labels are an enhancement, not a requirement */ });

    // Hold until it is actually on screen, so it is never already finished by
    // the time someone looks at it.
    if (typeof IntersectionObserver === "function") {
      var io = new IntersectionObserver(function (es) {
        if (es.some(function (e) { return e.isIntersecting; })) {
          io.disconnect();
          begin();
        }
      }, { threshold: 0.35 });
      io.observe(frame);
    } else {
      begin();
    }

    window.addEventListener("resize", function () { sizes = null; }, { passive: true });
  }());
}());
