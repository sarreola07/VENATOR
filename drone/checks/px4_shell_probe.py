#!/usr/bin/env python3
"""Read-only PX4 shell probe over MAVLink (SERIAL_CONTROL), for diagnosing the EKF.

Runs only read-only shell commands (listener, param show, ekf2 status) and prints
their output. Refuses to run while venator-c2 or anything else holds the port.

    ./venv/bin/python drone/checks/px4_shell_probe.py [--seconds S] "cmd 1" "cmd 2" ...
    (no commands: a default set about optical flow, range and the EKF)
"""
import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preflight_audit import find_fc  # noqa: E402
from pymavlink import mavutil  # noqa: E402

READ_ONLY = ("listener ", "param show ", "ekf2 status", "uorb top", "sensors status", "uavcan status")
DEFAULT = [
    "listener estimator_status_flags -n 1",
    "listener estimator_aid_src_optical_flow -n 1",
    "listener vehicle_optical_flow -n 1",
    "listener sensor_optical_flow -n 1",
    "listener distance_sensor -n 1",
    "listener estimator_aid_src_rng_hgt -n 1",
    "param show SENS_FLOW*",
    "param show EKF2_OF*",
    "param show EKF2_RNG*",
    "param show EKF2_MIN_RNG",
    "param show EKF2_HGT_REF",
]


def interlock(dev):
    if subprocess.run(["systemctl", "is-active", "--quiet", "venator-c2"]).returncode == 0:
        sys.exit("REFUSED: venator-c2 is running.")
    real = os.path.realpath(dev)
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) == os.getpid():
            continue
        try:
            if any(os.path.realpath(f"/proc/{pid}/fd/{fd}") == real for fd in os.listdir(f"/proc/{pid}/fd")):
                sys.exit(f"REFUSED: {real} is held by process {pid} (quit the calibration with Q first).")
        except OSError:
            continue


class Shell:
    def __init__(self, dev):
        self.m = mavutil.mavlink_connection(dev, baud=115200)
        self.M = mavutil.mavlink
        self.m.mav.heartbeat_send(self.M.MAV_TYPE_GCS, self.M.MAV_AUTOPILOT_INVALID, 0, 0, 0)
        if self.m.wait_heartbeat(timeout=10) is None:
            sys.exit("No heartbeat from the Pixhawk.")

    def _send(self, data=b""):
        flags = self.M.SERIAL_CONTROL_FLAG_EXCLUSIVE | self.M.SERIAL_CONTROL_FLAG_RESPOND
        while True:
            chunk, data = data[:70], data[70:]
            buf = list(chunk) + [0] * (70 - len(chunk))
            self.m.mav.serial_control_send(self.M.SERIAL_CONTROL_DEV_SHELL, flags, 0, 0, len(chunk), buf)
            if not data:
                return

    def run(self, cmd, seconds):
        if not cmd.startswith(READ_ONLY):
            return f"(skipped: '{cmd}' is not on the read-only list)"
        self._send((cmd + "\n").encode())
        out = bytearray()
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._send()  # poll for output
            m = self.m.recv_match(type="SERIAL_CONTROL", blocking=True, timeout=0.05)
            if m is not None and m.count:
                out += bytearray(m.data[:m.count])
        return out.decode(errors="replace")

    def close(self):
        # release the shell (no EXCLUSIVE flag) so PX4 goes back to normal
        self.m.mav.serial_control_send(self.M.SERIAL_CONTROL_DEV_SHELL, 0, 0, 0, 0, [0] * 70)
        self.m.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=2.5, help="how long to collect each command's output")
    ap.add_argument("cmds", nargs="*")
    a = ap.parse_args()
    dev = find_fc()
    interlock(dev)
    sh = Shell(dev)
    try:
        sh.run("", 1.0)  # wake the shell
        for cmd in a.cmds or DEFAULT:
            print(f"\n######## {cmd}")
            print(sh.run(cmd, a.seconds).replace("\r", ""))
    finally:
        sh.close()


if __name__ == "__main__":
    main()
