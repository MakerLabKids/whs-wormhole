#!/bin/bash
# Run projects/distance-vl53l1x/probe.py on the USB Pico with the constants
# filled in, and keep a transcript.
# Usage: tools/laser-probe.sh [seconds] [roi] [label] [xtalk_kcps] [calibrate_mm]
#   roi: 16 (or "full"), 8, 4.  xtalk: compensation in kcps (0 = off).
#   calibrate_mm: >0 runs calibrate_xtalk against a wall at that distance first.
#   Transcripts: ~/.cache/wormhole-bench/
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PICO_PORT:-/dev/host/ttyACM0}"
MP="${MPREMOTE:-$HOME/venv-tools/bin/mpremote}"
SECS="${1:-8}"; ROI="${2:-16}"; LABEL="${3:-probe}"; XT="${4:-0}"; CAL="${5:-0}"
[ "$ROI" = full ] && ROI=16
OUTDIR="$HOME/.cache/wormhole-bench"; mkdir -p "$OUTDIR"
OUT="$OUTDIR/$(date -u +%Y%m%dT%H%M%SZ)-$LABEL.txt"
TMP="$(mktemp --suffix=.py)"; trap 'rm -f "$TMP"' EXIT
sed -e "s/^SECONDS = .*/SECONDS = $SECS/" -e "s/^ROI = .*/ROI = $ROI/" -e "s/^LABEL = .*/LABEL = \"$LABEL\"/" \
    -e "s/^XTALK = .*/XTALK = $XT/" -e "s/^CALIBRATE_MM = .*/CALIBRATE_MM = $CAL/" \
  "$HERE/projects/distance-vl53l1x/probe.py" > "$TMP"
sleep 1   # a fresh init right after a previous run's stop can catch the chip mid-reset
"$MP" connect "$PORT" mount "$HERE/lib" run "$TMP" 2>&1 | grep -v 'mounted at' | tee "$OUT"
echo "saved: $OUT"
