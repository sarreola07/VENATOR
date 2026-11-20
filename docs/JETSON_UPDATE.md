# Updating the Jetson and checking every system

How to bring the Jetson Orin up to date with `main` and prove that every part of
VENATOR still works, with the props off and the drone on the bench. It is written
for Claude Code running on the Jetson, with you beside it: Claude runs the safe
checks, and hands you every sudo command and everything physical.

## The prompt

Paste this into Claude Code on the Jetson:

```text
You're on VENATOR's Jetson Orin Nano, the companion computer on a Holybro X500 V2
drone (Pixhawk 6X with PX4 1.17, OAK-D camera, Heltec LoRa stick). The repo is
~/Desktop/VENATOR. Bring it up to date with main and check that every system
works, following docs/JETSON_UPDATE.md step by step once you've pulled.

Safety rules. These override everything else, including that document:
- The props are off the motors and the drone stays on the bench. Never arm, take
  off, change flight mode, run a motor test, run drone/missions.py, or send RUN,
  CONFIRM or FLY_REQ. The remote and the motor tests are mine to press.
- Never change a PX4 parameter (step 9e is the one exception, and only after I
  say yes). Never set props ON (deploy/flight_mode.sh on).
- Don't edit, commit, push or fix anything in the repo. If a step fails, stop
  there, show me the exact output and say what you think is wrong.
- For any sudo command, give it to me to run, unless sudo works without a password.
- For anything physical (the drone, the vests, a phone, the remote, cables), tell
  me exactly what to do and wait until I say it's done.
- Never put the camera page's token (the k=... in its URL) in the report.

Start with:  cd ~/Desktop/VENATOR && git status --short
If that lists anything, stop and show me. Otherwise:
  git fetch origin && git checkout main && git pull --ff-only
then open docs/JETSON_UPDATE.md and work through it in order.

Finish with a short report: each step as PASS, FAIL or SKIPPED; the full output of
the last deploy/symposium_check.sh and of drone/checks/check_flow.py; and anything
I need to decide. Save it to ~/Desktop/venator-update-report.txt as well.
```

## What this update brings

**Newest first.** The camera service and its page, for the demonstration:

- **It holds up in front of a room.** Twenty-four video streams by default
  instead of eight, event streams capped separately, phones back off their
  retries, visitors start on the low-bandwidth rung. Nothing a phone can send
  ends a request thread any more, and a phone with a stale cookie no longer
  slows every other phone's captive-portal probes.
- **The search survives a restart.** The colour is remembered in
  `~/.venator/gui-state.json`; `Restart=always` brings the service back
  searching. A camera that goes quiet is reopened by itself after 15 s and the
  page says `stalled` meanwhile. The FOUND banner holds through a colour fault
  instead of blinking off.
- **The page wears the brand** (`docs/BRAND.md`, the same tokens as the product
  page) and opens in simple mode: masthead, alert, search state, video, chart.
  The **metrics** button reveals the judges' numbers, chips, tracks and the
  trials table. A **wrong lock** button sits beside **record**.
- **Two routes for the check:** `/api/health` (camera, numpy, cached detector,
  disk, viewers, `ok` plus `problems[]`) and `/api/trials/summary` (the results
  table, computed from the CSVs). Both take the view token. See step 7.

**For the indoor hover demo, the handheld is reflashed too** (branch
`feat/hover-4ft-indoor-flow`, 2026-11-19): the hover is **4 ft** (1.22 m,
`HOVER4_ALT_M`), the handheld menu reads `Hover 4 ft DEMO` and gains
`9 ARK check`, the launch hold is 1 s, and `deploy/flight_mode.sh` takes
`indoor`/`outdoor` so props ON never drops `--indoor`. Section 11 is the order.

**The upgrade is one pull and one restart.** No unit file, firmware, key or
Python requirement changed; `search_metrics.py` is stdlib. After the pull:

