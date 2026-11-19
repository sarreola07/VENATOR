// The language switch. English is the markup's own text and stays the default;
// Spanish comes from assets/i18n/es.js and is swapped in place, so there is one
// URL per page and with scripting off the English page is simply unchanged.
//
// Every translatable element carries data-i18n="key" (its text) and/or
// data-i18n-attr="alt:key;aria-label:key2" (its attributes). The English is
// read off the element the first time, never typed twice, so the markup stays
// the single source of the English copy. A key missing from the dictionary
// leaves that string in English rather than blank. tests/test_site_i18n.py
// checks that none are missing.
//
// ?lang=es in the URL, or a previous choice stored on this device, selects
// Spanish on load. This script is deferred, so the swap lands at the end of
// parsing, before the first layout settles on most devices.
(function () {
  "use strict";
  var STORE = "venator-lang";
  var dict = window.VENATOR_ES || {};
  var button = document.querySelector("button.lang");
  var current = "en";
  var english = [];          // [{el, text, attrs:{name: value}}], captured once

  function capture() {
    var els = document.querySelectorAll("[data-i18n],[data-i18n-attr]");
    for (var i = 0; i < els.length; i++) {
      var el = els[i], rec = { el: el, text: null, attrs: {} };
      if (el.hasAttribute("data-i18n")) rec.text = el.textContent;
      var spec = el.getAttribute("data-i18n-attr");
      if (spec) {
        var pairs = spec.split(";");
        for (var j = 0; j < pairs.length; j++) {
          var name = pairs[j].split(":")[0];
          if (name) rec.attrs[name] = el.getAttribute(name);
        }
      }
      english.push(rec);
    }
  }

  function lookup(key, fallback) {
    if (current !== "es") return fallback;
    var v = dict[key];
    return (typeof v === "string" && v) ? v : fallback;
  }

  // For the other scripts: the current wording of a key, or their own English.
  window.VENATOR_T = function (key, fallback) { return lookup(key, fallback); };
  window.VENATOR_LANG = function () { return current; };

  function apply(lang) {
    current = lang === "es" ? "es" : "en";
    for (var i = 0; i < english.length; i++) {
      var rec = english[i], el = rec.el;
      if (rec.text !== null) {
        el.textContent = lookup(el.getAttribute("data-i18n"), rec.text);
      }
      var spec = el.getAttribute("data-i18n-attr");
      if (spec) {
        var pairs = spec.split(";");
        for (var j = 0; j < pairs.length; j++) {
          var parts = pairs[j].split(":"), name = parts[0], key = parts[1];
          if (!name || !key) continue;
          el.setAttribute(name, lookup(key, rec.attrs[name]));
        }
      }
    }
    document.documentElement.lang = current;
    if (button) {
      // The button names the language it would switch to.
      button.textContent = current === "es" ? "EN" : "ES";
      // WCAG 2.5.3: the accessible name must contain the visible text, so the
      // two letters lead and the explanation follows.
      button.setAttribute("aria-label", current === "es" ? "EN, switch to English" : "ES, cambiar a español");
      button.setAttribute("lang", current === "es" ? "en" : "es");
    }
    // The plate viewer's caption is copied from the shown image's data-name
    // by assets/shots-gallery.js; refresh it from the now-translated attribute.
    var shown = document.querySelector(".shot[data-on]");
    var caption = document.querySelector("[data-shots-name]");
    if (shown && caption) caption.textContent = shown.getAttribute("data-name") || "";
    try { window.dispatchEvent(new CustomEvent("venator:lang", { detail: current })); } catch (e) { /* old browser */ }
  }

  function remember(lang) {
    try { localStorage.setItem(STORE, lang); } catch (e) { /* private mode */ }
  }

  function wanted() {
    var m = /[?&]lang=(es|en)\b/.exec(location.search);
    if (m) return m[1];
    try { return localStorage.getItem(STORE) || "en"; } catch (e) { return "en"; }
  }

  capture();
  if (button) {
    button.removeAttribute("hidden");
    button.addEventListener("click", function () {
      var next = current === "es" ? "en" : "es";
      apply(next);
      remember(next);
    });
  }
  var first = wanted();
  if (first === "es") apply("es"); else apply("en");
}());
