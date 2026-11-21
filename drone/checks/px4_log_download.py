#!/usr/bin/env python3
"""Download PX4 flight logs (ULog) from the Pixhawk's SD card over MAVLink. Read-only.

    ./venv/bin/python drone/checks/px4_log_download.py --list
    ./venv/bin/python drone/checks/px4_log_download.py --last 8 [--out DIR]

Uses only the MAVLink log protocol (LOG_REQUEST_LIST, LOG_REQUEST_DATA,
LOG_REQUEST_END). It never erases anything. It refuses while venator-c2 (or anything
else) holds the Pixhawk port, and while the aircraft is armed. Files already
downloaded with the right size are skipped, so it can be run again after a stop.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OUT = os.path.expanduser("~/.local/state/venator/ulogs")
CHUNK = 90          # LOG_DATA payload size


class Px4Logs:
    def __init__(self, dev):
        from pymavlink import mavutil
        self.M = mavutil.mavlink
        self.m = mavutil.mavlink_connection(dev, baud=115200)
        self.m.mav.heartbeat_send(self.M.MAV_TYPE_GCS, self.M.MAV_AUTOPILOT_INVALID, 0, 0, 0)
        if self.m.wait_heartbeat(timeout=10) is None:
            sys.exit("REFUSED: no heartbeat from the Pixhawk.")

    def require_disarmed(self):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            hb = self.m.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
            if hb is None or hb.autopilot != self.M.MAV_AUTOPILOT_PX4:
                continue
            if hb.base_mode & self.M.MAV_MODE_FLAG_SAFETY_ARMED:
                sys.exit("REFUSED: the aircraft is ARMED.")
            return
        sys.exit("REFUSED: no fresh heartbeat from the autopilot.")

    def entries(self):
        self.m.mav.log_request_list_send(self.m.target_system, self.m.target_component, 0, 0xFFFF)
        found, total = {}, None
        end = time.monotonic() + 8
        while time.monotonic() < end:
            e = self.m.recv_match(type="LOG_ENTRY", blocking=True, timeout=0.5)
            if e is None:
                continue
            total = e.num_logs
            if total == 0:
                break
            found[e.id] = e
            end = time.monotonic() + 2
            if len(found) >= total:
                break
        if total and len(found) < total:
            print(f"(only {len(found)} of {total} log entries arrived; the newest are what matter)")
        return [found[k] for k in sorted(found)]

    def download(self, e, path):
        size = e.size
        nchunks = (size + CHUNK - 1) // CHUNK
        have = bytearray(nchunks)
        data = bytearray(size)
        got = 0
        shown = -1

        def request(first, count_chunks):
            self.m.mav.log_request_data_send(self.m.target_system, self.m.target_component,
                                             e.id, first * CHUNK, count_chunks * CHUNK)

        request(0, nchunks)
        retries = 0
        t0 = time.monotonic()
        while got < nchunks:
            d = self.m.recv_match(type="LOG_DATA", blocking=True, timeout=1.5)
            if d is None:
                retries += 1
                if retries > 40:
                    print(f"\n  FAILED: log {e.id} stalled at {got}/{nchunks} chunks.")
                    return False
                first = have.find(0)
                run = first
                while run < nchunks and not have[run] and run - first < 2000:
                    run += 1
                request(first, run - first)
                continue
            if d.id != e.id or d.ofs % CHUNK or d.count == 0:
                continue
            i = d.ofs // CHUNK
            if i >= nchunks or have[i]:
                continue
            n = min(d.count, size - d.ofs)
            data[d.ofs:d.ofs + n] = bytes(d.data[:n])
            have[i] = 1
            got += 1
            retries = 0
            pct = got * 100 // nchunks
            if pct // 5 != shown:
                shown = pct // 5
                rate = got * CHUNK / max(0.1, time.monotonic() - t0) / 1024
                print(f"\r  log {e.id}: {pct:3d}%  ({size / 1e6:.1f} MB, {rate:.0f} kB/s)", end="", flush=True)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        print(f"\r  log {e.id}: done  ({size / 1e6:.1f} MB) -> {path}")
        return True

    def end(self):
        self.m.mav.log_request_end_send(self.m.target_system, self.m.target_component)

    def close(self):
        self.m.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="only list the logs on the SD card")
    ap.add_argument("--last", type=int, default=8, help="download the newest N logs (default 8)")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    from preflight_audit import find_fc        # noqa: E402
    from px4_shell_probe import interlock      # noqa: E402
    dev = find_fc()
    interlock(dev)
    px4 = Px4Logs(dev)
    try:
        px4.require_disarmed()
        logs = px4.entries()
        if not logs:
            print("No logs on the SD card.")
            return 1
        print(f"{len(logs)} logs on the SD card. Newest:")
        for e in logs[-max(a.last, 10):]:
            when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(e.time_utc)) if e.time_utc else "no UTC time"
            print(f"  id {e.id:4d}  {e.size / 1e6:6.2f} MB  {when}")
        if a.list:
            return 0
        os.makedirs(a.out, exist_ok=True)
        ok = True
        for e in logs[-a.last:]:
            path = os.path.join(a.out, f"log_{e.id:04d}.ulg")
            if os.path.exists(path) and os.path.getsize(path) == e.size:
                print(f"  log {e.id}: already here, skipped")
                continue
            ok = px4.download(e, path) and ok
        print("All done." if ok else "Some logs failed; run it again to fetch the rest.")
        return 0 if ok else 1
    finally:
        try:
            px4.end()
        finally:
            px4.close()


if __name__ == "__main__":
    sys.exit(main())