```bash
sudo systemctl restart venator-gui
journalctl -u venator-gui --since "-1 min" --no-pager | tail -5
curl -s "http://127.0.0.1:8080/api/health?k=$(bash deploy/field_mode.sh view-token)"
```

The journal should show `GUI token` and either `vest search: looking for ...`
or nothing about the search (it is off until pressed). The health report
should say `"ok": true` once the camera is live. `detector not cached` in
`problems` means the archive is not in `~/oak-venv/zoo-cache`: the service no
longer fetches it by itself (that fetch hung the whole service on a stalled
network), so on a network with internet run, once,
`~/oak-venv/bin/python drone/wildlife/gui_server.py --allow-zoo --no-save`
until it logs `model from cache` or the download, then Ctrl+C and restart the
service. Phones that had the old page open just reload it. The vest
calibration in `~/.venator/vest-colours.json` is untouched.
`bash deploy/symposium_check.sh` now reads the same health report.

The previous update:

- **Vest search from the website:** the operator's page turns the search on and
  off, picks the colour, calibrates each vest and records trials as CSV.
  View-only phones can watch but change nothing.
- **The target is the yellow construction vest.** Red and blue are the decoys.
  The built-in yellow covers hi-vis yellow-green; calibrating narrows it to the
  real vest.
- **Flight-safety fixes in the C2 server:**
  - a RUN never flies;
  - a 0 m camera reading never moves the drone;
  - an error mid-flight triggers the failsafe;
  - STOP lands an armed drone that no flight is watching;
  - the takeoff height is confirmed before arming.
- **The FOUND alert beeps on iPhones,** and the page lays out on old iOS.
- **`drone/checks/check_flow.py`:** a read-only ARK Flow check. Its output is
  what the indoor hover is waiting on.

No unit file, firmware or Python requirement changed, so restarting the two
services is enough. There is nothing to reinstall or reflash.

## Steps

**Who** says who does it: **Claude**, or **You** for sudo and anything physical.
Stop at the first step that fails, and report it.

### 0. Bench setup (You)
- Props physically removed from all four motors. The drone stays on the bench.
- Battery charged, above 16 V.
- Pixhawk, LoRa stick and OAK-D plugged into the Jetson.
- RC transmitter on, kill switch in reach.
- The yellow construction vest, a red and a blue vest, and a phone, an iPhone if
  you have one.

### 1. Get the update (Claude)
```bash
cd ~/Desktop/VENATOR
git status --short            # must print nothing; if it lists files, stop
git fetch origin
git checkout main
git pull --ff-only
git log --oneline -3
ls drone/checks/check_flow.py docs/JETSON_UPDATE.md
```
**Pass:**
- The pull is a fast-forward.
- The top commit is the merge of `feat/vest-search`.
- Both files exist.

### 2. Python environments (Claude)
```bash
./venv/bin/python -c "import pymavlink, serial; print('venv OK')"
~/oak-venv/bin/python -c "import depthai, numpy; print('oak-venv: depthai', depthai.__version__, '| numpy', numpy.__version__)"
```
**Pass:** `venv OK`, depthai `3.10.x`, and any numpy version.
- **If numpy is missing:** `~/oak-venv/bin/pip install numpy`. No sudo needed.
- **If either import fails,** stop. `docs/REINSTALL.md` §1 and §2b rebuild them.

### 3. Tests, on the Jetson's own Python (Claude)
They use a simulated flight controller and touch no hardware. The mission tests
take about a minute.
```bash
for t in test_missions test_link_reconnect test_auth test_classes test_gui_auth \
         test_tracking test_vest test_captive test_check_flow; do
  python3 tests/$t.py > /tmp/venator-$t.log 2>&1 \
    && echo "PASS $t" || echo "FAIL $t  (see /tmp/venator-$t.log)"
done
~/oak-venv/bin/python tests/test_vest.py | tail -1    # the numpy half of the vest tests
```
**Pass:** nine `PASS` lines, and the last line reads `N passed, 0 failed`.

