#!/usr/bin/env bash
# Printable QR codes for demo day: join the hotspot, then open the camera.
#
#   bash deploy/symposium_qr.sh           # the real sheet, onto the Desktop
#   bash deploy/symposium_qr.sh --open    # ...and open it here
#   bash deploy/symposium_qr.sh --docs    # redacted copies for docs/img/
#
# WHY QR CODES AND NOT JUST THE CAPTIVE PORTAL
#
# The portal needs dnsmasq answering venator.com, an nft rule moving port 80 to
# 8080, and iOS choosing to show the sheet. Three moving parts. The URLs below
# need none of them: they name the address the server actually listens on, so
# they work whether or not the portal does. The portal is the nice version; this
# is the one that cannot fail in front of an audience.
#
# WHY --docs EXISTS, AND WHY THE DEFAULT OUTPUT IS NOT IN THE REPO
#
# The real codes encode the Wi-Fi password and the camera token, and
# github.com/sarreola07/VENATOR is PUBLIC. A QR is the worst possible shape for
# a secret in a git repo: it survives review because it looks like decoration,
# and it is invisible to `git grep` because the bytes are an image. So the real
# sheet is written to the Desktop, outside the repo, and `--docs` renders the
# same layout with placeholder values for anything that may be committed.
#
# WHY THE TOKEN IS READ AND NOT HARDCODED
#
# gui_server.py derives its token from the GUI key, and a printed sheet carrying
# a stale one is worse than no sheet -- it fails at the moment you are pointing
# at it. field_mode.sh's `url` resolves the token through the same
# VENATOR_KEY_FILE the systemd unit sets, so the paper and the server cannot
# disagree. Regenerate after anything that could rotate the key.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "${HERE}/.." && pwd)"
AP_IP="${AP_IP:-10.42.0.1}"
CAM_PORT="${CAM_PORT:-8080}"
WEB_PORT="${WEB_PORT:-5037}"
CON="${CON:-venator-hotspot}"
PY="${REPO}/venv/bin/python"

G=$'\033[92m'; R=$'\033[91m'; Y=$'\033[93m'; Z=$'\033[0m'

MODE="live"
[[ "${1:-}" == "--docs" ]] && MODE="docs"

if [[ "${MODE}" == "docs" ]]; then
    OUT_DIR="${OUT_DIR:-${REPO}/docs/img}"
else
    OUT_DIR="${OUT_DIR:-${HOME}/Desktop/Symposium}"
fi

# Refuse to write live codes into the repo, rather than trusting .gitignore to
# catch it. A pattern cannot tell a redacted PNG from one carrying the real
# password, and the whole hazard here is that neither can a human reviewer.
# OUT_DIR is overridable, so this is the only thing standing between
# `OUT_DIR=docs/img bash deploy/symposium_qr.sh` and a public credential.
if [[ "${MODE}" == "live" ]]; then
    abs_out="$(readlink -m "${OUT_DIR}")"
    if [[ "${abs_out}" == "${REPO}" || "${abs_out}" == "${REPO}/"* ]]; then
        echo "${R}refusing to write live QR codes inside the repo${Z}"
        echo "  ${abs_out} is tracked by git, and these codes encode the Wi-Fi"
        echo "  password and the camera token. github.com/sarreola07/VENATOR is public."
        echo "  for committable copies:  bash deploy/symposium_qr.sh --docs"
        exit 1
    fi
fi

[[ -x "${PY}" ]] || { echo "${R}no ${PY}${Z}"; exit 1; }
"${PY}" - <<'CHK' 2>/dev/null || { echo "${R}missing deps${Z}  fix:  ${REPO}/venv/bin/pip install qrcode pillow"; exit 1; }
import qrcode, PIL
CHK

