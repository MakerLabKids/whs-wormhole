#!/bin/bash
# burrow-lock.sh: make the root and boot filesystems read-only (overlay in RAM).
# After this, nothing but /data is ever written. Reboots at the end.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 2; }
if ! findmnt -n /data >/dev/null; then
  echo "/data is not a separate mount; refusing to lock a root that holds the data."; exit 1
fi
if grep -q 'boot=overlay' /proc/cmdline; then echo "already locked"; exit 0; fi
# raspi-config and update-initramfs write to the boot partition: make sure it is writable now
mount -o remount,rw /boot/firmware 2>/dev/null || true
# Trixie: the overlay module must be in the initramfs or boot=overlay silently does nothing.
grep -qx overlay /etc/initramfs-tools/modules || echo overlay >> /etc/initramfs-tools/modules
update-initramfs -u -k all
raspi-config nonint enable_overlayfs
raspi-config nonint enable_bootro
sync
echo "locked: root + boot read-only after reboot. To change anything: burrow-unlock.sh"
echo "rebooting in 5 s..."; sleep 5; reboot