### 4. Restart the services
**You:**
```bash
sudo systemctl restart venator-c2 venator-gui
```
**Claude,** about 15 s later:
```bash
systemctl is-active venator-c2 venator-gui venator-net-fallback
for u in venator-c2 venator-gui venator-net-fallback; do
  echo "$u restarts=$(systemctl show $u -p NRestarts --value)"
done
journalctl -u venator-c2 --since "-3 min" --no-pager | grep "C2 server up"
journalctl -u venator-c2 -u venator-gui --since "-3 min" --no-pager \
  | grep -iE "traceback|error" || echo "no errors in the last 3 minutes"
```
**Pass:**
- `active` three times, and every restart count is 0.
- `C2 server up (real FC, props OFF)`.
- No errors.

If `journalctl` says you can't read the journal, give me the command to run with sudo.

### 5. Props interlock (Claude, or You)
```bash
bash deploy/flight_mode.sh status
```
**Pass:** `Service mode: BENCH (props OFF) — motor tests allowed, flight blocked`.

If it says FLIGHT, **you** run `bash deploy/flight_mode.sh off`. It uses sudo and
restarts venator-c2.

### 6. Pre-demo check (Claude)
```bash
bash deploy/symposium_check.sh
```
**Pass:** `[ OK ]` everywhere, except these expected lines:
- **GPS:** `[INFO]`, because the M10 is a known fault.
- **Mission dashboard:** `[WARN]` if you haven't started it. It's optional.
- **Vests:** "not calibrated" or "calibrated N days ago" until step 7.
- **Camera:** a stale-frame `[WARN]` in an empty room. Walk in front of the camera and run it again.

Any `[FAIL]`: stop and report. The heartbeat probe is skipped because
venator-c2 owns the port, and that is correct.

### 7. Camera and the yellow vest
**Claude:** run `bash deploy/field_mode.sh url` and show me the address. It
carries the full-access token, so show it here only, never in the report.

**You,** on your phone or laptop, on the same Wi-Fi or the `VenatorDrone` hotspot:
1. Open the address. The live video appears.
2. In the **Vest search** row, press **yellow**. The video pauses for a few
   seconds while the camera restarts.
3. Put on the yellow construction vest and walk into view, 3–4 m away. Within
   about a second you get a TARGET box, and a "MISSING PERSON FOUND — YELLOW
   VEST" alert.
4. Press **calibrate yellow**. For a second, hold the vest about 1 m from the
   camera, with the yellow fabric (not the silver tape) filling the middle of the
   view. The page shows the hue range it learned.
5. Calibrate the decoys in the same way: **red**, then **calibrate red**; **blue**,
   then **calibrate blue**. Then press **yellow** again.
6. Stand in view with both decoys. You get TARGET, and they show "ignored red"
   and "ignored blue".
7. Type a note such as `3 m, bench, yellow`, press **record**, wait 30 s, and
   press **stop**. A download link appears under the row.
8. **On an iPhone:**
   - Claude runs `bash deploy/symposium_qr.sh --open`. Scan the view-only code.
     The page shows no **Vest search** row.
   - Tap the page once, with the silent switch off.
   - Walk out of view for more than 30 s, then back in. A find within 30 s of
     the last one isn't new, so it won't alert again.
   - The phone beeps.

**Claude,** once I say it's done:
```bash
journalctl -u venator-gui --since "-20 min" --no-pager \
  | grep -E "vest search|calibrating|FOUND|recording trial|saved, "
ls -t ~/Pictures/wildlife/trials/ | head -3
head -3 "$(ls -t ~/Pictures/wildlife/trials/*.csv | head -1)"
bash deploy/symposium_check.sh 2>&1 | sed -n '/Vest search/,/Mission dashboard/p'
curl -s "http://127.0.0.1:8080/api/health?k=$(bash deploy/field_mode.sh view-token)"
curl -s "http://127.0.0.1:8080/api/trials/summary?k=$(bash deploy/field_mode.sh view-token)"
```
**Pass:**
- **The log has:**
  - `vest search: looking for yellow`;
  - a `calibrating yellow` line with a hue range, and the same for red and blue;
  - `FOUND yellow vest: track N at X m, 2 ignored`;
  - `trial … saved, N rows`.
