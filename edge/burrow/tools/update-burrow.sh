#!/bin/bash
# update-burrow.sh N [N ...]: bring a Burrow (the Pi at 192.168.8N.10) up to the
# repo's HEAD from a laptop on its LAN: unlock the read-only root (reboot), git
# pull, install.sh, lock again (reboot), and wait through both reboots. Run it
# from a laptop that can ssh to the Pi; it is idempotent.
#
#   edge/burrow/tools/update-burrow.sh 1          # burrow1
#   edge/burrow/tools/update-burrow.sh 0 1        # both at home
#   BURROW_USER=pi BURROW_REPO=~/wormhole edge/burrow/tools/update-burrow.sh 2
set -euo pipefail
USER_="${BURROW_USER:-worm}"
REPO="${BURROW_REPO:-~/whs-wormhole}"
[ $# -ge 1 ] || { echo "usage: $0 N [N ...]   (N = room/Burrow number, Pi at 192.168.8N.10)"; exit 2; }

wait_for() {               # wait until ssh answers again after a reboot
  local host="$1" i
  sleep 8
  for i in $(seq 1 60); do
    if ssh -o ConnectTimeout=4 -o BatchMode=yes "$USER_@$host" true 2>/dev/null; then return 0; fi
    sleep 3
  done
  echo "  $host did not come back in 3 minutes"; return 1
}

for n in "$@"; do
  host="192.168.8$n.10"
  echo "== burrow$n at $host"
  ssh -o ConnectTimeout=6 "$USER_@$host" "cd $REPO && git rev-parse --short HEAD && (grep -q boot=overlay /proc/cmdline && echo locked || echo unlocked)" || { echo "  cannot reach $host (are you on its LAN?)"; exit 1; }
  if ssh "$USER_@$host" "grep -q boot=overlay /proc/cmdline"; then
    echo "  unlocking (reboots)..."
    ssh "$USER_@$host" "sudo $REPO/edge/burrow/burrow-unlock.sh" || true
    wait_for "$host"
  fi
  echo "  pulling + installing..."
  ssh "$USER_@$host" "cd $REPO && git pull --ff-only && sudo edge/burrow/install.sh && git rev-parse --short HEAD"
  echo "  locking (reboots)..."
  ssh "$USER_@$host" "sudo $REPO/edge/burrow/burrow-lock.sh" || true
  wait_for "$host"
  ssh "$USER_@$host" "systemctl is-active burrow && curl -s http://127.0.0.1:8080/api/status | head -c 200; echo"
  echo "== burrow$n done"
done