if [[ "${MODE}" == "live" ]]; then
    tok="$(bash "${HERE}/field_mode.sh" url 2>/dev/null)"; tok="${tok##*k=}"
    if [[ -z "${tok}" || "${tok}" == *"/"* ]]; then
        echo "${R}could not read the camera token${Z} — is the GUI key present?"
        exit 1
    fi
    # From the NetworkManager profile, not from a literal: the password lives in
    # exactly one place and a second copy here would drift the first time it
    # changed.
    ssid="$(nmcli -e no -g 802-11-wireless.ssid connection show "${CON}" 2>/dev/null)"
    psk="$(nmcli -s -e no -g 802-11-wireless-security.psk connection show "${CON}" 2>/dev/null)"
    [[ -n "${ssid}" ]] || echo "${Y}warn${Z}  no '${CON}' profile — sheet will have no join code"
else
    # Deliberately not the real values. These render an identical-looking sheet
    # for documentation without publishing anything.
    tok="REPLACED-AT-GENERATION"
    ssid="VenatorDrone"
    psk="see-deploy-wifi_mode.sh"
fi

mkdir -p "${OUT_DIR}"

MODE="${MODE}" TOKEN="${tok}" SSID="${ssid}" PSK="${psk}" AP_IP="${AP_IP}" \
CAM_PORT="${CAM_PORT}" WEB_PORT="${WEB_PORT}" OUT_DIR="${OUT_DIR}" \
"${PY}" - <<'PY' || { echo "${R}generation failed${Z}"; exit 1; }
import html, io, os
import qrcode
from qrcode.image.svg import SvgPathImage

env = os.environ
ap, cam, web = env["AP_IP"], env["CAM_PORT"], env["WEB_PORT"]
ssid, psk, token = env["SSID"], env["PSK"], env["TOKEN"]
out_dir, docs = env["OUT_DIR"], env["MODE"] == "docs"

cam_url = f"http://{ap}:{cam}/?k={token}"
web_url = f"http://{ap}:{web}/"


def wifi_payload(s, p):
    # The MECARD-ish escaping the Wi-Fi QR format requires. Our SSID and
    # password happen to contain none of these, but a sheet that silently
    # encodes the wrong password the day someone adds a ';' is a bad trade
    # for four characters of code.
    esc = lambda v: "".join("\\" + c if c in '\\;,:"' else c for c in v)
    return f"WIFI:T:WPA;S:{esc(s)};P:{esc(p)};;"


def make(data):
    # ERROR_CORRECT_H (30% recovery), not the M default. Two reasons, one
    # practical and one measured. Practical: this sheet gets printed, taped up
    # and scanned at an angle under hall lighting, which is what the redundancy
    # is for. Measured: at M the dashboard URL lands on a 25x25 version-2 symbol
    # that OpenCV's QRCodeDetector cannot read at any scale, while the same
    # string at L, at H, and forced to version 4 all decode. The encode is valid
    # -- a known detector weakness on small symbols -- but a code that no
    # decoder on this machine can verify is a code nobody should print.
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H,
                      box_size=10, border=4)
    q.add_data(data)
    q.make(fit=True)
    return q


def svg_of(q):
    buf = io.BytesIO()
    q.make_image(image_factory=SvgPathImage).save(buf)
    body = buf.getvalue().decode().split("?>", 1)[-1].strip()
    # Let CSS size it rather than the generator's millimetre width/height.
    return body.replace("<svg ", '<svg class="qr" ', 1)


cards = []
if ssid:
    cards.append(("wifi", "1", "Join the Wi-Fi", wifi_payload(ssid, psk),
                  f"{html.escape(ssid)} &middot; {html.escape(psk)}"))
cards.append(("camera", "2", "Open the camera", cam_url, html.escape(cam_url)))
cards.append(("dashboard", "3", "Mission dashboard", web_url, html.escape(web_url)))

written = []
blocks = []
for slug, n, title, payload, caption in cards:
    q = make(payload)
    png = os.path.join(out_dir, f"venator-qr-{slug}.png")
    q.make_image(fill_color="black", back_color="white").save(png)
    written.append((png, q.version, payload))
    blocks.append(
        f'''  <figure>
    <h2><span>{n}</span>{html.escape(title)}</h2>
    {svg_of(q)}
    <figcaption>{caption}</figcaption>
  </figure>''')

