#!/usr/bin/env python3
"""Serve the VENATOR mission-planner dashboard without .NET.

The upstream project (XSilverEyeX/drone-mission-planner-css, branch
venator-gui-iteration-3) is browser -> C# ASP.NET -> Python bridge -> MAVLink.
Only ONE of its ten endpoints has real logic in C#: /api/plan, the A* planner.
Every other route is a thin JSON relay onto the bridge's TCP socket. So on a
Jetson -- aarch64, no .NET SDK installed, and a demo due today -- the C# tier is
the one piece standing between us and a working page, and it is also the piece
worth the least.

This serves the SAME wwwroot/index.html and relays the same JSON, so the UI is
unchanged and the upstream repo stays the source of truth for it. Installing the
.NET 10 ARM64 SDK and building a first-time project hours before a presentation
is the risk this avoids.

    ./venv/bin/python deploy/venator_web.py
    ./venv/bin/python deploy/venator_web.py --port 5037 --bridge-port 5555

Then open http://<jetson>:5037/ from a phone or laptop on the same network.

WHAT OWNS THE PIXHAWK

Exactly one process can hold a serial port. drone_bridge.py opens it when you
pick a port in the page, and venator-c2.service holds /dev/ttyACM0 whenever it
is running. Stop the C2 service before connecting the bridge to USB, or point
the bridge at the SiK radio instead so the two use different ports.

    sudo systemctl stop venator-c2        # frees /dev/ttyACM0 for the bridge
"""
import argparse
import json
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 5555
BRIDGE_TIMEOUT_S = 30.0          # matches the C# client's ReceiveTimeout
CONNECT_TIMEOUT_S = 2.0


def bridge(command, host=BRIDGE_HOST, port=BRIDGE_PORT):
    """One request, one response, one connection -- the bridge's whole protocol.

    DroneClient.cs opens a fresh TcpClient per command, writes a single line of
    JSON and reads a single line back. Matching that exactly matters: the bridge
    reads with readline(), so a connection reused for two commands would block.
    """
    s = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S)
    try:
        s.settimeout(BRIDGE_TIMEOUT_S)
        s.sendall((json.dumps(command) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                raise IOError("bridge closed the connection")
            buf += chunk
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    finally:
        s.close()


class Handler(BaseHTTPRequestHandler):
    wwwroot = None
    bridge_port = BRIDGE_PORT

    # Keep the console readable: one line per request, not urllib's default spam.
    def log_message(self, fmt, *args):
        sys.stderr.write("  %s %s\n" % (self.address_string(), fmt % args))

    # -- plumbing ----------------------------------------------------------
    def _json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _relay(self, command):
        """Forward to the bridge and pass its answer through untouched.

        A bridge that is down is reported as an error the page can render,
        rather than a 500: the dashboard is useful read-only, and the operator
        needs to see *why* it cannot reach the vehicle.
        """
        try:
            self._json(bridge(command, port=self.bridge_port))
        except (OSError, IOError, ValueError) as exc:
            self._json({"status": "error",
                        "message": f"bridge on 127.0.0.1:{self.bridge_port} "
                                   f"did not answer ({exc}). Start it with: "
                                   f"python3 python_bridge/drone_bridge.py"}, 200)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except ValueError:
            return {}

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._json({"status": "ok"})
        if path == "/api/status":
            return self._relay({"cmd": "get_status"})
        if path == "/api/telemetry/ports":
            return self._relay({"cmd": "get_ports"})
        return self._static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()

        if path == "/api/telemetry/connect":
            return self._relay({"cmd": "connect",
                                "port": body.get("port"), "baud": body.get("baud")})
        if path == "/api/telemetry/disconnect":
            return self._relay({"cmd": "disconnect"})
        if path == "/api/demo/enable":
            return self._relay({"cmd": "enable_demo",
                                "enabled": body.get("enabled"),
                                "confirmed": body.get("confirmed")})
        if path == "/api/abort":
            return self._relay({"cmd": "abort"})
        if path.startswith("/api/demo/"):
            # The page posts the action as the last path segment and any
            # parameters in the body; the bridge expects them flattened into
            # one object with cmd=<action>. Program.cs does the same.
            action = path[len("/api/demo/"):].strip("/")
            if not action.replace("_", "").isalnum():
                return self._json({"status": "error", "message": "bad action"}, 400)
            return self._relay(dict(body, cmd=action))
        if path == "/api/plan":
            # The only endpoint with real C# behind it: quadtree + A* +
            # line-of-sight smoothing. Not ported, and not needed for the
            # indoor bench demo, where the planner panel stays collapsed and
            # navigation is gated off anyway for want of a position estimate.
            return self._json({"status": "error",
                               "message": "Path planning needs the C# service "
                                          "(dotnet run --project DroneNavigation.Web). "
                                          "Telemetry and the gated bench controls "
                                          "work without it."}, 200)
        return self._json({"status": "error", "message": "no such endpoint"}, 404)

    # -- static ------------------------------------------------------------
    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (self.wwwroot / rel).resolve()
        # Refuse anything that escapes wwwroot. The page is served to whatever
        # is on the network, so a traversal here would hand out the filesystem.
        if not str(target).startswith(str(self.wwwroot.resolve())) or not target.is_file():
            self.send_error(404)
            return
        ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
                 ".css": "text/css", ".json": "application/json",
                 ".svg": "image/svg+xml", ".png": "image/png",
                 ".ico": "image/x-icon"}.get(target.suffix, "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser(description="VENATOR dashboard without .NET")
    ap.add_argument("--wwwroot", default=str(Path.home() / "Desktop"
                    / "drone-mission-planner-css" / "csharp"
                    / "DroneNavigation.Web" / "wwwroot"))
    ap.add_argument("--port", type=int, default=5037)
    ap.add_argument("--bridge-port", type=int, default=BRIDGE_PORT)
    # 0.0.0.0 by default: the whole point is reaching it from a phone. The
    # bridge itself stays on loopback, so the vehicle link is not exposed --
    # only this page is, and it carries no credential. Do not run it on a
    # network you do not control.
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    root = Path(args.wwwroot)
    if not (root / "index.html").is_file():
        sys.exit(f"no index.html under {root}\n"
                 f"clone it first:  git clone -b venator-gui-iteration-3 "
                 f"https://github.com/XSilverEyeX/drone-mission-planner-css.git")

    Handler.wwwroot = root
    Handler.bridge_port = args.bridge_port

    print(f"  serving {root}")
    print(f"  bridge  127.0.0.1:{args.bridge_port}")
    print(f"  open    http://<this-jetson>:{args.port}/")
    try:
        ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")


if __name__ == "__main__":
    main()
