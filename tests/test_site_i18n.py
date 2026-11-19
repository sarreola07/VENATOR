#!/usr/bin/env python3
"""The product site's language switch: every keyed string has its Spanish.

assets/lang.js swaps text and attributes in place from the keys in the markup
(data-i18n, data-i18n-attr) and the dictionary in assets/i18n/es.js. A key on a
page with no entry leaves that string in English, silently; an entry with no
key on any page is dead weight that drifts. This pins both directions, and
that the switch itself is on both pages with scripting-off safety intact.

Stdlib only: the dictionary is read as text, not executed.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ("index.html", "how-it-works.html")
PASS = FAIL = 0


def check(label, got, want=True):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"    {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"   got {got!r}"))


def page_keys(html):
    keys = set(re.findall(r'data-i18n="([^"]+)"', html))
    for spec in re.findall(r'data-i18n-attr="([^"]+)"', html):
        for pair in spec.split(";"):
            name, _, key = pair.partition(":")
            check(f"attribute spec is well formed: {pair!r}", bool(name) and bool(key))
            keys.add(key)
    return keys


dictionary = (ROOT / "assets" / "i18n" / "es.js").read_text(encoding="utf-8")
entries = dict(re.findall(r'^\s*"([^"]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$', dictionary, re.M))

print("\nThe dictionary")
check("it declares window.VENATOR_ES", "window.VENATOR_ES = {" in dictionary)
check("every entry has its English above it, for review",
      len(re.findall(r"^\s*// EN: ", dictionary, re.M)) == len(entries))
check("no entry is empty", all(v.strip() for v in entries.values()))
check("no entry carries markup", all("<" not in v and ">" not in v for v in entries.values()))
check("no entry is still English (identical to its EN line)",
      all(f"// EN: {v}\n" not in dictionary for k, v in entries.items()
          if k not in ("hw.lab", "nav.github")))     # "Hardware" is the same word

used = set()
for page in PAGES:
    html = (ROOT / page).read_text(encoding="utf-8")
    print(f"\n{page}")
    keys = page_keys(html)
    used |= keys
    missing = sorted(k for k in keys if k not in entries)
    check(f"every keyed string has its Spanish ({len(keys)} keys)", missing, [])
    check("the switch is in the nav, hidden until the script runs",
          '<button class="lang" type="button" hidden' in html)
    check("the two scripts are deferred at the end of the body",
          '<script src="assets/i18n/es.js" defer></script>\n<script src="assets/lang.js" defer></script>' in html)
    check("English is the default", '<html lang="en">' in html)
    check("the title and description are keyed",
          'data-i18n="' in html.split("</title>")[0] and 'data-i18n-attr="content:' in html)
    check("every data-i18n element has no child elements",
          not re.search(r'<[a-z0-9]+[^>]*data-i18n="[^"]+"[^>]*>[^<]*<(?!/)', html))
    first_style = re.search(r"<style>.*?</style>", html, re.S).group(0)
    check("the switch's style is in the shared stylesheet", ".mast nav .lang{" in first_style)

print("\nBoth directions")
gallery = (ROOT / "assets" / "shots-gallery.js").read_text(encoding="utf-8")
used |= set(re.findall(r't\("([^"]+)"', gallery))     # the gallery's own two strings
check("every dictionary entry is used on a page or by the gallery",
      sorted(k for k in entries if k not in used), [])
check("the gallery script's two strings have keys", {"shots.close", "shots.open"} <= set(entries))
check("and the gallery reads them through the switch", 't("shots.close"' in gallery and 't("shots.open"' in gallery)
styles = [re.search(r"<style>.*?</style>", (ROOT / p).read_text(encoding="utf-8"), re.S).group(0) for p in PAGES]
check("both pages still carry the same stylesheet", styles[0] == styles[1])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
