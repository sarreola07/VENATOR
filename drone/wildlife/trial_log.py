#!/usr/bin/env python3
"""
Recordings of vest search trials, as CSV, for the results table.

The live chart forgets after 30 seconds, and a snapshot keeps one moment. A
recognition trial needs every reading: when the wearer came into view, how the
vote built up, when FOUND fired, and whether a decoy was ever the target. So the
operator starts a recording from the camera page with a short note ("4 m,
daylight, Sam in yellow"), runs the trial, and stops it. Each one is a CSV in
<save_dir>/trials/, downloadable from the page.

One row per person per detection frame, plus a row for each FOUND. Stdlib only,
so CI tests it exactly as it runs.

A recording must never take the camera down with it. A write that fails, a full
disk say, stops the recording, says so once, and the search carries on.
"""
import csv
import re
import threading
import time
from pathlib import Path

COLUMNS = ("time", "note", "target", "state", "track", "role", "vest", "vest_match",
           "person_confidence", "votes", "tracker_status", "distance_m", "event")

#: What this module writes, and so all the page may ask to download: a timestamp,
#: then an optional note slug. Checked by shape, like the evidence names, so no
#: path can be smuggled through a file name.
NAME = re.compile(r"^\d{8}-\d{6}(-[a-z0-9-]{1,40})?\.csv$")

#: Long enough to say what the trial was, short enough for a file name.
NOTE_MAX = 60


def slug(note):
    """A file-name-safe version of a note: "4 m, Daylight!" -> "4-m-daylight"."""
    return re.sub(r"[^a-z0-9]+", "-", note.lower()).strip("-")[:36].rstrip("-")


