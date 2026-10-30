#!/bin/bash
# Measure one known distance with ROI 16, 8 and 4 and print the error of each.
# Usage: tools/laser-sweep.sh <truth_mm> <label>
# Env: OFF (offset mm, default 0), X16/X8/X4 (crosstalk kcps per ROI, default 0).
# Example: OFF=17 X16=1818 X8=1328 X4=0 tools/laser-sweep.sh 500 wall-50cm
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
T="$1"; L="$2"
declare -A XT=([16]=${X16:-0} [8]=${X8:-0} [4]=${X4:-0})
printf "%-6s %-8s %-10s %-9s %-7s %-8s %s\n" roi xtalk median err valid signal bad
for roi in 16 8 4; do
  full=$("$HERE/tools/laser-probe.sh" 6 $roi "$L-roi$roi" ${XT[$roi]} 0 ${OFF:-0} 0)
  out=$(echo "$full" | grep "^DONE")
  [ -z "$out" ] && { echo "$full" | grep -E "Error|OSError" | tail -1; break; }
  med=$(echo "$out" | sed -n 's/.*median \([0-9-]*\) .*/\1/p')
  ok=$(echo "$out" | sed -n 's/.*n=\([0-9]*\) ok=\([0-9]*\).*/\2\/\1/p')
  sig=$(echo "$out" | sed -n 's/.*signal \([0-9.]*\) .*/\1/p')
  bad=$(echo "$out" | sed -n 's/.*bad=\(.*\)$/\1/p')
  if [ "$med" != "-" ] && [ -n "$med" ]; then err=$((med - T)); else err="n/a"; fi
  printf "%-6s %-8s %-10s %-9s %-7s %-8s %s\n" "$roi" "${XT[$roi]}" "$med" "$err" "$ok" "$sig" "$bad"
  sleep 1
done
