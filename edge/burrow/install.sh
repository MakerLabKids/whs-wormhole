#!/bin/bash
# install.sh: (re)deploy the Burrow code into /opt/burrow and (re)start it.
# Safe to re-run after a git pull. Needs the root filesystem writable
# (burrow-unlock.sh first if the overlay is on).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 2; }
if grep -q 'boot=overlay' /proc/cmdline; then
  echo "root is read-only (overlay active). Run burrow-unlock.sh, reboot, then install."; exit 1
fi
mkdir -p /opt/burrow/www
rm -rf /opt/burrow/burrow
cp -r "$HERE/burrow" /opt/burrow/burrow
cp "$HERE/PROTOCOL.md" /opt/burrow/
if [ -d "$REPO/web/dash" ]; then
  rm -rf /opt/burrow/www && cp -r "$REPO/web/dash" /opt/burrow/www
fi
cp "$HERE/burrow-lock.sh" "$HERE/burrow-unlock.sh" "$HERE/install-cloudflared.sh" /opt/burrow/ 2>/dev/null || true
chown -R root:root /opt/burrow
chmod -R a+rX /opt/burrow
install -m 644 "$HERE/systemd/burrow.service" /etc/systemd/system/burrow.service
systemctl daemon-reload
systemctl enable burrow >/dev/null
systemctl restart burrow
sleep 2
systemctl --no-pager --lines=5 status burrow || true
echo "installed burrow $(python3 -c 'import sys; sys.path.insert(0,"/opt/burrow"); import burrow; print(burrow.VERSION)')"
