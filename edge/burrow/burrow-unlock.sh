#!/bin/bash
# burrow-unlock.sh: make root writable again for maintenance (apt, install.sh,
# cloudflared token). Reboots. Re-lock with burrow-lock.sh when done.
#
# Only the overlay is switched off here (that lives in cmdline.txt on the
# boot partition, so it must be remounted writable first). The boot
# partition itself stays read-only per fstab; when you need to edit
# config.txt after the reboot:  sudo mount -o remount,rw /boot/firmware
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 2; }
if ! grep -q 'boot=overlay' /proc/cmdline; then echo "already unlocked"; exit 0; fi
mount -o remount,rw /boot/firmware
raspi-config nonint disable_overlayfs
sync
echo "unlocked after reboot (root writable; /boot/firmware stays ro: remount it rw if you need it)."
echo "Remember burrow-lock.sh afterwards. rebooting in 5 s..."; sleep 5; reboot
