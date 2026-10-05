/* Scroll-scrubbed hero.
 *
 * The only JavaScript on this site. It exists because scrubbing an image
 * sequence against scroll position cannot be done in CSS, and a library for it
 * would be ~70 KB to perform one division.
 *
 * What it must never do:
 *   - block first paint. Frame 0 is an ordinary <img> in the markup, so it is
 *     the LCP element and paints without this file running at all.
 *   - fetch 119 images during load. They are requested after window.load, so
 *     they land outside the window Lighthouse measures.
 *   - move anything for a reader who asked for no motion.
 *   - be required. With JS off, or this file 404ing, the <img> still shows the
 *     aircraft and the page reads normally.
 *
 * The labels on the 360 are real HTML text, not pixels burned into the render:
 * a screen reader can read them, they stay crisp at any size, and they restyle
 * for dark mode on their own. Blender exported where each part sits in every
 * frame; this positions the text over it.
 */
(function () {
  "use strict";

  var stage = document.querySelector("[data-cine]");
  if (!stage) return;

  var img = stage.querySelector("img");
  var total = parseInt(stage.getAttribute("data-cine"), 10) || 0;
  var path = stage.getAttribute("data-cine-path") || "";
  if (!img || total < 2) return;

  var last = total - 1;
  function name(i) {
    return "f" + ("00" + i).slice(-3) + ".webp";
  }

  /* Frame 0 sits in the markup with a srcset listing both encodes, so the
     browser picks one using the viewport AND the device pixel ratio -- better
     information than any breakpoint hardcoded here, and it means a phone never
     fetches the desktop set. Whichever it picked is the directory the other
     119 frames come from. */
  var base = path;
  function dropSources() {
    var pic = img.parentNode;
    if (!pic || pic.tagName !== "PICTURE") return;
    var srcs = pic.getElementsByTagName("source");
    while (srcs.length) pic.removeChild(srcs[0]);
  }
  function resolveBase() {
    var m = (img.currentSrc || img.src || "").match(/^(.*\/)f\d{3}\.webp/);
    if (m) base = m[1];
    // The <picture> has now done its job and it has to go: while a matching
    // <source> is still there the browser keeps re-selecting from it and any
    // src assigned here is ignored, which pins the hero on frame 0 forever
    // while the labels carry on moving. Point src at the frame already decoded
    // so nothing is refetched, then strip the sources.
    img.src = base + name(0);
    dropSources();
    img.removeAttribute("srcset");
    img.removeAttribute("sizes");
  }
  function src(i) {
    return base + name(i);
  }

  // The sequence ends on the static hero hold, so the last frame is the right
  // thing to show someone who does not want it to move.
  if (window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    // Swap the frame inside the srcset rather than setting src, so the
    // browser still gets to choose the size it would have chosen.
    var pic = img.parentNode;
    if (pic && pic.tagName === "PICTURE") {
      var srcs = pic.getElementsByTagName("source");
      for (var k = 0; k < srcs.length; k++) {
        srcs[k].srcset = srcs[k].srcset.replace(/f000\.webp/g, name(last));
      }
    }
    img.src = img.src.replace(/f000\.webp/, name(last));
    stage.setAttribute("data-cine-static", "");
    return;
  }

  var ready = new Array(total);
  ready[0] = true;
  var shown = 0;
  var queued = false;
  var labels = null;      // { labels: [{id,text}], track: [[ [u,v,vis], ... ], ...] }
  var nodes = [];
  var order = [];
  var frame = stage.querySelector(".cine-frame");
  var sizes = null;       // cached label boxes, in px; cleared on resize

  /* Blender says where each part sits, but on an airframe this compact two
     labels land on top of each other for about half the turn -- including the
     frame the sequence stops on. So each is placed in a fixed order and pushed
     DOWN far enough to clear the ones already placed.
     Fixed order, and always downward, because both make the final position a
     continuous function of the input: no label swaps places with another
     mid-scrub. The push is tapered over TAPER px of horizontal approach so it
     ramps in over several frames rather than snapping on the moment two boxes
     touch. */
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
    if (!frame) return;
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

  function paint() {
    queued = false;
    var span = stage.offsetHeight - window.innerHeight;
    var p = span > 0 ? -stage.getBoundingClientRect().top / span : 0;
    p = p < 0 ? 0 : (p > 1 ? 1 : p);

    var want = Math.round(p * last);
    // While the sequence is still arriving, fall back to the nearest frame
    // already cached rather than flashing a half-loaded image.
    var frame = want;
    while (frame > 0 && !ready[frame]) frame--;
    if (frame !== shown) {
      img.src = src(frame);
      shown = frame;
    }

    if (labels) place(labels.track[want]);
  }

  function onScroll() {
    if (!queued) {
      queued = true;
      window.requestAnimationFrame(paint);
    }
  }

  window.addEventListener("load", function () {
    resolveBase();
    for (var i = 1; i < total; i++) {
      (function (n) {
        var im = new Image();
        im.onload = function () { ready[n] = true; };
        im.src = src(n);
      }(i));
    }

    fetch(path + "labels.json").then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (data) {
      if (!data || !data.track || !frame) return;
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
      paint();
    }).catch(function () { /* labels are an enhancement, not a requirement */ });

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", function () {
      sizes = null;
      onScroll();
    }, { passive: true });
    paint();
  });
}());
