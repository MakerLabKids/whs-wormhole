#!/bin/bash
# The whole chain on one laptop: real Worker (wrangler dev, local D1/R2) +
# real Burrow uploading to it + 12 fake Bins + the dashboard driven by a
# headless browser. 26 checks. Takes about two minutes (castings must seal).
#
#   cd tools/e2e && npm i && npx playwright install chromium     # once
#   tools/e2e/run.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
TMP="$(mktemp -d)"; PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; pkill -f "wrangler dev -c wrangler.e2e.jsonc" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT
cd "$REPO/cloud/surface"
[ -d node_modules ] || npm i
rm -rf .wrangler/state/v3/d1 .wrangler/state/v3/r2 2>/dev/null || true
npx wrangler d1 execute wormhole --local -c wrangler.e2e.jsonc --file schema.sql >/dev/null
npx wrangler dev -c wrangler.e2e.jsonc --port 8787 > "$TMP/wrangler.log" 2>&1 & PIDS+=($!)
cat > "$TMP/burrow.json" <<J
{"edge":"burrow1","room":1,"listen":"127.0.0.1","port":8213,"data_dir":"$TMP/data","www_dir":"$REPO/web/dash",
 "peers":{},"cloud":{"url":"http://127.0.0.1:8787","token_file":"$TMP/token","live_key_file":"$TMP/livekey","every_s":15},
 "seal_minutes":1,"seal_grace_s":5,"sweep":{"enabled":false}}
J
echo tok1 > "$TMP/token"; echo local-live-key > "$TMP/livekey"
(cd "$REPO/edge/burrow" && BURROW_CONFIG="$TMP/burrow.json" python3 -m burrow > "$TMP/burrow.log" 2>&1) & PIDS+=($!)
python3 "$HERE/liveproxy.py" > /dev/null 2>&1 & PIDS+=($!)
(cd "$REPO/edge/burrow" && python3 tools/simbins.py --edge http://127.0.0.1:8213 --n 12 --every 10 > /dev/null 2>&1) & PIDS+=($!)
for i in $(seq 1 30); do curl -s -o /dev/null http://127.0.0.1:8787/api/me && break; sleep 1; done
cd "$HERE" && node e2e.mjs
