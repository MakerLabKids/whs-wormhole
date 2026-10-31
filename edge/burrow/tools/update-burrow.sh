#!/bin/bash
# update-burrow.sh N [N ...]: bring a Burrow (the Pi at 192.168.8N.10) up to this
# working tree: copy edge/, tools/ and web/ over ssh into ~/wormhole on the Pi
# (the Pis have no git; that folder is a plain copy), run install.sh there, and
# if the root was locked (read-only overlay) unlock first and lock after, waiting
# through both reboots. Run it from a machine on the Pi's LAN with ssh access.
#
#   edge/burrow/tools/update-burrow.sh 1          # burrow1
#   edge/burrow/tools/update-burrow.sh 0 1        # both at home
#   BURROW_USER=pi edge/burrow/tools/update-burrow.sh 2
set -euo pipefail
USER_="${BURROW_USER:-worm}"
DEST="${BURROW_DIR:-wormhole}"            # under the user's home on the Pi
HERE="$(cd "$(dirname "$0")/../../.." && pwd)"
[ $# -ge 1 ] || { echo "usage: $0 N [N ...]   (N = room/Burrow number, Pi at 192.168.8N.10)"; exit 2; }
SSH="ssh -o ConnectTimeout=6 -o BatchMode=yes"

wait_for() {               # wait until ssh answers again after a reboot
  local host="$1" i
  sleep 8
  for i in $(seq 1 60); do
    if $SSH -o ConnectTimeout=4 "$USER_@$host" true 2>/dev/null; then return 0; fi
    sleep 3
  done
  echo "  $host did not come back in 3 minutes"; return 1
}

for n in "$@"; do
  host="192.168.8$n.10"
  echo "== burrow$n at $host"
  locked=$($SSH "$USER_@$host" "grep -q boot=overlay /proc/cmdline && echo yes || echo no") || { echo "  cannot reach $host (are you on its LAN?)"; exit 1; }
  if [ "$locked" = yes ]; then
    echo "  unlocking (reboots)..."
    $SSH "$USER_@$host" "sudo ~/$DEST/edge/burrow/burrow-unlock.sh" || true
    wait_for "$host"
  fi
  echo "  copying edge/ tools/ web/ and installing..."
  (cd "$HERE" && tar czf - --exclude=__pycache__ --exclude=node_modules --exclude=tools/e2e edge tools web) |
    $SSH "$USER_@$host" "mkdir -p ~/$DEST && cd ~/$DEST && tar xzf - && sudo edge/burrow/install.sh 2>&1 | tail -2"
  if [ "$locked" = yes ]; then
    echo "  locking (reboots)..."
    $SSH "$USER_@$host" "sudo ~/$DEST/edge/burrow/burrow-lock.sh" || true
    wait_for "$host"
  fi
  $SSH "$USER_@$host" "sleep 2; systemctl is-active burrow; curl -s http://127.0.0.1:8080/api/status | head -c 160; echo"
  echo "== burrow$n done"
done
