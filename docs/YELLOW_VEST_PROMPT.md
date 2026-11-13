# Master prompt: the camera locks onto the yellow vest, and ignores everyone else

One detailed prompt for Claude Code on the Jetson. It:
- pulls the latest code;
- checks the Jetson's setup and repairs anything missing;
- sets up the vest search on the existing camera page;
- proves it finds the person in the yellow construction vest, keeps the lock on
  them as they move, and ignores everyone else.

You stay beside it: Claude runs the safe steps, and hands you every sudo command
and everything physical.

**To use it:** open a terminal on the Jetson, run `cd ~/Desktop/VENATOR && claude`,
and paste the prompt below into Claude Code. It pulls the code itself, so you
can paste it before or after a `git pull`. To copy it from the Jetson itself,
run `git pull`, then open this file with `xdg-open docs/YELLOW_VEST_PROMPT.md`.

It needs Claude Code, the terminal agent, which can run commands on the Jetson.
A plain Claude chat window can't.

**What "follow" means today:** the camera follows the yellow vest. It marks that
person TARGET, keeps the box on them as they move, and calls everyone else
ignored. The drone doesn't move or turn toward them yet. That flight code isn't
built, and it waits on the ARK Flow check in phase 5.

Ignored is for targeting, never for safety: everyone the camera sees still
counts when it works out how close the nearest person is.

## The prompt

```text
You are Claude Code, running on VENATOR's Jetson Orin Nano. VENATOR is a student
search-and-rescue drone: a Holybro X500 V2 with a Pixhawk 6X (PX4 1.17) on USB,
an OAK-D camera, and a Heltec LoRa stick for the command link. This Jetson runs
Ubuntu 24.04 (JetPack, L4T R39) as user jetson, and the repo is
~/Desktop/VENATOR (github.com/sarreola07/VENATOR).

Your job: pull the latest code, install and configure it on this Jetson, and
prove that the camera finds the person in the yellow construction vest, keeps
the lock on them as they move, and ignores everyone else, live on the existing
camera website. The code is already written, tested and merged into main, so
don't write or change code: install, configure, verify and report. I'm beside
you for every sudo command and everything physical.

How it's put together (check, don't assume; the docs are in the repo):
- Three boot services:
  - venator-gui: the camera website on port 8080. It runs
    drone/wildlife/gui_server.py in ~/oak-venv (depthai 3.10 and numpy). The
    vest search lives here, switched from the operator's page.
  - venator-c2: the LoRa command link. It runs drone/c2_server.py in ./venv
    (pymavlink, pyserial) and owns the Pixhawk's serial port. Props OFF comes
    from a drop-in written by deploy/flight_mode.sh off.
  - venator-net-fallback: joins a known Wi-Fi, or hosts the VenatorDrone hotspot.
- The camera page has a full-access address for the operator, and a view-only
  one for phones (the QR code). While a vest search is on, phones joining the
  hotspot only get view-only.
- docs/JETSON_UPDATE.md is the update and system-check runbook (steps 0 to 10).
  docs/YELLOW_VEST_PROMPT.md holds this prompt and the optional "search at boot"
  drop-in. docs/REINSTALL.md rebuilds anything missing. The "Vest search"
  section of drone/wildlife/README.md explains the page's controls and chart.

Safety rules. These override everything else, including the docs:
- The props are off the motors and the drone stays on the bench. Never arm, take
  off, change flight mode, run a motor test, run drone/missions.py, or send RUN,
  CONFIRM or FLY_REQ. Nothing in this session commands the aircraft.
- Never change a PX4 parameter, and never set props ON (deploy/flight_mode.sh on).
- Don't edit, commit or push anything in the repo, and don't write flight code.
  If a step fails, stop there, show me the exact output and say what you think
  is wrong.
- For any sudo command, give it to me to run, unless sudo works without a password.
- For anything physical (the vests, a phone, the drone, cables), tell me exactly
  what to do and wait until I say it's done.
- The camera page's address carries a token (k=...). Show it to me here, but
  never put it in a file or the report.

How to work: one phase at a time. Say what you're about to do, run it, show the
result, and mark the phase PASS, FAIL or SKIPPED before moving on.

Phase 0. Look before touching anything (read-only).
  hostname; cat /etc/nv_tegra_release; python3 --version; df -h ~
  cd ~/Desktop/VENATOR && git status --short && git branch --show-current && git log --oneline -1
  ./venv/bin/python -c "import pymavlink, serial; print('venv OK')"
  ~/oak-venv/bin/python -c "import depthai, numpy; print('oak-venv', depthai.__version__, numpy.__version__)"
  systemctl is-enabled venator-gui venator-c2 venator-net-fallback
  systemctl is-active venator-gui venator-c2 venator-net-fallback
  bash deploy/flight_mode.sh status
  ls /dev/serial/by-id/
  bash drone/wildlife/checks/system_check.sh
Tell me what's there and what's missing. If git status lists anything, stop and
show me.

Phase 1. Get the code.
  git fetch origin && git checkout main && git pull --ff-only
  git log --oneline -3
  ls docs/YELLOW_VEST_PROMPT.md docs/JETSON_UPDATE.md drone/checks/check_flow.py

Phase 2. Repair only what phase 0 found missing.
  - venv or oak-venv won't import, or depthai isn't 3.10.x: docs/REINSTALL.md
    sections 1 and 2b.
  - Only numpy is missing: ~/oak-venv/bin/pip install numpy (no sudo).
  - A service isn't installed or enabled: docs/REINSTALL.md section 4b.
    deploy/field_mode.sh install and deploy/install_service.sh use sudo, so hand
    them to me.
  - Props say FLIGHT: I run bash deploy/flight_mode.sh off.
  If nothing is missing, say so and skip this phase.

Phase 3. Update, restart and check: docs/JETSON_UPDATE.md steps 3 to 6. That's
the tests, my restart of venator-c2 and venator-gui, the props interlock, and
deploy/symposium_check.sh. Step 6 lists the warnings that are expected.

Phase 4. The yellow vest search, on the camera page.
  a. Ask whether I want the search on from power-on. If yes, prepare the drop-in
     under "Start the search at boot" in docs/YELLOW_VEST_PROMPT.md, with its
     ExecStart checked against `systemctl cat venator-gui`, for me to install.
     Then confirm the journal (journalctl -u venator-gui) says "vest search:
     looking for yellow".
  b. Run `bash deploy/field_mode.sh url` and show me the address; I open it on my
     phone or laptop. I press yellow (unless a. did it), then "calibrate yellow"
     while holding the construction vest about 1 m away, with the yellow fabric,
     not the silver tape, filling the middle of the view. Then the same for the
     red and blue decoy vests, then yellow again. Check the journal for a
     "calibrating" line with a hue range for each colour.
  c. The proof. Before each test I type a note on the page and press record, and
     afterwards I press stop:
     1. I walk in wearing the yellow vest: TARGET within about a second, and a
        "MISSING PERSON FOUND" alert.
     2. People in the red and blue vests, and one with no vest, stand beside me:
        each shows "ignored", and none of them ever gets TARGET.
     3. I walk slowly across the room: the TARGET box stays on me, and the chart,
        set to "vest match", stays above the match line while the decoys stay flat.
     4. I swap places with a decoy: TARGET stays with the yellow vest, not the spot.
     5. I leave the view for more than 30 s and come back: a new FOUND.
  d. Summarise every CSV in ~/Pictures/wildlife/trials/ as a table: the note, the
     seconds from the first row to the first "found" event, the distances, and
     any row with role "target" on a vest that isn't yellow. That's a wrong lock,
     the result that matters most, and there should be none.
  e. Phones: run `bash deploy/symposium_qr.sh --open`. On a phone, the view-only
     page shows the video, the boxes and the chart, and no Vest search row. On an
     iPhone, tap the page once with the silent switch off; the next FOUND, after
     more than 30 s out of view, beeps.
  f. On my page I press poster, then snapshot and save PNG, and save CSV. Check
     the files downloaded.
  g. Refresh the demo-day folder: bash deploy/install_shortcuts.sh --symposium
     (no sudo). ~/Desktop/Symposium/README.md should now describe the yellow vest.

Phase 5. What the drone needs before it can follow (read-only).
Do docs/JETSON_UPDATE.md step 9, the Pixhawk and ARK Flow checks, with me stopping
and starting venator-c2 and lifting the drone when check_flow.py asks. Skip 9e
unless I say yes. Its output decides when the turn-to-face work can start.

Phase 6. Report: each phase as PASS, FAIL or SKIPPED with one line on why; what
you repaired; the calibrated range for each colour; the trial table; the last
deploy/symposium_check.sh output; the drone/checks/check_flow.py output; and
anything I need to decide. Save it to ~/Desktop/venator-vest-report.txt, with
no token in it.
```

