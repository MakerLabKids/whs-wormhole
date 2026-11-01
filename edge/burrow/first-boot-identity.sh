#!/bin/bash
# first-boot-identity.sh: runs before the Burrow service on every boot. If the
# boot partition carries burrow-identity.json (dropped there by clone-card.sh),
# become that Burrow: edge name, room, static address, hostname, tokens if
# given; wipe the cloned /data; remove the file. Idempotent and silent when
# there is no file. Installed as burrow-identity.service (Before=burrow).
set -euo pipefail
F=/boot/firmware/burrow-identity.json
MARK=/etc/burrow/needs-identity          # set by clone-card.sh write: this card is a fresh Pi
py=/usr/bin/python3
if [ ! -f "$F" ] && [ -f "$MARK" ]; then
  # Enrol: the room comes from the subnet our Opal hands out (192.168.8<room>.x), the name,
  # upload token and tunnel token from the Surface (POST /v1/edge/enrol with the fleet secret).
  for i in $(seq 1 60); do nmcli -t general status >/dev/null 2>&1 && break; sleep 2; done
  con=""
  for i in $(seq 1 30); do
    con=$(nmcli -t -f NAME,DEVICE connection show 2>/dev/null | awk -F: '$2=="eth0"{print $1}' | head -1 || true)
    [ -n "$con" ] && break; sleep 2
  done
  [ -n "$con" ] || { echo "enrol: no NetworkManager connection on eth0; will try next boot"; exit 0; }
  nmcli connection modify "$con" ipv4.method auto ipv4.addresses "" ipv4.gateway "" ipv4.dns "" || true
  nmcli connection up "$con" >/dev/null 2>&1 || true
  # the room must come from the Opal's DHCP, never from the donor's static .10 address: a clone
  # that still had 192.168.80.10 would have enrolled as burrow0 and taken its tunnel
  [ "$(nmcli -g ipv4.method connection show "$con" 2>/dev/null)" = auto ] || { echo "enrol: eth0 did not switch to DHCP; will try next boot"; exit 0; }
  room=""
  for i in $(seq 1 60); do
    ip4=$(ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1 | head -1)
    case "$ip4" in 192.168.8[0-9].10) ;; 192.168.8[0-9].*) room=$(echo "$ip4" | cut -d. -f3 | sed 's/^8//'); break ;; esac
    sleep 5
  done
  [ -n "$room" ] || { echo "enrol: no 192.168.8N.x address from the Opal after 5 min; will try next boot"; exit 0; }
  serial=$(tr -d '\0' < /sys/firmware/devicetree/base/serial-number 2>/dev/null || awk '/^Serial/{print $3}' /proc/cpuinfo)
  url=$($py -c "import json; print(json.load(open('/etc/burrow/burrow.json'))['cloud']['url'].rstrip('/'))" 2>/dev/null || echo https://whs.makerlabkids.com)
  secret=$(cat /etc/burrow/enrol.secret 2>/dev/null || true)
  [ -n "$secret" ] || { echo "enrol: no /etc/burrow/enrol.secret on this card"; exit 0; }
  eth=$(cat /sys/class/net/eth0/address 2>/dev/null || true); wlan=$(cat /sys/class/net/wlan0/address 2>/dev/null || true)
  body=$($py -c "import json,sys; print(json.dumps({'secret': sys.argv[1], 'serial': sys.argv[2], 'room': int(sys.argv[3]), 'eth_mac': sys.argv[4], 'wlan_mac': sys.argv[5]}))" "$secret" "$serial" "$room" "$eth" "$wlan")
  reply=""
  for i in $(seq 1 30); do
    reply=$(curl -fsS --max-time 20 -H 'content-type: application/json' -d "$body" "$url/v1/edge/enrol" 2>/dev/null) && break
    sleep 10
  done
  [ -n "$reply" ] || { echo "enrol: the Surface did not answer; will try next boot"; exit 0; }
  F=/run/burrow-identity.json
  $py -c "import json,sys; r=json.loads(sys.argv[1]); json.dump({'edge': r['edge'], 'room': r['room'], 'cloud_token': r['token'], 'tunnel_token': r.get('tunnel_token')}, open(sys.argv[2], 'w'))" "$reply" "$F"
  echo "enrolled as $($py -c "import json; print(json.load(open('$F'))['edge'])") (room $room, serial $serial)"
fi
[ -f "$F" ] || exit 0
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
    r = int(room) if room != "" else int(edge[-1])
    tc["host"] = "192.168.8%s.1" % r
    ups = tc.get("upstreams") or []
    if r == 0:
        # room 0 is cabled to the Portal, which IS the backhaul AP: no WormHole-Core entry
        tc["upstreams"] = [u for u in ups if u.get("ssid") != "WormHole-Core"]
    elif not any(u.get("ssid") == "WormHole-Core" for u in ups):
        # the donor was burrow0 (no backhaul entry, no backhaul key on its card): this Tunnel
        # would fall back to BYLD/Loki instead of the Portal. Image a room 1-3 Pi, or fix with
        # render_tunnel_json.py --room N (burrow2, 2026-11-01).
        print("WARNING: tunnel.json has no WormHole-Core upstream (cloned from burrow0?)")
    json.dump(tc, open(t, "w"), indent=2)
PY
hostnamectl set-hostname "$edge" 2>/dev/null || echo "$edge" > /etc/hostname
# the donor's name in /etc/hosts makes every sudo complain "unable to resolve host"
if grep -q '^127\.0\.1\.1' /etc/hosts; then sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$edge/" /etc/hosts; else printf '127.0.1.1\t%s\n' "$edge" >> /etc/hosts; fi
# the cable address: .10 on this room's Opal
con=$(nmcli -t -f NAME,DEVICE connection show | awk -F: '$2=="eth0"{print $1}' | head -1)
if [ -n "$con" ] && [ -n "$room" ]; then
  nmcli connection modify "$con" ipv4.method manual ipv4.addresses "192.168.8$room.10/24" ipv4.gateway "192.168.8$room.1" ipv4.dns "192.168.8$room.1" || true
fi
# a clone carries the donor's data: start clean
rm -rf /data/burrow/* 2>/dev/null || true
# clone-card.sh makes /data a fresh root-owned ext4: the service (User=burrow) cannot create its
# own folder there (burrow2, 2026-11-01: PermissionError on /data/burrow, restart loop)
install -d -m 755 -o burrow -g burrow /data/burrow 2>/dev/null || install -d -m 755 /data/burrow
rm -f "$F" "$MARK"
sync
echo "identity applied; rebooting into it"
systemctl reboot
