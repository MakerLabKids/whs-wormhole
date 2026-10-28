#!/bin/bash
# setup-pi.sh: turn a fresh Raspberry Pi OS Lite (64-bit, Trixie) into a Burrow.
#
#   sudo ./setup-pi.sh <room 0|1|2|3> [--no-partition] [--defer-net]
#
#   room 0 is the Portal's own Pi (burrow0 at 192.168.80.10): the Burrow every
#   Bin tries first when it lands on the Portal's Wi-Fi, and the watchdog for
#   the Portal's school-network join.
#
#   --defer-net   save the static classroom address but do not switch to it now
#                 (use when setting up through the Portal or a home LAN; the Pi
#                 takes 192.168.8N.10 at the next boot or cable change)
#
# Run ONCE, as root, on a Pi that has booted, has internet (for apt), and
# whose root partition was NOT auto-expanded (see docs/design/burrow.html:
# remove the firstboot init= token from cmdline.txt before the first boot).
# Idempotent where it can be. It does NOT enable the read-only overlay: that
# is burrow-lock.sh, run last, after cloudflared has its token.
set -euo pipefail

ROOM="${1:-}"
case "$ROOM" in 0|1|2|3) ;; *) echo "usage: sudo $0 <room 0|1|2|3> [--no-partition] [--defer-net]"; exit 2;; esac
NOPART=0; DEFER_NET=0
for a in "${@:2}"; do case "$a" in --no-partition) NOPART=1;; --defer-net) DEFER_NET=1;; *) echo "unknown option $a"; exit 2;; esac; done
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 2; }

HOST="burrow$ROOM"
LAN_IP="192.168.8${ROOM}.10"
LAN_GW="192.168.8${ROOM}.1"
HERE="$(cd "$(dirname "$0")" && pwd)"
say() { printf '\n\033[1;32m== %s\033[0m\n' "$*"; }

say "hostname -> $HOST"
hostnamectl set-hostname "$HOST"
sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$HOST/" /etc/hosts || true
# cloud-init re-applies user-data every boot on Trixie and would undo the
# hostname; it has done its job (user, ssh), so switch it off.
touch /etc/cloud/cloud-init.disabled 2>/dev/null || true

ADMIN_USER="${SUDO_USER:-}"
if [ -n "$ADMIN_USER" ] && [ "$ADMIN_USER" != root ] && [ ! -f /etc/sudoers.d/010-"$ADMIN_USER"-nopasswd ]; then
  say "sudo without a password for $ADMIN_USER"
  echo "$ADMIN_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/010-"$ADMIN_USER"-nopasswd
  chmod 440 /etc/sudoers.d/010-"$ADMIN_USER"-nopasswd
fi

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq chrony parted curl ca-certificates gnupg iperf3 >/dev/null
# iperf3 server always on (port 5201, ~4 MB idle): real throughput numbers from any
# Bin, Pi or laptop on the LAN:  iperf3 -c 192.168.8N.10
DEBIAN_FRONTEND=noninteractive systemctl enable --now iperf3 >/dev/null 2>&1 || true
# fake-hwclock on Trixie has a bug that reverts the clock; the Pi 5 RTC +
# chrony cover its job.
apt-get purge -y -qq fake-hwclock >/dev/null 2>&1 || true

say "data partition"
DEV="$(findmnt -n -o SOURCE / | sed 's/p[0-9]*$//')"       # /dev/mmcblk0
ROOTP="$(findmnt -n -o SOURCE /)"
ROOTN="${ROOTP##*p}"
# An un-expanded Trixie Lite root is 2.4 GiB with ~150 MB free: too small for
# apt lists and cloudflared. Grow it (online, in place) to ROOT_GIB before
# anything else is carved out of the free space.
ROOT_GIB="${ROOT_GIB:-6}"
ROOT_BYTES="$(lsblk -nbdo SIZE "$ROOTP")"
NPARTS0="$(lsblk -nlo NAME,TYPE "$DEV" | awk '$2=="part"' | wc -l)"
if [ "$NOPART" = 0 ] && [ "$NPARTS0" -le 2 ] && [ "$ROOT_BYTES" -lt $((ROOT_GIB*1024*1024*1024)) ]; then
  echo "root is $((ROOT_BYTES/1024/1024)) MiB: growing it to ${ROOT_GIB} GiB"
  echo ",${ROOT_GIB}G" | sfdisk --no-reread --force -N "$ROOTN" "$DEV" >/dev/null
  partx -u "$DEV" 2>/dev/null || partprobe "$DEV" 2>/dev/null || true
  resize2fs "$ROOTP" >/dev/null
  echo "root now: $(df -h / | awk 'NR==2{print $2" ("$4" free)"}')"
