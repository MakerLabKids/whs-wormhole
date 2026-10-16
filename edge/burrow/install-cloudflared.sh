#!/bin/bash
# install-cloudflared.sh <TUNNEL_TOKEN>: the Burrow's outbound-only live link.
# HTTP/2 over TCP 443 only, so it works wherever a browser works.
set -euo pipefail
TOKEN="${1:-}"; [ -n "$TOKEN" ] || { echo "usage: sudo $0 <tunnel token from the Cloudflare dashboard>"; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 2; }
if ! command -v cloudflared >/dev/null; then
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
  # 'any' is Cloudflare's distribution-independent suite; use 'trixie' if it exists when you read this.
  echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
    > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -qq && apt-get install -y -qq cloudflared >/dev/null
fi
systemctl stop cloudflared 2>/dev/null || true
cloudflared service uninstall 2>/dev/null || true
cloudflared service install "$TOKEN"
mkdir -p /etc/systemd/system/cloudflared.service.d
cat > /etc/systemd/system/cloudflared.service.d/override.conf <<'OVR'
[Service]
ExecStart=
ExecStart=/usr/bin/cloudflared --no-autoupdate --protocol http2 tunnel run
Restart=always
RestartSec=10
OVR
systemctl daemon-reload
systemctl enable --now cloudflared
sleep 3
systemctl --no-pager --lines=8 status cloudflared || true
