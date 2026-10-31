#!/bin/bash
# Run the Pico firmware (lib/picolab.py) under the MicroPython UNIX port with
# stubbed machine/network modules and a fake clock, against a REAL Burrow.
#   sudo apt-get install micropython     (Ubuntu/Debian)
#   tools/picotest/run.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
command -v micropython >/dev/null || { echo "need the micropython unix port (apt install micropython)"; exit 2; }
TMP="$(mktemp -d)"; trap 'kill $BPID 2>/dev/null; rm -rf "$TMP"' EXIT
mkdir -p "$TMP/www"; echo '<h1>dash</h1>' > "$TMP/www/index.html"
cat > "$TMP/burrow.json" <<J
{"edge":"burrow1","room":1,"listen":"127.0.0.1","port":8211,"data_dir":"$TMP/data","www_dir":"$TMP/www",
 "peers":{},"cloud":{"url":"","token_file":"/nonexistent","live_key_file":"/nonexistent"},"sweep":{"enabled":false}}
J
(cd "$REPO/edge/burrow" && BURROW_CONFIG="$TMP/burrow.json" python3 -m burrow > "$TMP/burrow.log" 2>&1) & BPID=$!
sleep 1.5
cp "$REPO/lib/picolab.py" "$HERE/board/picolab.py"
cd "$HERE/board" && micropython harness.py || { echo "---- burrow.log (tail) ----"; tail -25 "$TMP/burrow.log"; rm -f "$HERE/board/picolab.py"; exit 1; }
rm -f "$HERE/board/picolab.py"