fi
# A previous run may have created the partition but been unable to see it
# until a reboot (the kernel sometimes refuses to re-read a busy table).
LASTP="$(lsblk -nlo NAME,TYPE "$DEV" | awk '$2=="part"{print $1}' | tail -1)"
NPARTS="$(lsblk -nlo NAME,TYPE "$DEV" | awk '$2=="part"' | wc -l)"
if [ "$NOPART" = 0 ] && ! blkid -L burrowdata >/dev/null 2>&1 && [ "$NPARTS" -ge 3 ] && [ -z "$(blkid -s TYPE -o value "/dev/$LASTP")" ]; then
  echo "found an unformatted third partition /dev/$LASTP from an earlier run: formatting it"
  mkfs.ext4 -q -L burrowdata "/dev/$LASTP"
fi
if [ "$NOPART" = 0 ] && ! blkid -L burrowdata >/dev/null 2>&1; then
  FREE_START="$(parted -ms "$DEV" unit s print free | awk -F: '/free/ {s=$2} END {print s}')"
  FREE_END="$(parted -ms "$DEV" unit s print free | awk -F: '/free/ {e=$3} END {print e}')"
  FREE_S=$(( ${FREE_END%s} - ${FREE_START%s} ))
  if [ "$FREE_S" -gt $((4*1024*1024*2)) ]; then      # > 4 GiB of free sectors
    echo "creating data partition in free space ($((FREE_S/2048)) MiB)"
    parted -s "$DEV" mkpart primary ext4 "$FREE_START" 100%
    partprobe "$DEV" 2>/dev/null || true; sleep 2
    NEWP="$(lsblk -nlo NAME,TYPE "$DEV" | awk '$2=="part"{print $1}' | tail -1)"
    if [ "$NEWP" = "$LASTP" ] || [ ! -b "/dev/$NEWP" ]; then
      echo "!! the kernel has not picked up the new partition yet. Reboot and run this script again;"
      echo "!! it will find and format the partition on the second pass."
      exit 3
    fi
    mkfs.ext4 -q -L burrowdata "/dev/$NEWP"
  else
    echo "!! no free space after root ($FREE_S sectors). Root was auto-expanded."
    echo "!! Continuing in single-partition mode: /data lives on the root filesystem"
    echo "!! and burrow-lock.sh will refuse to enable the overlay. Re-image to fix."
    NOPART=1
  fi
fi
mkdir -p /data
if blkid -L burrowdata >/dev/null 2>&1; then
  grep -q 'LABEL=burrowdata' /etc/fstab || \
    echo 'LABEL=burrowdata  /data  ext4  defaults,noatime,data=journal,commit=5  0  2' >> /etc/fstab
  mount -a
  echo "/data mounted: $(findmnt -n -o SOURCE,OPTIONS /data)"
else
  echo "single-partition mode: /data is a directory on /"
fi

say "quiet the SD card: journald in RAM, no swap, no apt timers"
install -D -m 644 "$HERE/etc/journald-volatile.conf" /etc/systemd/journald.conf.d/volatile.conf
systemctl restart systemd-journald
swapoff -a || true
# Trixie's rpi-swap is a systemd generator configured by drop-ins (takes effect at reboot)
if [ -d /etc/rpi ] || command -v rpi-swap >/dev/null 2>&1; then
  mkdir -p /etc/rpi/swap.conf.d
  printf '[Main]\nMechanism=none\n' > /etc/rpi/swap.conf.d/90-burrow-no-swap.conf
fi
for u in dphys-swapfile.service apt-daily.timer apt-daily-upgrade.timer man-db.timer; do
  systemctl disable --now "$u" >/dev/null 2>&1 || true
  systemctl mask "$u" >/dev/null 2>&1 || true
done
# the root stays rw until burrow-lock.sh; still, no atime churn (Pi OS
# already mounts / noatime; only add it if a line lacks it)
awk '$2=="/" && $3=="ext4" && $4 !~ /noatime/ { $4 = $4 ",noatime" } { print }' /etc/fstab > /etc/fstab.new && mv /etc/fstab.new /etc/fstab

