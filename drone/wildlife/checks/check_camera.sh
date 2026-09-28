#!/usr/bin/env bash
# Quick health check for the IMX219 on CAM0 of a Jetson Orin Nano (L4T R39).
# Read-only. No sudo needed. Exit 0 = healthy.
#
#   ./check_camera.sh

pass=0; fail=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$1"; pass=$((pass+1)); }
no()   { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=$((fail+1)); }
info() { printf '  ----  %s\n' "$1"; }

# Printed whenever frames fail to arrive. Re-probes I2C rather than reusing
# the earlier reading, because during a failed capture the sensor is powered
# up and so the probe is meaningful at this point even if it was not before.
mipi_hint() {
  local probe
  probe=$(i2ctransfer -y -f 9 w2@0x10 0x00 0x00 r2 2>/dev/null)
  if [ "$probe" = "0x02 0x19" ]; then
    info "  -> sensor answers on I2C ($probe) but zero frames arrived, so the"
    info "     fault is in the MIPI physical layer, not in software."
    info "     Silence with NO ecc/crc errors means no signal at all rather"
    info "     than a noisy one: suspect the 24 MHz MCLK or an open/swapped"
    info "     CSI pair. Jumper wires cannot carry 912 Mbps/lane."
  else
    info "  -> sensor does not answer on I2C either. Check 3.3V, SCL, SDA and"
    info "     that the ribbon is fully seated at BOTH ends, contacts facing"
    info "     the heatsink. CSI is not hot-swappable: power off before"
    info "     reseating, then remove power for 10s."
  fi
  info "     Confirm with:"
  info "       journalctl -u nvargus-daemon -n 40 | grep -i timeout"
  info "       sudo dmesg | grep -iE 'nvcsi|Physical rate|Lanes:'"
}

echo "IMX219 / CAM0 health check"
echo

# 1. Boot config actually selects the camera overlay.
if grep -qE '^\s*OVERLAYS .*imx219-A\.dtbo' /boot/extlinux/extlinux.conf 2>/dev/null; then
  ok "extlinux.conf has the imx219-A overlay"
else
  no "no imx219-A OVERLAYS line in /boot/extlinux/extlinux.conf"
fi

# 2. Overlay actually merged into the live device tree.
if [ -d /proc/device-tree/tegra-camera-platform ]; then
  badge=$(find /proc/device-tree/tegra-camera-platform -name badge -print -quit 2>/dev/null)
  badge=$([ -n "$badge" ] && tr -d '\0' < "$badge")
  ok "tegra-camera-platform present (badge: ${badge:-unknown})"
else
  no "tegra-camera-platform missing - overlay not applied; reboot needed?"
fi

# 3. Driver bound.
if lsmod | grep -q '^nv_imx219'; then ok "nv_imx219 module loaded"
else no "nv_imx219 not loaded"; fi

# 4. Sensor really answers on I2C.
#
#    Do NOT trust 'UU' from i2cdetect here. UU only means "some driver has
#    claimed this address, so I skipped probing it" - it proves nothing about
#    whether the chip is alive or the wiring is good. This check previously
#    reported UU as proof the sensor ACKed, which was simply wrong and hid a
#    real fault for hours.
#
#    Read the IMX219 model ID instead: regs 0x0000-0x0001 must return 0x0219.
#    -f (force) is required because nv_imx219 owns the address.
if command -v i2ctransfer >/dev/null 2>&1; then
  id=$(i2ctransfer -y -f 9 w2@0x10 0x00 0x00 r2 2>/dev/null)
  if [ "$id" = "0x02 0x19" ]; then
    ok "sensor responds on i2c-9, model ID $id (genuine IMX219)"
  else
    # nv_imx219 powers the sensor down whenever no capture is active, so an
    # idle camera legitimately does not answer here. Reporting that as a
    # failure raised a false alarm on a fully working board, so this is
    # informational only and the end-to-end capture below is the authority.
    info "no I2C answer while idle (normal: the driver powers the sensor down)"
    id=""
  fi
else
  info "i2ctransfer not installed (apt install i2c-tools); skipping real I2C probe"
fi

# 5. V4L2 node with the expected name.
if [ -e /dev/video0 ]; then
  name=$(cat /sys/class/video4linux/video0/name 2>/dev/null)
  ok "/dev/video0 present ($name)"
else
  no "/dev/video0 missing"
fi

# 6. Modes enumerate.
if command -v v4l2-ctl >/dev/null 2>&1 && [ -e /dev/video0 ]; then
  n=$(v4l2-ctl -d /dev/video0 --list-formats-ext 2>/dev/null | grep -c 'Size: Discrete')
  if [ "$n" -ge 5 ]; then ok "$n sensor modes enumerated (expect 5)"
  else no "only $n modes enumerated (expect 5)"; fi
fi

# 7. Argus daemon.
if systemctl is-active --quiet nvargus-daemon; then ok "nvargus-daemon active"
else no "nvargus-daemon not active"; fi

# 8. End-to-end capture: 10 frames through the full ISP path.
#
#    Argus permits only one consumer of the sensor, so if the live feed is
#    already up this test cannot run and would report a bogus failure. Detect
#    that first and say so instead.
if [ -e /dev/video0 ] && pgrep -f 'imx219_feed\.py --display' >/dev/null 2>&1; then
  info "live feed is already running (pid $(pgrep -f 'imx219_feed\.py --display' | head -1))"
  info "  skipping the end-to-end capture: Argus allows only one consumer."
  info "  A running feed is itself proof that capture works."
elif [ -e /dev/video0 ]; then
  tmp=$(mktemp -d)
  if timeout 60 gst-launch-1.0 nvarguscamerasrc sensor-id=0 sensor-mode=4 num-buffers=10 \
        ! 'video/x-raw(memory:NVMM),width=1280,height=720,framerate=60/1' \
        ! nvjpegenc ! multifilesink location="$tmp/f_%d.jpg" >/dev/null 2>&1; then
    sz=$(stat -c%s "$tmp/f_9.jpg" 2>/dev/null || echo 0)
    # A black or broken frame compresses to almost nothing.
    if [ "$sz" -gt 20000 ]; then
      ok "captured 10 frames; last JPEG ${sz} bytes (real image data)"
    else
      no "capture produced no real image data (last JPEG ${sz} bytes)"
      mipi_hint
    fi
  else
    no "Argus capture failed to run"
    mipi_hint
  fi
  rm -rf "$tmp"
fi

# Context, not pass/fail.
echo
mode=$(nvpmodel -q 2>/dev/null | grep -i 'power mode' | head -1)
info "${mode:-power mode unknown}  cores online: $(cat /sys/devices/system/cpu/online)"
info "at 7W expect ~52 fps at 640x360 (numpy) or ~46 fps at 720p (display)"

echo
if [ "$fail" -eq 0 ]; then
  printf '\033[32mAll %d checks passed.\033[0m\n' "$pass"; exit 0
else
  printf '\033[31m%d of %d checks failed.\033[0m\n' "$fail" "$((pass+fail))"; exit 1
fi
