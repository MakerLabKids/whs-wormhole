#!/bin/bash
# Admin people screens: add a teacher; a class from a CSV makes a team per bin and prints a slip per student.
#   tools/e2e/people-e2e.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
TMP="$(mktemp -d)"; PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; pkill -f -- "--persist-to $TMP/state" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT
cd "$REPO/cloud/surface"
npx wrangler d1 execute wormhole --local -c wrangler.e2e.jsonc --persist-to "$TMP/state" --file schema.sql >/dev/null
npx wrangler dev -c wrangler.e2e.jsonc --persist-to "$TMP/state" --port 8787 > "$TMP/wrangler.log" 2>&1 & PIDS+=($!)
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8787/api/me && break; sleep 1; done
cd "$HERE" && SHOTS="$HERE/shots" node people-e2e.mjs || { echo "--- wrangler log"; tail -20 "$TMP/wrangler.log"; exit 1; }
