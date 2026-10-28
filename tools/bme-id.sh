#!/bin/bash
# Run the BME280/BMP280 identifier on the USB-attached Pico and keep a
# timestamped transcript (evidence for a return). Usage: tools/bme-id.sh [label]
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PICO_PORT:-/dev/host/ttyACM0}"
MP="${MPREMOTE:-$HOME/venv-tools/bin/mpremote}"
LABEL="${1:-run}"
OUT="$HERE/projects/bme280/evidence/$(date -u +%Y%m%dT%H%M%SZ)-$LABEL.txt"
mkdir -p "$(dirname "$OUT")"
{
  echo "# $(date -u)  label: $LABEL  port: $PORT"
  "$MP" connect "$PORT" run "$HERE/projects/bme280/identify.py"
} 2>&1 | tee "$OUT"
echo "saved: $OUT"
