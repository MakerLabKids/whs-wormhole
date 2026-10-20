#!/usr/bin/env bash
# Print every secret the Surface needs, plus the three per-Burrow token files.
# Nothing is written anywhere: copy what you need. Run once; keep the output safe.
#
#   tools/gen-secrets.sh                  # print everything
#   tools/gen-secrets.sh --put            # also run `wrangler secret put` for each
#   tools/gen-secrets.sh --put-from FILE  # push the four NAME=value lines from a saved output
set -euo pipefail

put_all() {  # $1..$4 = SESSION_SECRET LIVE_KEY ADMIN_BOOTSTRAP EDGE_TOKENS
  cd "$(dirname "$0")/.."
  printf '%s' "$1" | npx wrangler secret put SESSION_SECRET
  printf '%s' "$2" | npx wrangler secret put LIVE_KEY
  printf '%s' "$3" | npx wrangler secret put ADMIN_BOOTSTRAP
  printf '%s' "$4" | npx wrangler secret put EDGE_TOKENS
  echo; echo "secrets now on the Worker:"; npx wrangler secret list
}

if [ "${1:-}" = "--put-from" ]; then
  F="${2:?usage: $0 --put-from FILE}"
  val() { grep -m1 "^$1=" "$F" | cut -d= -f2- | tr -d '\r\n'; }
  for k in SESSION_SECRET LIVE_KEY ADMIN_BOOTSTRAP EDGE_TOKENS; do
    [ -n "$(val "$k")" ] || { echo "no $k= line in $F" >&2; exit 1; }
  done
  put_all "$(val SESSION_SECRET)" "$(val LIVE_KEY)" "$(val ADMIN_BOOTSTRAP)" "$(val EDGE_TOKENS)"
  exit 0
fi

rand() { openssl rand -hex "$1"; }

SESSION_SECRET=$(rand 32)
LIVE_KEY=$(rand 32)
ADMIN_BOOTSTRAP=$(rand 16)
T1=$(rand 24); T2=$(rand 24); T3=$(rand 24)
EDGE_TOKENS=$(printf '{"burrow1":"%s","burrow2":"%s","burrow3":"%s"}' "$T1" "$T2" "$T3")

cat <<EOF
# ---- Worker secrets (npx wrangler secret put <NAME>, paste the value) ----
SESSION_SECRET=$SESSION_SECRET
LIVE_KEY=$LIVE_KEY
ADMIN_BOOTSTRAP=$ADMIN_BOOTSTRAP
EDGE_TOKENS=$EDGE_TOKENS

# ---- Per-Burrow token files (/etc/burrow/cloud.token on each Pi; one line) ----
# burrow1: /etc/burrow/cloud.token
$T1
# burrow2: /etc/burrow/cloud.token
$T2
# burrow3: /etc/burrow/cloud.token
$T3

# ---- The same LIVE_KEY goes in /etc/burrow/live.key on every Pi; the Burrow ----
# ---- rejects tunnel requests that do not carry X-Burrow-Key: <this value>  ----
$LIVE_KEY
EOF

if [ "${1:-}" = "--put" ]; then
  put_all "$SESSION_SECRET" "$LIVE_KEY" "$ADMIN_BOOTSTRAP" "$EDGE_TOKENS" >&2
fi