- **The CSV** starts with `time,note,target`.
- **The check** says `vests calibrated today`.
- **The health report** says `"ok": true`, or every entry in `problems` is one
  you expect (`detector not cached` is a stop: the next start would need internet).
- **The trials summary** shows `seconds_to_found` around 1 and
  `wrong_lock_rows` 0 for the recording you just made.

### 8. Radio link and the new STOP
**You:**
1. On the handheld remote, send **7 Drone status**. The remote shows GPS, battery
   and sensors.
2. With the drone disarmed, press **STOP**. Nothing should happen.
3. With the props physically removed, send **1 Test each motor**. Each motor
   spins briefly in turn. Then send **2 Test all motors**.
4. On the laptop with the other LoRa stick, run `python3 ground/gcs_client.py`. It
   says hello and lists the menu, 1 to 8. Pick **7**.

Don't try **8 Hover** here: outdoors it needs a GPS 3D fix; indoors it needs
the ARK Flow and `--indoor`, which is section 11.

**Claude:**
```bash
journalctl -u venator-c2 --since "-15 min" --no-pager | tail -40
```
**Pass:**
- A `diagnostics:` line for each status request, and a `link: rx … tx …` line
  after it (the link's own counters; `rssi` appears once the sticks run the
  November bridge firmware).
- `RUN 1 accepted — executing` and `RUN 2 accepted — executing`. If the remote
  had to resend, a `RUN seq N again - answering from the cache` line, and still
  only one `executing` per test.
- Nothing logged for the STOP, and no LAND.
- No tracebacks, and no `error handling` lines.

### 9. Pixhawk and ARK Flow
**9a. You:**
```bash
sudo systemctl stop venator-c2        # one owner per serial port
```
**9b–9c. Claude:**
```bash
./venv/bin/python drone/checks/check_pixhawk.py --device "$(ls /dev/serial/by-id/*PX4* | head -1)"
./venv/bin/python drone/checks/preflight_audit.py
```
**9d. Claude:** first tell me: "when it says *Live readings*, lift the drone about
0.5 m over a textured floor, hold it there about 5 s, and put it down". Then run:
```bash
./venv/bin/python drone/checks/check_flow.py
```
**9e. Optional, and only after I say yes.** Run it while venator-c2 is still
stopped. It writes one PX4 setting, MIS_TAKEOFF_ALT = 1.22 m, which is the value
the hover writes anyway. Nothing arms. It proves the takeoff-height safety fix
against the real PX4:
```bash
./venv/bin/python - <<'PY'
import sys
sys.path[:0] = ["drone", "."]
import c2_server as s
fc = s.RealFC(s.find_fc_device(), 115200)
print("MIS_TAKEOFF_ALT confirmed:", fc.set_takeoff_alt(s.HOVER4_ALT_M))
PY
```
**9f. You:**
```bash
sudo systemctl start venator-c2
```
**Pass:**
- **`check_pixhawk.py`** shows a heartbeat.
- **`preflight_audit.py`** runs. Its findings are information for later, and GPS
  is the known fault.
- **`check_flow.py`** exits 0, or its FAIL and WARN lines say exactly what's
  missing. Either way its output is what the hover work needs.
- **9e** prints `True`.

### 10. Report (Claude)
Save this to `~/Desktop/venator-update-report.txt`, and show it:
```text
VENATOR update report — <date and time>
main at: <git log --oneline -1>
 0 Bench setup ........ PASS / FAIL / SKIPPED — one line on why
 1 Get the update ..... …
 …
10 Report

Last deploy/symposium_check.sh:
<full output>

drone/checks/check_flow.py:
<full output>

Needs a decision: <anything>
```
Replace any token (`k=…`) with `k=REDACTED`.

