#!/bin/bash
# burrow-unlock.sh: make root writable again for maintenance (apt, install.sh,
# cloudflared token). Reboots. Re-lock with burrow-lock.sh when done.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 2; }
if ! grep -q 'boot=overlay' /proc/cmdline; then echo "already unlocked"; exit 0; fi
raspi-config nonint disable_overlayfs
mount -o remount,rw /boot/firmware 2>/dev/null || true
raspi-config nonint disable_bootro || true
sync
echo "unlocked after reboot. Remember burrow-lock.sh afterwards."
echo "rebooting in 5 s..."; sleep 5; reboot
