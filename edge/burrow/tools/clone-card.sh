#!/bin/bash
# clone-card.sh: make a golden image of a good Burrow's SD card, from a machine
# that can ssh to it, and write a new card from that image with just an
# identity file dropped on its boot partition. No flasher, no setup script.
#
#   edge/burrow/tools/clone-card.sh image 0 burrow-golden.img.gz   # read burrow0's card (locked root preferred)
#   edge/burrow/tools/clone-card.sh write burrow-golden.img.gz /dev/sdX        # a new card: it enrols itself
#   edge/burrow/tools/clone-card.sh write burrow-golden.img.gz /dev/sdX 2      # ...or is told: burrow2
#
# The image is the whole card, gzip'd; the Pi keeps serving while it is read
# (the root is read-only under the overlay, /data is the only live writer,
# so the copy is consistent enough for a fresh box: /data on the new card is
# wiped on first boot anyway). The identity file is one line of JSON on the
# boot partition, read and removed by first-boot-identity.sh on the Pi:
#   {"edge": "burrow2", "room": 2}
# Tokens (cloud, tunnel) are per-Pi secrets and do not travel in the image:
# the first boot reports "unregistered" until the Surface's enrolment hands
# them out, or you put them in the identity file ("cloud_token", "tunnel_token").
set -euo pipefail
USER_="${BURROW_USER:-worm}"
cmd="${1:-}"
case "$cmd" in
  image)
    n="${2:?burrow number}"; out="${3:?output .img.gz}"
    host="192.168.8$n.10"
    echo "reading burrow$n's card over ssh (a 32 GB card takes 10-20 minutes)..."
    ssh "$USER_@$host" "sudo sync; sudo dd if=/dev/mmcblk0 bs=4M status=none | gzip -1" > "$out"
    ls -l "$out"
    ;;
  write)
    img="${2:?image}"; dev="${3:?/dev/sdX}"; n="${4:-}"; room="${5:-$n}"
    [ "$(id -u)" = 0 ] || { echo "run with sudo (writes $dev)"; exit 2; }
    [ -b "$dev" ] || { echo "$dev is not a block device"; exit 2; }
    read -r -p "This ERASES $dev and writes a Burrow card${n:+ for burrow$n}. Type the device name again to go: " again
    [ "$again" = "$dev" ] || { echo "not that; nothing written"; exit 1; }
    gzip -dc "$img" | dd of="$dev" bs=4M status=progress conv=fsync
    partprobe "$dev" 2>/dev/null || true; sleep 2
    boot=$(lsblk -nrpo NAME,LABEL "$dev" | awk '$2=="bootfs"{print $1}' | head -1)
    [ -n "$boot" ] || boot="${dev}1"
    # the donor's per-Pi secrets do not travel: strip them and mark the card "needs identity"
    root=$(lsblk -nrpo NAME,LABEL "$dev" | awk '$2=="rootfs"{print $1}' | head -1)
    [ -n "$root" ] || root="${dev}2"
    mnt=$(mktemp -d); mount "$root" "$mnt"
    rm -f "$mnt/etc/burrow/cloud.token" "$mnt/etc/cloudflared/token"
    touch "$mnt/etc/burrow/needs-identity"
    [ -s "$mnt/etc/burrow/enrol.secret" ] || echo "WARNING: no /etc/burrow/enrol.secret on this image: the Pi cannot enrol by itself"
    umount "$mnt"
    if [ -n "$n" ]; then                    # an explicit identity instead of enrolment (no internet at first boot)
      mount "$boot" "$mnt"
      printf '{"edge": "burrow%s", "room": %s}\n' "$n" "$room" > "$mnt/burrow-identity.json"
      umount "$mnt"
    fi
    rmdir "$mnt"
    echo "done. Boot it on any room's Opal: it takes the room from the Opal's subnet and enrols with the Surface${n:+ (or becomes burrow$n from the identity file)}"
    ;;
  *) sed -n 2,20p "$0"; exit 2 ;;
esac
