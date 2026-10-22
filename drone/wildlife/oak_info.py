#!/usr/bin/env python3
"""
Identify a Luxonis OAK / DepthAI device and report exactly what is on it.

Run with the venv interpreter that has depthai installed:

    /home/jetson/oak-venv/bin/python drone/wildlife/oak_info.py
    /home/jetson/oak-venv/bin/python drone/wildlife/oak_info.py --ir 0.3

Why this script exists: USB descriptors cannot tell OAK models apart. Every
OAK presents as 03e7:2485 (MyriadX boot ROM) and then 03e7:f63b once the
Luxonis bootloader or firmware is running. Only asking the device over the
DepthAI protocol reveals the board name and which image sensors are fitted.

The depthai API moved between 2.x and 3.x, so every call here is probed with
getattr() rather than assumed. Anything unavailable is reported, not fatal.
"""

import argparse
import sys


def probe(obj, *names):
    """Call the first existing zero-arg method from *names. Returns (name, value)."""
    for n in names:
        fn = getattr(obj, n, None)
        if callable(fn):
            try:
                return n, fn()
            except Exception as e:                      # noqa: BLE001
                return n, f"<call failed: {e}>"
    return None, None


def show(label, pair):
    name, val = pair
    if name is None:
        print(f"  {label:<22} <not exposed by this depthai version>")
    else:
        print(f"  {label:<22} {val}      [{name}()]")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ir", type=float, metavar="INTENSITY",
                    help="test the IR flood LED and laser dot projector at this "
                         "intensity (0.0-1.0). Start low: the LEDs add USB "
                         "current draw and can brown out a USB2 port.")
    ap.add_argument("--seconds", type=float, default=5.0,
                    help="how long to hold the IR LEDs on (default 5)")
    args = ap.parse_args()

    if args.ir is not None and not 0.0 <= args.ir <= 1.0:
        print("error: --ir must be between 0.0 and 1.0", file=sys.stderr)
        return 2

    try:
        import depthai as dai
    except ModuleNotFoundError:
        print("error: depthai is not installed in this interpreter.\n"
              "Install it with:\n"
              "  /home/jetson/oak-venv/bin/pip install depthai\n"
              "then run this script with /home/jetson/oak-venv/bin/python",
              file=sys.stderr)
        return 1

    print(f"depthai version: {getattr(dai, '__version__', 'unknown')}\n")

    # ---- Stage 1: enumerate without booting the device -------------------
    print("Available devices (pre-boot enumeration):")
    try:
        found = dai.Device.getAllAvailableDevices()
    except Exception as e:                              # noqa: BLE001
        print(f"  enumeration failed: {e}")
        found = []
    if not found:
        print("  NONE FOUND.\n"
              "  The device may be mid-reboot (03e7:2485 = MyriadX boot ROM).\n"
              "  Unplug, wait 3 seconds, replug, then retry.")
        return 1
    for d in found:
        bits = []
        for attr in ("name", "mxid", "state", "protocol", "platform", "status"):
            v = getattr(d, attr, None)
            if v is None:
                _, v = probe(d, f"get{attr.capitalize()}")
            if v is not None:
                bits.append(f"{attr}={v}")
        print("  " + "  ".join(str(b) for b in bits))
    print()

    # ---- Stage 2: boot firmware and interrogate --------------------------
    print("Booting firmware over USB and querying the device...")
    try:
        dev_ctx = dai.Device()
    except Exception as e:                              # noqa: BLE001
        print(f"\nerror: could not open the device: {e}\n"
              "Common causes:\n"
              "  - another process already holds it (only one host at a time)\n"
              "  - insufficient USB current; try a powered hub or USB3 port\n"
              "  - udev rule missing (03e7 needs MODE=0666)", file=sys.stderr)
        return 1

    with dev_ctx as device:
        print("\n=== Board identity ===")
        show("device name",   probe(device, "getDeviceName"))
        show("product name",  probe(device, "getProductName"))
        show("MxID / serial", probe(device, "getMxId", "getDeviceId"))
        show("platform",      probe(device, "getPlatform", "getPlatformAsString"))
        show("USB speed",     probe(device, "getUsbSpeed"))
        show("bootloader ver", probe(device, "getBootloaderVersion"))
        show("EEPROM calib",  probe(device, "getConnectedIMU"))

        print("\n=== Image sensors actually fitted ===")
        name, feats = probe(device, "getConnectedCameraFeatures")
        if name is None or not isinstance(feats, (list, tuple)):
            show("connected cameras", (name, feats))
            print("  (falling back to socket list)")
            show("connected sockets", probe(device, "getConnectedCameras"))
        else:
            if not feats:
                print("  device reports NO cameras - this may be a bare "
                      "compute module (Neural Compute Stick 2, not an OAK)")
            for f in feats:
                # These are pybind enums, not strings: they have no __format__,
                # so str() them before applying any field width.
                socket = str(getattr(f, "socket", "?")).split(".")[-1]
                sensor = str(getattr(f, "sensorName", "?"))
                w = getattr(f, "width", "?")
                h = getattr(f, "height", "?")
                types = getattr(f, "supportedTypes", [])
                hasAf = getattr(f, "hasAutofocus", None)
                print(f"  socket {socket:<8} {sensor:<10} {w}x{h}  "
                      f"types={[str(t).split('.')[-1] for t in types]}  "
                      f"autofocus={hasAf}")

        print("\n=== IR illumination (the 'onboard LEDs') ===")
        name, drivers = probe(device, "getIrDrivers")
        if name is None:
            print("  this depthai version cannot report IR drivers")
            drivers = None
        elif not drivers:
            print("  NO IR drivers present.")
            print("  This board has no software-controllable IR flood LED or")
            print("  laser dot projector. Only OAK-*-PRO variants fit them.")
            print("  The small visible status LED is hardwired, not controllable.")
        else:
            print(f"  IR drivers found: {drivers}")
            print("  Controllable: IR flood LED + laser dot projector.")

        if args.ir is not None:
            if not drivers:
                print(f"\n  skipping --ir {args.ir}: no IR hardware to drive")
            else:
                import time
                print(f"\n  Driving both IR emitters at {args.ir:.2f} for "
                      f"{args.seconds:g}s ...")
                print("  IR is invisible to the eye - point a phone camera at "
                      "the lenses to see them glow.")
                for meth, label in (
                    ("setIrFloodLightIntensity", "flood LED"),
                    ("setIrLaserDotProjectorIntensity", "dot projector"),
                ):
                    fn = getattr(device, meth, None)
                    if fn is None:
                        # 2.x spelling took milliamps instead of 0-1 intensity
                        legacy = meth.replace("Intensity", "Brightness")
                        fn = getattr(device, legacy, None)
                        if fn is not None:
                            meth = legacy
                    if fn is None:
                        print(f"    {label:<15} no API available")
                        continue
                    try:
                        arg = args.ir if "Intensity" in meth else int(args.ir * 500)
                        print(f"    {label:<15} {meth}({arg}) -> {fn(arg)}")
                    except Exception as e:              # noqa: BLE001
                        print(f"    {label:<15} failed: {e}")
                time.sleep(args.seconds)
                print("  Turning both off.")
                for meth in ("setIrFloodLightIntensity",
                             "setIrLaserDotProjectorIntensity",
                             "setIrFloodLightBrightness",
                             "setIrLaserDotProjectorBrightness"):
                    fn = getattr(device, meth, None)
                    if fn:
                        try:
                            fn(0)
                        except Exception:               # noqa: BLE001, S110
                            pass

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
