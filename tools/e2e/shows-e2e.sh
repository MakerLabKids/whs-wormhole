#!/bin/bash
# Shows phase 2, the whole chain on one machine: real Worker (wrangler dev, local D1) + a real
# Burrow + one fake Bin + the website driven by headless Chromium: add a show and a playlist on the
# bin's page -> the Burrow fetches the file -> the Bin's push reply carries it -> the Bin fetches it
# from the Burrow -> reports shows_rev -> the page says "On the bin". About a minute.
#   tools/e2e/shows-e2e.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
TMP="$(mktemp -d)"; PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; rm -rf "$TMP"; }
trap cleanup EXIT
cd "$REPO/cloud/surface"
rm -rf .wrangler/state/v3/d1 .wrangler/state/v3/r2 2>/dev/null || true
npx wrangler d1 execute wormhole --local -c wrangler.e2e.jsonc --file schema.sql >/dev/null
npx wrangler dev -c wrangler.e2e.jsonc --port 8787 > "$TMP/wrangler.log" 2>&1 & PIDS+=($!)
cat > "$TMP/burrow.json" <<J
{"edge":"burrow1","room":1,"listen":"127.0.0.1","port":8214,"data_dir":"$TMP/data","www_dir":"$REPO/web/dash",
 "peers":{},"cloud":{"url":"http://127.0.0.1:8787","token_file":"$TMP/token","live_key_file":"$TMP/livekey","every_s":5},
 "seal_minutes":1,"seal_grace_s":5,"sweep":{"enabled":false}}
J
echo tok1 > "$TMP/token"; echo local-live-key > "$TMP/livekey"
(cd "$REPO/edge/burrow" && BURROW_CONFIG="$TMP/burrow.json" python3 -m burrow > "$TMP/burrow.log" 2>&1) & PIDS+=($!)
for i in $(seq 1 40); do curl -s -o /dev/null http://127.0.0.1:8787/api/me && curl -s -o /dev/null http://127.0.0.1:8214/health && break; sleep 1; done
cd "$HERE" && SHOTS="$HERE/shots" node shows-e2e.mjs || { echo "--- burrow log"; tail -20 "$TMP/burrow.log"; echo "--- wrangler log"; tail -20 "$TMP/wrangler.log"; exit 1; }