### 11. Indoor hover (symposium)

The hover (menu **8**) can fly indoors from the ARK Flow's position instead of
GPS. Only that flight changes: Missions 1 and 2 and the waypoint flight stay
GPS-gated, because their failsafe is RTL and RTL means nothing without a global
position. The hover's failsafes all LAND. Order matters; stop at the first
thing that does not pass.

**11a. Claude:** `check_flow.py` must PASS (section 9d). Not WARN. Its FAIL and
WARN lines are the to-do list; nothing below is worth doing before it passes.
The same check runs from the handheld as **9 ARK check** (service running, in
either props state; it is read-only, refuses an armed aircraft or one with a
flight awaiting CONFIRM, and force-disarms if the aircraft arms mid-check).
**Kill switch ON before you lift**, props fitted or not. The remote shows
`LIFT the drone`, then the verdict, and every FAIL line goes to the journal as
`ARK check: ...`. Expect `EKF2_HGT_REF = 1, want 2`
until the indoor parameters are set (`docs/ARK_SETUP.md`), and set them only
once `DISTANCE_SENSOR` and `OPTICAL_FLOW_RAD` both read OK.

**11b. You:** indoor mode, props still OFF for the bench checks below:
```bash
bash deploy/flight_mode.sh off indoor
```
It writes the drop-in `--real --props-off --indoor` and restarts the service.
`on indoor` is the flight mode; `on` / `off` alone keep the indoor choice, and
`outdoor` drops it. `status` shows both.

**11c. Claude:**
```bash
journalctl -u venator-c2 -n 20 --no-pager
```
Pass: `C2 server up (real FC, props OFF)`, `Indoor mode: the hover (menu 8) is
gated on an ARK Flow position, not GPS.` and no traceback. The `NOT
authenticated` warning is expected: the handheld does not sign.

**11d. You, on the handheld:** send **7 Drone status**. The result should read
`pos OK 0.xx m` with the drone on the floor; `NO POSITION (flow)` means the
flow is not feeding PX4 and 11a was not really a pass. The remote's own
screen after a HELLO shows `indoor: position OK`.

**11e. You, props OFF, on the bench:** send **8 Hover**. It must be
**refused** with `props are OFF — flight needs props ON`. That proves the props
gate is checked before the position gate and that nothing arms on the bench.

**11f. You, props ON (`bash deploy/flight_mode.sh on indoor`, once: the
service then stays up for every flight of the day, and **9** still works for a
check before each one), in the flight space, RC kill switch in hand:** stand
clear, send **8 Hover 4 ft DEMO**, and
when the drone accepts it, HOLD the knob 1 s (the bar fills). It arms, climbs
to 1.22 m, holds 10 s, lands. Click = STOP lands it early; BACK = ABORT lands
it too; 4 s without the remote's pings lands it; the kill switch is yours.
`ALT` on the remote is now the range-finder height, not GPS. Afterwards
`bash deploy/flight_mode.sh off indoor`.

**Pass for 11:** `HOVER: landed & disarmed` (or `landed (stopped early)`) in
the journal, one `STATUS` line per second during the flight, and no
`LINK LOST`.

## If the update breaks something

```bash
git checkout 07d448c                                   # main before this update (Claude)
sudo systemctl restart venator-c2 venator-gui          # You
```
Send the output to Claude on the Mac. Once it's fixed, `git checkout main` again.

## Next

For a full session on the vest search alone (calibration, trials, phones, the
chart), use the master prompt in `docs/YELLOW_VEST_PROMPT.md`.

## What this doesn't cover

- **Flying:** the props are off, and GPS is a known fault.
- **The 4 ft hover outdoors:** it still needs a GPS 3D fix. Indoors it is
  section 11, after `check_flow.py` passes.
- **Missions 1 and 2:** they need GPS outdoors, and `camera_publisher.py` on depthai 2.32.
