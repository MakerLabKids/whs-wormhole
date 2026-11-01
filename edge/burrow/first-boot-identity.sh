#!/bin/bash
# first-boot-identity.sh: runs before the Burrow service on every boot. If the
# boot partition carries burrow-identity.json (dropped there by clone-card.sh),
# become that Burrow: edge name, room, static address, hostname, tokens if
# given; wipe the cloned /data; remove the file. Idempotent and silent when
# there is no file. Installed as burrow-identity.service (Before=burrow).
set -euo pipefail
F=/boot/firmware/burrow-identity.json
[ -f "$F" ] || exit 0
py=/usr/bin/python3
edge=$($py -c "import json; print(json.load(open('$F'))['edge'])")
room=$($py -c "import json; print(json.load(open('$F')).get('room', ''))")
n="${edge#burrow}"
echo "first boot as $edge (room $room)"
mount -o remount,rw /boot/firmware 2>/dev/null || true
$py - "$F" "$edge" "$room" <<'PY'
import json, os, sys
f, edge, room = sys.argv[1], sys.argv[2], sys.argv[3]
ident = json.load(open(f))
p = "/etc/burrow/burrow.json"
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg["edge"] = edge
if room != "": cfg["room"] = int(room)
# peers: every other Burrow by its Tunnel's Portal-side forward; the local one is .10
peers = {}
for k in range(4):
    other = "burrow%d" % k
    if other != edge:
        peers[other] = {"url": "http://192.168.80.%d:8080" % (10 if k == 0 else 20 + k)}
cfg["peers"] = peers
json.dump(cfg, open(p, "w"), indent=2)
for key, path in (("cloud_token", "/etc/burrow/cloud.token"), ("tunnel_token", "/etc/cloudflared/token")):
    if ident.get(key):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as out: out.write(ident[key])
        os.chmod(path, 0o600)
t = "/etc/burrow/tunnel.json"
if os.path.exists(t):
    tc = json.load(open(t))
    tc["host"] = "192.168.8%s.1" % (int(room) if room != "" else int(edge[-1]))
    json.dump(tc, open(t, "w"), indent=2)
PY
hostnamectl set-hostname "$edge" 2>/dev/null || echo "$edge" > /etc/hostname
# the cable address: .10 on this room's Opal
con=$(nmcli -t -f NAME,DEVICE connection show | awk -F: '$2=="eth0"{print $1}' | head -1)
if [ -n "$con" ] && [ -n "$room" ]; then
  nmcli connection modify "$con" ipv4.method manual ipv4.addresses "192.168.8$room.10/24" ipv4.gateway "192.168.8$room.1" ipv4.dns "192.168.8$room.1" || true
fi
# a clone carries the donor's data: start clean
rm -rf /data/burrow/* 2>/dev/null || true
rm -f "$F"
sync
echo "identity applied; rebooting into it"
systemctl reboot
