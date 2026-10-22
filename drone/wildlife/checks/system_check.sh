#!/usr/bin/env bash
# Full system check for the Jetson Orin Nano + IMX219-160 IR-CUT camera rig.
# Read-only, no sudo required.  ./system_check.sh
#
# Complements check_camera.sh: that one answers "does the camera work?",
# this one answers "is anything else about this box wrong?".

sec() { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$1"; WARNS=$((WARNS+1)); }
good() { printf '  \033[32mok\033[0m    %s\n' "$1"; }
WARNS=0

sec "Platform"
printf '  %s\n' "$(tr -d '\0' < /proc/device-tree/model 2>/dev/null)"
printf '  %s\n' "$(head -1 /etc/nv_tegra_release 2>/dev/null)"
printf '  kernel %s | ubuntu %s\n' "$(uname -r)" "$(. /etc/os-release && echo "$VERSION_ID")"
printf '  uptime %s (booted %s)\n' "$(uptime -p | sed 's/^up //')" "$(uptime -s)"

sec "Power / thermal"
# The rig is required to run at 7 W (nvpmodel ID 1). Checking only the live
# mode is not enough: on 2026-09-28 it silently reverted to 15 W across a
# reboot because /etc/nvpmodel.conf still carried DEFAULT=0, and nothing
# flagged it. So verify the live mode AND the two things that decide what
# comes back after a power cycle.
REQUIRED_MODE=1
REQUIRED_NAME=7W

pm=$(nvpmodel -q 2>/dev/null)
pm_name=$(printf '%s\n' "$pm" | sed -n 's/.*NV Power Mode: *//p' | tr -d ' ')
pm_id=$(printf '%s\n' "$pm" | sed -n '2p' | tr -d ' ')
cores=$(cat /sys/devices/system/cpu/online)
printf '  mode %s (id %s) | cores online %s\n' "${pm_name:-?}" "${pm_id:-?}" "$cores"

if [ "${pm_id:-}" = "$REQUIRED_MODE" ]; then
  good "running at $REQUIRED_NAME (nvpmodel id $REQUIRED_MODE)"
else
  warn "running at ${pm_name:-unknown}, NOT $REQUIRED_NAME  ->  sudo nvpmodel -m $REQUIRED_MODE"
fi

# Survives a reboot? DEFAULT= in the config wins on a fresh boot; the status
# file records the last explicit selection.
pm_default=$(sed -n 's/.*PM_CONFIG *DEFAULT=\([0-9]\+\).*/\1/p' /etc/nvpmodel.conf 2>/dev/null)
if [ "${pm_default:-}" = "$REQUIRED_MODE" ]; then
  good "boot default is $REQUIRED_NAME (PM_CONFIG DEFAULT=$pm_default)"
else
  warn "boot default is id ${pm_default:-unknown}, not $REQUIRED_MODE - it will revert on reboot"
  printf '  ----    sudo sed -i '"'"'s/PM_CONFIG DEFAULT=%s/PM_CONFIG DEFAULT=%s/'"'"' /etc/nvpmodel.conf\n' \
    "${pm_default:-0}" "$REQUIRED_MODE"
fi

pm_saved=$(sed -n 's/^pmode:0*\([0-9]\+\)$/\1/p' /var/lib/nvpmodel/status 2>/dev/null)
[ -z "$pm_saved" ] && grep -q 'pmode:0000' /var/lib/nvpmodel/status 2>/dev/null && pm_saved=0
if [ -n "$pm_saved" ] && [ "$pm_saved" != "$REQUIRED_MODE" ]; then
  warn "saved state is mode $pm_saved (/var/lib/nvpmodel/status) - re-applying with nvpmodel -m $REQUIRED_MODE rewrites it"
fi
for h in /sys/class/hwmon/hwmon*; do
  [ "$(cat "$h/name" 2>/dev/null)" = "ina3221" ] || continue
  for i in 1 2 3; do
    l=$(cat "$h/in${i}_label" 2>/dev/null) || continue
    [ -n "$l" ] && printf '  %-16s %5s mV  %5s mA\n' "$l" \
      "$(cat "$h/in${i}_input" 2>/dev/null)" "$(cat "$h/curr${i}_input" 2>/dev/null)"
  done
done
tot=$(cat /sys/class/hwmon/hwmon*/curr1_input 2>/dev/null | head -1)
mv=$(cat /sys/class/hwmon/hwmon*/in1_input 2>/dev/null | head -1)
[ -n "$tot" ] && [ -n "$mv" ] && printf '  board draw      %.2f W\n' "$(echo "$tot*$mv/1000000" | bc -l)"
hot=0
for z in /sys/class/thermal/thermal_zone*/temp; do
  t=$(cat "$z" 2>/dev/null); [ -n "$t" ] && [ "$t" -gt 80000 ] && hot=1
done
[ "$hot" = 1 ] && warn "a thermal zone is above 80 C" || good "all thermal zones under 80 C"

sec "Camera device tree"
for n in tegra-camera-platform rtcpu@bc00000 camera-ivc-channels; do
  [ -e "/proc/device-tree/$n" ] && good "$n present" || warn "$n MISSING"
done
of=/sys/bus/i2c/devices/9-0010/of_node
if [ -d "$of" ]; then
  good "sensor node $(tr -d '\0' < "$of/name") (model $(tr -d '\0' < "$of/sensor_model" 2>/dev/null))"
  printf '    port-index %s | lanes %s | mclk %s kHz\n' \
    "$(od -An -tu4 --endian=big < "$of/ports/port@0/endpoint/port-index" 2>/dev/null | tr -d ' ')" \
    "$(od -An -tu4 --endian=big < "$of/ports/port@0/endpoint/bus-width" 2>/dev/null | tr -d ' ')" \
    "$(tr -d '\0' < "$of/mode4/mclk_khz" 2>/dev/null)"
else
  warn "no sensor node at i2c 9-0010"
fi

sec "Boot config"
grep -E '^\s*(DEFAULT|FDT|OVERLAYS)' /boot/extlinux/extlinux.conf 2>/dev/null | sed 's/^\s*/  /'
n=$(grep -c '^LABEL' /boot/extlinux/extlinux.conf 2>/dev/null)
[ "$n" -gt 1 ] && good "$n boot entries (a fallback exists)" || warn "only one boot entry: no fallback if the overlay breaks"

sec "Kernel errors this boot"
# Read the kernel log through the journal, not dmesg. journalctl -k works
# unprivileged for members of the adm / systemd-journal group and is already
# scoped to the current boot, so there is no reason to relax
# kernel.dmesg_restrict (which exists to stop unprivileged processes reading
# kernel addresses out of the log) merely to run a health check.
kmsg() { journalctl -k -b --no-pager 2>/dev/null || dmesg 2>/dev/null; }
if [ -n "$(kmsg | head -1)" ]; then
  e=$(kmsg | grep -icE 'imx219.*(error|fail)|nvcsi.*error|vi5.*error' || true)
  [ "$e" -gt 0 ] && warn "$e camera error lines this boot (journalctl -k -b | grep -i imx219)" \
                 || good "no camera errors this boot"
  o=$(kmsg | grep -icE 'Out of memory|oom-kill|soctherm.*throttl' || true)
  [ "$o" -gt 0 ] && warn "$o OOM/throttle lines this boot" || good "no OOM or throttling"
else
  warn "cannot read the kernel log (need group adm or systemd-journal)"
fi

sec "Capture stack"
systemctl is-active --quiet nvargus-daemon && good "nvargus-daemon active" || warn "nvargus-daemon not active"
# Scope this to the current boot (-b). The journal persists across reboots, so
# without -b a fault that a power cycle already fixed keeps being reported as
# if it were live - which it did, on exactly this rig.
t=$(journalctl -u nvargus-daemon -b --no-pager 2>/dev/null | grep -cE 'Timeout!!|error state' || true)
[ "${t:-0}" -gt 0 ] && warn "$t timeout/error-state lines this boot" \
                    || good "no capture timeouts this boot"
[ -e /dev/video0 ] && good "/dev/video0 = $(cat /sys/class/video4linux/video0/name 2>/dev/null)" \
                   || warn "/dev/video0 missing"

sec "Display"
printf '  DISPLAY=%s  session=%s\n' "${DISPLAY:-unset}" "${XDG_SESSION_TYPE:-unset}"
DISPLAY=${DISPLAY:-:1} xrandr --query 2>/dev/null | grep ' connected' | sed 's/^/  /'
miss=""
for s in nv3dsink nveglglessink xvimagesink ximagesink nvvidconv nvjpegenc; do
  gst-inspect-1.0 "$s" >/dev/null 2>&1 || miss="$miss $s"
done
[ -n "$miss" ] && warn "missing GStreamer elements:$miss" || good "all 6 GStreamer elements present"

sec "Live feed"
. "$(dirname "$(readlink -f "$0")")/../lib_pid.sh"
p=$(script_pid imx219_feed.py --display)
if [ -n "$p" ]; then
  good "feed running (pid $p, $(ps -o etime= -p "$p" | tr -d ' ') elapsed, $(ps -o %cpu= -p "$p" | tr -d ' ')% cpu)"
else
  printf '  ----  not running; start it with ./imx219_camera.sh 720p\n'
fi

sec "Project files"
# Resolve the module from this script's own location (checks/ -> wildlife/) so
# the check works from any clone path, not just the one it was written on.
W="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
echo "  module: $W"
# Enumerate what is actually there rather than checking a hand-written list.
# The hardcoded version silently ignored four files added after it was written,
# which is exactly the failure a file check exists to catch.
missing=0
while IFS= read -r q; do
  f="${q#"$W"/}"
  if [ ! -x "$q" ]; then warn "$f not executable"; missing=1; fi
done < <(find "$W" -type f \( -name '*.py' -o -name '*.sh' \) ! -name '__init__.py' | sort)
n=$(find "$W" -type f \( -name '*.py' -o -name '*.sh' \) ! -name '__init__.py' | wc -l)
[ "$missing" = 0 ] && good "$n scripts present and executable"
# The two entry points must exist by name; everything else is discovered.
for f in imx219_camera.sh oak_camera.sh; do
  [ -x "$W/$f" ] && good "entry point $f" || warn "entry point $f MISSING"
done
# The repo ships a __REPO__ template, not a literal .desktop, so validate the
# copy that install_shortcuts.sh rendered rather than the template itself.
launcher="$HOME/.local/share/applications/wildlife-camera.desktop"
if [ -e "$launcher" ]; then
  desktop-file-validate "$launcher" 2>/dev/null \
    && good "installed wildlife-camera.desktop validates" \
    || warn "installed wildlife-camera.desktop has validation errors"
elif [ -e "$W/../../deploy/desktop/wildlife-camera.desktop.in" ]; then
  printf '  ----  launcher template present but not installed yet\n'
  printf '  ----    run: bash deploy/install_shortcuts.sh\n'
else
  warn "wildlife-camera.desktop.in template missing from deploy/desktop/"
fi

sec "Disk / memory"
df -h / | awk 'NR==2{printf "  rootfs %s used of %s (%s)\n",$3,$2,$5}'
u=$(df --output=pcent / | tr -dc '0-9')
[ "$u" -gt 90 ] && warn "rootfs over 90% full" || good "rootfs has headroom"
free -h | awk 'NR==2{printf "  mem %s used of %s, %s available\n",$3,$2,$7}'

sec "USB"
lsusb 2>/dev/null | sed 's/^/  /'
dai=0
/home/jetson/oak-venv/bin/python -c 'import depthai' 2>/dev/null && dai=1
for d in /sys/bus/usb/devices/*/idVendor; do
  [ "$(cat "$d" 2>/dev/null)" = "03e7" ] || continue
  dir=$(dirname "$d"); sp=$(cat "$dir/speed" 2>/dev/null)
  printf '  OAK %s:%s "%s" at %s Mbps\n' "$(cat "$dir/idVendor")" \
    "$(cat "$dir/idProduct")" "$(cat "$dir/product" 2>/dev/null)" "$sp"
  # Link speed only constrains anything once something is actually streaming
  # from the device, so this is a warning only when depthai is installed.
  # Otherwise it is a note, not a fault.
  if [ "${sp%%.*}" -le 480 ] 2>/dev/null; then
    if [ "$dai" = 1 ]; then
      warn "OAK on USB 2.0 ($sp Mbps) with depthai installed: move it to the USB 3.0 hub"
    else
      printf '  ----  on USB 2.0 (%s Mbps); only matters once depthai is in use\n' "$sp"
    fi
  else
    good "OAK on USB 3.0 ($sp Mbps)"
  fi
done
if [ "$dai" = 1 ]; then
  good "depthai $(/home/jetson/oak-venv/bin/python -c 'import depthai;print(depthai.__version__)' 2>/dev/null)"
else
  printf '  ----  depthai not installed (/home/jetson/oak-venv/bin/pip install depthai)\n'
fi

echo
if [ "$WARNS" -eq 0 ]; then
  printf '\033[32mNo problems found.\033[0m\n'
else
  printf '\033[33m%d warning(s) above.\033[0m\n' "$WARNS"
fi