## Start the search at boot (optional)

With this, the camera is already looking for the yellow vest when the Jetson
powers on. Phones joining the hotspot get the view-only page straight away,
because they always do while a search is on. You can still switch the search
off or change colour from the page, and any restart brings yellow back.

**What it costs:** while the search is on, the camera pulls colour frames over
USB (about 35 Mbps). That counts against the 7 W budget.

**You install it, with sudo.** First, print the camera service's current start
line:

```bash
systemctl cat venator-gui | grep '^ExecStart=/'
```

Then write the drop-in. The second `ExecStart` must be exactly the line you just
printed, with ` --search yellow` added. On a standard install it's the one below.
The bare `ExecStart=` clears the original, which systemd needs before it accepts
a replacement.

```bash
sudo mkdir -p /etc/systemd/system/venator-gui.service.d
sudo tee /etc/systemd/system/venator-gui.service.d/search.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/home/jetson/oak-venv/bin/python /home/jetson/Desktop/VENATOR/drone/wildlife/gui_server.py --save-dir /home/jetson/Pictures/wildlife --search yellow
EOF
```

Reload and restart:

```bash
sudo systemctl daemon-reload && sudo systemctl restart venator-gui
```

Check it took:

```bash
journalctl -u venator-gui --since "-1 min" --no-pager | grep "vest search"
```

**Pass:** `vest search: looking for yellow, colours from …`

**To undo:**
```bash
sudo rm /etc/systemd/system/venator-gui.service.d/search.conf
sudo systemctl daemon-reload && sudo systemctl restart venator-gui
```

## How it decides

- **A person first:** the network has to detect a person, so a yellow bin or sign
  is never a candidate.
- **The chest's colour:** at least 30% of the middle of the chest has to be the
  colour, and at least 10 points ahead of any other. The threshold is that low to
  allow for the silver reflective tape and the arms.
- **A second of agreement:** a track has to read yellow in about 8 frames out of
  10 before it counts, so a colour that flickers can't get through.
- **One lock:** once locked, the search stays on that track. A second yellow vest
  is reported, not switched to. Anyone who disappears has to earn the vote again.
- **No lock beyond 8 m.**
- **A known limit:** a yellow shirt looks the same as a yellow vest, and so can
  lime or olive clothes. It matches a description; it doesn't recognise a vest.

## Not covered

- **The drone turning to follow the vest:** not built. It waits on the ARK Flow
  check in phase 5, and on your go-ahead.
- **Flying of any kind:** the props are off, and GPS is a known fault.
