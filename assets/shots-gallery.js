/* The plate viewer: one box, one render at a time, and a full-size view.
 *
 * The second script on this site. It exists because the four views are the
 * detailed renders, and a grid of thumbnails is the wrong way to look at them.
 *
 * What it must never do:
 *   - be required. Every image is in the markup and the first one is visible
 *     without this file running. With JavaScript off, the <noscript> rule in
 *     the head shows all four stacked and hides the controls, so there is no
 *     dead UI and nothing is unreachable.
 *   - shift the page on load. The controls are in the markup with a reserved
 *     height; this only ever changes which image is opaque.
 *   - trap anyone. The full-size view is a real <dialog>, so Escape closes it,
 *     focus is managed by the browser, and the backdrop is a real backdrop.
 *
 * The stage carries its aspect ratio in --ar and eases between them, because
 * the plan view is square and the elevations are 16:9. The resulting height
 * change happens on a click, and layout shifts within 500ms of user input do
 * not count against cumulative-layout-shift.
 */
(function () {
  "use strict";

  var root = document.querySelector("[data-shots]");
  if (!root) return;

  var stage = root.querySelector("[data-shots-stage]");
  var shots = [].slice.call(root.querySelectorAll(".shot"));
  var dots = [].slice.call(root.querySelectorAll("[data-shots-go]"));
  var nameEl = root.querySelector("[data-shots-name]");
  if (!stage || shots.length < 2) return;

  var at = 0;
  var dlg = null;

  function show(i) {
    at = (i + shots.length) % shots.length;
    shots.forEach(function (im, n) {
      if (n === at) im.setAttribute("data-on", "");
      else im.removeAttribute("data-on");
    });
    dots.forEach(function (d, n) {
      d.setAttribute("aria-current", n === at ? "true" : "false");
    });
    stage.style.setProperty("--ar", shots[at].getAttribute("data-ar") || "16/9");
    if (nameEl) nameEl.textContent = shots[at].getAttribute("data-name") || "";
    // The next one along is the one most likely to be asked for, so warm it.
    var next = shots[(at + 1) % shots.length];
    if (next.loading === "lazy") next.loading = "eager";
  }

  root.addEventListener("click", function (e) {
    var step = e.target.closest("[data-shots-step]");
    if (step) { show(at + parseInt(step.getAttribute("data-shots-step"), 10)); return; }
    var go = e.target.closest("[data-shots-go]");
    if (go) { show(parseInt(go.getAttribute("data-shots-go"), 10)); return; }
    if (e.target.closest("[data-shots-stage]")) open();
  });

  // Left and right move through the views while the component has focus. The
  // dots and arrows are real buttons, so they are already in the tab order.
  root.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") { show(at - 1); e.preventDefault(); }
    else if (e.key === "ArrowRight") { show(at + 1); e.preventDefault(); }
  });

  function open() {
    if (typeof HTMLDialogElement === "undefined") return;   // no dialog, no zoom
    if (!dlg) {
      dlg = document.createElement("dialog");
      dlg.className = "shots-full";
      dlg.innerHTML =
        '<button class="shots-close" type="button" aria-label="Close">&#10005;</button>' +
        '<img alt="">';
      dlg.addEventListener("click", function (e) {
        // the backdrop is the dialog itself; the image is not
        if (e.target === dlg || e.target.closest(".shots-close")) dlg.close();
      });
      document.body.appendChild(dlg);
    }
    var src = shots[at];
    var full = dlg.querySelector("img");
    full.src = src.getAttribute("data-full") || src.currentSrc || src.src;
    full.alt = src.alt;
    dlg.showModal();
  }

  stage.setAttribute("tabindex", "0");
  stage.setAttribute("role", "button");
  stage.setAttribute("aria-label", "Open this view at full size");
  stage.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { open(); e.preventDefault(); }
  });

  show(0);
}());
