#!/usr/bin/env bash
#
# Enable the IMX219 camera on CAM0 of a Jetson Orin Nano Developer Kit
# running L4T R39.x (JetPack 7.x).
#
# Works around an R39 packaging regression: nvidia-l4t-jetson-io globs
# /boot/dtb/*.dtb, but nvidia-l4t-kernel-dtbs installs DTBs flat into /boot/.
#
# DRY RUN BY DEFAULT. Nothing is modified unless you pass --apply.
#
#   sudo ./setup_cam0.sh            # inspect only
#   sudo ./setup_cam0.sh --apply    # make the change
#
# Does NOT reboot. Review the printed diff, then reboot yourself.

set -euo pipefail

HDR_NAME="Jetson 22pin CSI Connector"
HW_NAME="Camera IMX219-A"      # CAM0. Use "Camera IMX219-C" for CAM1.
JETSON_IO=/opt/nvidia/jetson-io/config-by-hardware.py
EXTLINUX=/boot/extlinux/extlinux.conf
DTBDIR=/boot/dtb

APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
step() { printf '\n=== %s ===\n' "$*"; }

[ "$(id -u)" -eq 0 ] || die "must run as root (use sudo)"

# ---------------------------------------------------------------- 1. board check
step "1. Board identity"
LIVE_C=$(tr '\0' ' ' < /proc/device-tree/compatible | sed 's/ $//')
LIVE_M=$(tr -d '\0' < /proc/device-tree/model)
printf 'compatible : %s\nmodel      : %s\nL4T        : %s\n' \
  "$LIVE_C" "$LIVE_M" "$(sed -n '1s/^# //p' /etc/nv_tegra_release)"

case "$LIVE_C" in
  *p3768-0000+p3767-*) ;;
  *) die "not a p3768/p3767 Orin Nano carrier; this script does not apply" ;;
esac

# ------------------------------------------------- 2. find the right base DTB
# Match on compatible AND model, exactly as jetson-io does, then prefer the
# -nv variant. The -nv DTB carries rtcpu@bc00000 and camera-ivc-channels,
# which the camera pipeline needs; the plain DTB lacks them.
step "2. Selecting base DTB"
MATCHES=()
for f in /boot/*.dtb; do
  [ -e "$f" ] || continue
  C=$(fdtget -t s "$f" / compatible 2>/dev/null) || continue
  M=$(fdtget -t s "$f" / model 2>/dev/null) || continue
  if [ "$C" = "$LIVE_C" ] && [ "$M" = "$LIVE_M" ]; then
    MATCHES+=("$f")
    echo "  match: $(basename "$f")"
  fi
done
[ ${#MATCHES[@]} -gt 0 ] || die "no /boot/*.dtb matches this board's compatible+model"

BASE_DTB=""
for f in "${MATCHES[@]}"; do
  case "$f" in *-nv.dtb) BASE_DTB="$f" ;; esac
done
[ -n "$BASE_DTB" ] || BASE_DTB="${MATCHES[0]}"

# Corroborate the choice against the live tree rather than trusting the name.
if [ -e /proc/device-tree/rtcpu@bc00000 ] && [ -e /proc/device-tree/camera-ivc-channels ]; then
  echo "  live tree has rtcpu@bc00000 + camera-ivc-channels (expected on -nv)"
  case "$BASE_DTB" in
    *-nv.dtb) ;;
    *) die "live tree looks like -nv but no -nv DTB matched; stopping rather than guessing" ;;
  esac
else
  echo "  WARNING: live tree lacks rtcpu@bc00000/camera-ivc-channels."
  echo "  That is unexpected. Stop and investigate before applying."
  [ $APPLY -eq 1 ] && die "refusing to apply with an unexpected live tree"
fi
echo "  chosen: $BASE_DTB"

# ------------------------------------------- 3. stage it where jetson-io looks
step "3. Staging $DTBDIR"
if [ -d "$DTBDIR" ]; then
  EXISTING=$(find "$DTBDIR" -maxdepth 1 -name '*.dtb' | wc -l)
  echo "  $DTBDIR exists with $EXISTING .dtb file(s)"
  if [ "$EXISTING" -gt 1 ]; then
    die "$DTBDIR holds multiple .dtb files; jetson-io will fail with 'Multiple DTBs found'. Clear it first."
  fi
else
  echo "  $DTBDIR does not exist (expected on R39)"
fi

# A real copy, not a symlink: UEFI's ext4 reader loads the FDT file directly
# and symlink resolution is not something to rely on.
if [ $APPLY -eq 1 ]; then
  mkdir -p "$DTBDIR"
  cp -v "$BASE_DTB" "$DTBDIR/"
else
  echo "  [dry run] would: mkdir -p $DTBDIR && cp $BASE_DTB $DTBDIR/"
  echo "  [dry run] cannot query jetson-io until the DTB is staged; stopping here."
  echo
  echo "Re-run with --apply to stage the DTB and configure the overlay."
  exit 0
fi

# --------------------------------------------------- 4. enumerate the headers
step "4. jetson-io header listing"
LIST=$("$JETSON_IO" -l) || die "jetson-io -l still failing; paste the output"
echo "$LIST"

HDRNUM=$(printf '%s\n' "$LIST" \
  | sed -n "s/^Header \([0-9]\+\).*${HDR_NAME}.*/\1/p" | head -1)
[ -n "$HDRNUM" ] || die "could not find header '$HDR_NAME' in the listing above"

BLOCK=$(printf '%s\n' "$LIST" | awk -v h="Header $HDRNUM" '
  index($0, h)==1 { inblk=1; next }
  /^Header [0-9]/  { inblk=0 }
  inblk')

printf '\n  header number : %s\n' "$HDRNUM"
printf '  modules offered:\n%s\n' "$BLOCK"

grep -qF "$HW_NAME" <<<"$BLOCK" \
  || die "'$HW_NAME' not offered on header $HDRNUM; do not force it"

# -------------------------------------------------------- 5. apply the overlay
step "5. Applying overlay"
STAMP=$(date +%Y%m%d-%H%M%S)
cp -v "$EXTLINUX" "$EXTLINUX.bak-$STAMP"

BEFORE=$(cat "$EXTLINUX")
"$JETSON_IO" -n "${HDRNUM}=${HW_NAME}"

step "6. extlinux.conf diff"
diff <(printf '%s\n' "$BEFORE") "$EXTLINUX" || true

cat <<EOF

--------------------------------------------------------------------
Done. NOT rebooted.

Review the diff above. Expect a new 'LABEL JetsonIO' stanza with:
    FDT      $DTBDIR/$(basename "$BASE_DTB")
    OVERLAYS /boot/tegra234-p3767-camera-p3768-imx219-A.dtbo
and DEFAULT switched from 'primary' to 'JetsonIO'.

The original 'primary' entry is retained. If the board misbehaves,
pick 'primary kernel' from the UEFI boot menu (needs a display+keyboard
or the ttyTCU0 serial console at 115200).

Backups: $EXTLINUX.bak-$STAMP
         $EXTLINUX.jetson-io-backup  (written by jetson-io)

Then:  sudo reboot
After: ls /dev/video0 && sudo dmesg | grep -iE 'imx219|nvcsi'
--------------------------------------------------------------------
EOF