class TrialLog:
    """Starts, writes and stops one recording at a time. Thread-safe: the page
    starts and stops it while the camera loop writes."""

    def __init__(self, directory, log=print):
        self.directory = Path(directory)
        self._log = log
        self._lock = threading.Lock()
        self._file = None
        self._writer = None
        self.name = None
        self.note = ""
        self.rows = 0

    @property
    def recording(self):
        return self._file is not None

    def start(self, note=""):
        """Begin a new recording, ending any current one. Returns its name, or
        None if the folder can't be written."""
        note = " ".join(str(note).split())[:NOTE_MAX]
        tail = slug(note)
        base = time.strftime("%Y%m%d-%H%M%S") + (f"-{tail}" if tail else "")
        with self._lock:
            self._close()
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                # Two recordings in one second, with the same note, must not
                # overwrite each other: "x" refuses an existing file, so number it.
                for n in range(1, 100):
                    name = base + (f"-{n}" if n > 1 else "") + ".csv"
                    try:
                        f = open(self.directory / name, "x", newline="")
                        break
                    except FileExistsError:
                        continue
                else:
                    raise OSError("too many recordings in one second")
            except OSError as exc:
                self._log(f"could not start a trial recording: {exc}")
                return None
            self._file, self._writer = f, csv.writer(f)
            self.name, self.note, self.rows = name, note, 0
            self._writer.writerow(COLUMNS)
        self._log(f"recording trial {name}")
        return name

    def stop(self):
        """End the current recording. Returns its name, or None if none was running."""
        with self._lock:
            name = self.name if self._file else None
            self._close()
        if name:
            self._log(f"trial {name} saved, {self.rows} rows")
        return name

    def write(self, report, dets, stamp=None):
        """Record one detection frame of the search. Does nothing when stopped."""
        if self._file is None or report is None:
            return
        stamp = time.time() if stamp is None else stamp
        when = time.strftime("%H:%M:%S", time.localtime(stamp)) + f".{int(stamp * 1000) % 1000:03d}"
        common = (when, self.note, report.get("target") or "", report.get("state", ""))
        rows = []
        for d in dets:
            if d.get("c") != "person":
                continue
            xyz = d.get("xyz")
            z = xyz[2] if xyz and xyz[2] > 0 else ""
            rows.append(common + (d.get("id", ""), d.get("role", ""), d.get("vest") or "",
                                  d.get("match", ""), d.get("p", ""), d.get("votes", ""),
                                  d.get("st", ""), z, ""))
        if report.get("found_now"):
            rows.append(common + (report.get("id", ""), "target", report.get("target") or "",
                                  "", report.get("conf", ""), "", "", report.get("z", ""),
                                  "found"))
        if not rows:
            return
        with self._lock:
            if self._writer is None:
                return
            try:
                self._writer.writerows(rows)
                self._file.flush()
                self.rows += len(rows)
            except (OSError, ValueError) as exc:   # ValueError: the file was closed
                self._log(f"trial recording stopped, could not write: {exc}")
                self._close()

    def event(self, name, target="", stamp=None):
        """One row that is not a detection: the operator marking a wrong lock."""
        if self._file is None:
            return
        stamp = time.time() if stamp is None else stamp
        when = time.strftime("%H:%M:%S", time.localtime(stamp)) + f".{int(stamp * 1000) % 1000:03d}"
        row = (when, self.note, target or "", "", "", "", "", "", "", "", "", "", name)
        with self._lock:
            if self._writer is None:
                return
            try:
                self._writer.writerow(row)
                self._file.flush()
                self.rows += 1
            except (OSError, ValueError) as exc:
                self._log(f"trial recording stopped, could not write: {exc}")
                self._close()

    def summary(self, limit=50):
        """The results table, newest first: one line per recording on disk."""
        out = []
        for item in self.list(limit):
            path = self.path(item["name"])
            if path is not None:
                out.append(summarise(path))
        return out

    def _close(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
        self._file = self._writer = None

    def status(self):
        return {"name": self.name, "rows": self.rows} if self.recording else None

    def list(self, limit=50):
        """The recordings on disk, newest first."""
        try:
            files = [p for p in self.directory.iterdir() if NAME.match(p.name)]
        except OSError:
            return []
        files.sort(key=lambda p: p.name, reverse=True)
        out = []
        for p in files[:limit]:
            try:
                out.append({"name": p.name, "bytes": p.stat().st_size})
            except OSError:
                continue
        return out

    def path(self, name):
        """The file for a name from the page, or None if it isn't one of ours."""
        if not NAME.match(name or ""):
            return None
        p = self.directory / name
        return p if p.is_file() else None


def _seconds(when):
    """A 'HH:MM:SS.mmm' stamp as seconds into the day, or None."""
    try:
        h, m, s = when.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        return None


def summarise(path):
    """What one recording proved, for the results table.

    The note, the rows, seconds from the first row to the first FOUND, the
    range of distances read, and the rows where someone was TARGET in a vest
    that is not the target colour: a wrong lock, the result that matters most.
    docs/YELLOW_VEST_PROMPT.md used to ask for this table to be worked out by
    hand from the CSVs.
    """
    path = Path(path)
    out = {"name": path.name, "note": "", "target": "", "rows": 0, "finds": 0,
           "seconds_to_found": None, "distance_min_m": None, "distance_max_m": None,
           "wrong_lock_rows": 0, "wrong_locks_marked": 0, "people": 0}
    try:
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            first = None
            people = set()
            for row in reader:
                out["rows"] += 1
                out["note"] = out["note"] or row.get("note", "")
                out["target"] = out["target"] or row.get("target", "")
                t = _seconds(row.get("time"))
                if t is not None and first is None:
                    first = t
                if row.get("track"):
                    people.add(row["track"])
                event = row.get("event", "")
                if event == "found":
                    out["finds"] += 1
                    if out["seconds_to_found"] is None and first is not None and t is not None:
                        delta = t - first
                        if delta < 0:
                            delta += 86400        # a trial across midnight
                        out["seconds_to_found"] = round(delta, 2)
                elif event == "wrong_lock":
                    out["wrong_locks_marked"] += 1
                elif (row.get("role") == "target" and row.get("vest")
                      and row.get("target") and row["vest"] != row["target"]):
                    out["wrong_lock_rows"] += 1
                try:
                    z = float(row.get("distance_m") or "")
                except ValueError:
                    continue
                if z > 0:
                    out["distance_min_m"] = z if out["distance_min_m"] is None else min(out["distance_min_m"], z)
                    out["distance_max_m"] = z if out["distance_max_m"] is None else max(out["distance_max_m"], z)
            out["people"] = len(people)
    except (OSError, csv.Error, UnicodeDecodeError) as exc:
        out["error"] = str(exc)
    return out