note = ('<p class="warn">Placeholder codes for documentation. The real sheet '
        'carries a live token and the Wi-Fi password and is never committed — '
        'run <code>bash deploy/symposium_qr.sh</code> to produce it.</p>'
        if docs else '')

page = f'''<!doctype html>
<meta charset="utf-8">
<title>VENATOR — scan to watch</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 0; padding: 28px 24px;
         color: #111; background: #fff; }}
  h1 {{ font-size: 23px; margin: 0 0 2px; letter-spacing: .14em; }}
  .sub {{ color: #666; margin: 0 0 22px; }}
  .warn {{ background: #fff6d8; border: 1px solid #e8d48a; border-radius: 8px;
           padding: 10px 13px; margin: 0 0 20px; font-size: 13px; }}
  .row {{ display: flex; flex-wrap: wrap; gap: 20px; }}
  figure {{ margin: 0; flex: 1 1 220px; max-width: 290px; border: 1px solid #dcdcdc;
            border-radius: 10px; padding: 14px; text-align: center; }}
  h2 {{ font-size: 14px; margin: 0 0 10px; display: flex; align-items: center;
        gap: 8px; justify-content: center; }}
  h2 span {{ background: #111; color: #fff; border-radius: 50%; width: 21px;
             height: 21px; display: inline-grid; place-items: center;
             font-size: 12px; }}
  .qr {{ width: 100%; height: auto; max-width: 205px; }}
  figcaption {{ font: 12px ui-monospace, Menlo, monospace; color: #444;
                margin-top: 9px; word-break: break-all; }}
  footer {{ margin-top: 24px; padding-top: 14px; border-top: 1px solid #e4e4e4;
            color: #555; font-size: 13px; }}
  @media print {{ body {{ padding: 0; }} figure {{ break-inside: avoid; }} }}
</style>
<h1>VENATOR</h1>
<p class="sub">Scan 1 to join the drone's network, then 2 to watch the camera.</p>
{note}
<div class="row">
{chr(10).join(blocks)}
</div>
<footer>
  These addresses use no DNS and no firewall rule &mdash; they work even if the
  captive portal does not. If a phone shows &ldquo;no internet&rdquo;, that is
  expected: the drone is not a router. Stay on the network and scan 2.
</footer>
'''

html_path = os.path.join(out_dir, "venator-qr.html")
with open(html_path, "w") as fh:
    fh.write(page)

for png, ver, _ in written:
    print(f"  png   {png}  (version {ver})")
print(f"  html  {html_path}")

# The same codes in the terminal, for when there is no printer and no second
# screen -- a phone scans these off the Jetson's own display perfectly well.
if not docs:
    for slug, n, title, payload, _ in cards:
        if slug == "dashboard":
            continue
        print(f"\n  {n}. {title.lower()}\n")
        t = qrcode.QRCode(border=1)
        t.add_data(payload)
        t.print_ascii()
PY

echo
if [[ "${MODE}" == "docs" ]]; then
    printf "  %sredacted sheet written for documentation%s\n" "${G}" "${Z}"
    printf "  %sno live token and no password in these files%s\n\n" "${Y}" "${Z}"
    exit 0
fi

printf "  %ssheet written%s\n" "${G}" "${Z}"
printf "  camera     %s\n" "http://${AP_IP}:${CAM_PORT}/?k=${tok}"
printf "  dashboard  %s\n" "http://${AP_IP}:${WEB_PORT}/"
[[ -n "${ssid}" ]] && printf "  wifi       %s / %s\n" "${ssid}" "${psk}"
printf "\n  %sthese work only while the access point is up%s —  bash deploy/wifi_mode.sh on\n" "${Y}" "${Z}"
printf "  %sthe sheet contains the password and token — do not commit it%s\n\n" "${Y}" "${Z}"

if [[ "${1:-}" == "--open" ]]; then
    command -v firefox >/dev/null 2>&1 && exec firefox --new-window "file://${OUT_DIR}/venator-qr.html"
    exec xdg-open "${OUT_DIR}/venator-qr.html"
fi