say "network: static $LAN_IP on eth0, Wi-Fi off until the watchdog needs it, Bluetooth off"
# A fresh, explicitly saved profile (the auto-generated "Wired connection 1"
# lives in /run on Trixie and is not persistent). Idempotent.
if nmcli -t -f NAME connection show | grep -qx burrow-lan; then
  nmcli connection modify burrow-lan ipv4.method manual ipv4.addresses "$LAN_IP/24" \
    ipv4.gateway "$LAN_GW" ipv4.dns "$LAN_GW" ipv6.method disabled connection.autoconnect yes \
    connection.autoconnect-priority 10
else
  nmcli connection add type ethernet ifname eth0 con-name burrow-lan ipv4.method manual \
    ipv4.addresses "$LAN_IP/24" ipv4.gateway "$LAN_GW" ipv4.dns "$LAN_GW" ipv6.method disabled \
    connection.autoconnect yes connection.autoconnect-priority 10 >/dev/null
fi
ls /etc/NetworkManager/system-connections/ | grep -q burrow-lan || echo "!! burrow-lan profile is not under /etc; check nmcli"
if [ "$DEFER_NET" = 1 ]; then
  echo "static $LAN_IP saved (--defer-net): it takes effect at the next boot or when the cable moves"
else
  echo "switching eth0 to $LAN_IP now (an SSH session on the old address will drop; reconnect to $LAN_IP)"
  nmcli connection up burrow-lan >/dev/null 2>&1 || true
fi
# The radio stays present but off: tunnel-watchdog.py turns it on to reach
# another Opal when this room's cable path is dead, and off again after.
nmcli radio wifi off || true
CFG=/boot/firmware/config.txt
sed -i '/^dtoverlay=disable-wifi$/d' $CFG        # earlier images disabled it in firmware; undo
grep -q '^dtoverlay=disable-bt' $CFG || echo 'dtoverlay=disable-bt' >> $CFG

say "time: chrony peers with the other Burrows, orphan mode when offline"
PEERS=""
for r in 0 1 2 3; do
  [ "$r" = "$ROOM" ] && continue
  if [ "$r" = 0 ]; then P=192.168.80.10; else P="192.168.80.2${r}"; fi
  PEERS="${PEERS}peer $P minpoll 4 maxpoll 6 xleave
"
done
awk -v peers="$PEERS" '{ if ($0=="__PEERS__") printf "%s", peers; else print }' \
  "$HERE/etc/chrony.conf.template" > /etc/chrony/chrony.conf
systemctl enable --now chrony >/dev/null
systemctl restart chrony

say "burrow user, config, sudoers"
id burrow >/dev/null 2>&1 || useradd --system --home /opt/burrow --shell /usr/sbin/nologin burrow
mkdir -p /etc/burrow /data/burrow
chown burrow:burrow /data/burrow
if [ ! -f /etc/burrow/burrow.json ]; then
  python3 - "$ROOM" > /etc/burrow/burrow.json <<'PY'
import json, sys
room = int(sys.argv[1])
cfg = {
  "edge": "burrow%d" % room, "room": room, "listen": "0.0.0.0", "port": 8080,
  "data_dir": "/data/burrow", "www_dir": "/opt/burrow/www",
  "peers": {"burrow%d" % r: ("http://192.168.80.10:8080" if r == 0 else "http://192.168.80.2%d:8080" % r)
            for r in (0, 1, 2, 3) if r != room},
  "cloud": {"url": "https://whs.makerlabkids.com", "token_file": "/etc/burrow/cloud.token",
            "live_key_file": "/etc/burrow/live.key", "every_s": 60},
  "seal_minutes": 15, "fsync_s": 30, "retain_days": 7, "replicate_every_s": 120,
  "sweep": {"enabled": True, "every_s": 300, "first": 100, "last": 249}}
print(json.dumps(cfg, indent=2))
PY
fi
install -m 440 "$HERE/etc/sudoers-burrow" /etc/sudoers.d/burrow
visudo -c -q

say "install the service"
"$HERE/install.sh"

say "done. Next:"
cat <<TXT
  1. Check:   curl -s http://$LAN_IP:8080/health
  2. Cloud:   when the Surface exists, put the tokens in place:
                echo '<token>' | sudo tee /etc/burrow/cloud.token
                echo '<key>'   | sudo tee /etc/burrow/live.key
                sudo chmod 640 /etc/burrow/*.token /etc/burrow/*.key; sudo chgrp burrow /etc/burrow/*.token /etc/burrow/*.key
              and install cloudflared:  sudo ./install-cloudflared.sh <tunnel token>
  3. Lock:    sudo ./burrow-lock.sh      (read-only root; reboot)
TXT
