#!/usr/bin/env bash
# Print every secret the Surface needs, plus the three per-Burrow token files.
# Nothing is written anywhere: copy what you need. Run once; keep the output safe.
#
#   tools/gen-secrets.sh            # print everything
#   tools/gen-secrets.sh --put      # also run `wrangler secret put` for each
set -euo pipefail

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

# ---- Per-Burrow token files (the Burrow's cloud.token_file; one line, no newline needed) ----
# burrow1: /data/burrow/cloud.token
$T1
# burrow2: /data/burrow/cloud.token
$T2
# burrow3: /data/burrow/cloud.token
$T3

# ---- Each Burrow's cloudflared ingress must require this header on /live ----
# X-Burrow-Key: $LIVE_KEY
EOF

if [ "${1:-}" = "--put" ]; then
  cd "$(dirname "$0")/.."
  printf '%s' "$SESSION_SECRET"  | npx wrangler secret put SESSION_SECRET
  printf '%s' "$LIVE_KEY"        | npx wrangler secret put LIVE_KEY
  printf '%s' "$ADMIN_BOOTSTRAP" | npx wrangler secret put ADMIN_BOOTSTRAP
  printf '%s' "$EDGE_TOKENS"     | npx wrangler secret put EDGE_TOKENS
fi
