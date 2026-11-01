#!/bin/bash
# self-update.sh: move this Burrow to the commit named in the data dir's
# update-request.json (written by the service when the admin clicked Update).
# Download the commit's tarball from GitHub, verify its sha256 against what
# the Surface computed, unpack it over the checkout, run install.sh (which
# restarts the service), and report. Run by burrow-update.service as root,
# started by burrow-update.path when the request file appears. Never installs
# a tarball whose hash does not match.
set -euo pipefail
DATA="${BURROW_DATA:-/data/burrow}"
REQ="$DATA/update-request.json"
LOG="$DATA/update.log"
CHECKOUT="${BURROW_CHECKOUT:-/home/worm/wormhole}"
[ -f "$REQ" ] || exit 0
say() { echo "$(date -Is) $*" | tee -a "$LOG"; }
read -r BUILD SHA URL < <(python3 -c "import json; r=json.load(open('$REQ')); print(r['build'], r['sha256'], r['url'])")
say "update to $BUILD from $URL"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
if ! curl -fsSL --max-time 300 -o "$work/src.tgz" "$URL"; then
  say "download failed"; mv "$REQ" "$REQ.failed"; exit 1
fi
got=$(sha256sum "$work/src.tgz" | cut -d' ' -f1)
if [ "$got" != "$SHA" ]; then
  say "REFUSED: sha256 $got does not match $SHA"; mv "$REQ" "$REQ.failed"; exit 1
fi
mkdir -p "$work/tree"
tar xzf "$work/src.tgz" -C "$work/tree" --strip-components=1
[ -f "$work/tree/edge/burrow/install.sh" ] || { say "not a repo tarball"; mv "$REQ" "$REQ.failed"; exit 1; }
mkdir -p "$CHECKOUT"
for d in edge tools web; do
  [ -d "$work/tree/$d" ] || continue
  rm -rf "$CHECKOUT/$d"
  cp -r "$work/tree/$d" "$CHECKOUT/$d"
done
echo "$BUILD $(date -Is)" > "$CHECKOUT/edge/burrow/BUILD"
chown -R worm:worm "$CHECKOUT" 2>/dev/null || true
rm -f "$REQ"
say "installing $BUILD"
if bash "$CHECKOUT/edge/burrow/install.sh" >>"$LOG" 2>&1; then
  say "installed $BUILD"
else
  say "install.sh failed for $BUILD (see above)"; exit 1
fi
