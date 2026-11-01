#!/bin/bash
# ssh-burrow.sh N [command]: SSH to burrowN from anywhere, through its Cloudflare
# tunnel (hostname ssh-burrowN.whs.makerlabkids.com, service ssh://localhost:22,
# set up in Cloudflare Zero Trust). Needs cloudflared on this machine.
set -euo pipefail
[ $# -ge 1 ] || { echo "usage: $0 N [command]"; exit 2; }
n="$1"; shift
host="ssh-burrow$n.${BURROW_DOMAIN:-whs.makerlabkids.com}"
exec ssh -o ProxyCommand="cloudflared access ssh --hostname %h" "${BURROW_USER:-worm}@$host" "$@"
