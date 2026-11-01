#!/bin/bash
# fault-test.sh: simulate a failure on a Burrow without touching a cable, always self-undoing.
# Run from a machine on the Portal's LAN (the Pis at 192.168.80.10 / .2N).
#
#   edge/burrow/tools/fault-test.sh cut-eth N [minutes]   # burrowN loses its Opal for that long (default 14)
#   edge/burrow/tools/fault-test.sh watch N [minutes]      # print every minute: where burrowN is, Surface last-heard
#   edge/burrow/tools/fault-test.sh ok N                   # it came back: cancel the safety reboot, show the watchdog's log
#
# cut-eth: arms `nmcli device connect eth0` on the Pi for +minutes FIRST, then disconnects eth0.
# Expected: within ~4 min (watchdog every 2 min + WIFI_AFTER_S 90 s: on Wi-Fi 2-4 min after the cut) the Pi is on its own Wi-Fi,
# shows up as a client on some other Opal, and keeps reaching the Surface; when eth0 returns the
# watchdog drops the Wi-Fi again ("cable healthy again").
set -euo pipefail
cmd="${1:-}"; n="${2:?burrow number}"; mins="${3:-14}"
host=$([ "$n" = 0 ] && echo 192.168.80.10 || echo "192.168.80.2$n")
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
case "$cmd" in
  cut-eth)
    # one transient unit does cut, wait, restore; a second, independent one reboots the Pi 4 min
    # after the planned restore unless `fault-test.sh ok N` cancels it (a failed restore stranded
    # burrow3 on 2026-11-01 and needed a hand on the power plug)
    ssh -o ConnectTimeout=8 -o BatchMode=yes "worm@$host" "
      sudo systemd-run --quiet --on-active=$((mins + 4))min --unit=faulttest-reboot /bin/systemctl reboot &&
      echo \"safety reboot armed for +$((mins + 4)) min (cancel: fault-test.sh ok $n)\" &&
      sudo systemd-run --quiet --unit=faulttest-cut /bin/sh -c 'sleep 3; nmcli device disconnect eth0; sleep $((mins * 60)); nmcli device connect eth0 || ip link set eth0 up' &&
      echo \"eth0 cut in 3 s at \$(date +%H:%M:%S), back at +$mins min\"" || true
    ;;
  ok)
    ssh -o ConnectTimeout=8 -o BatchMode=yes "worm@$host" "sudo systemctl stop faulttest-reboot.timer faulttest-reboot.service 2>/dev/null; echo safety reboot cancelled; tail -20 /data/burrow/watchdog-events.log 2>/dev/null"
    ;;
  watch)
    wlan=$(ssh -o ConnectTimeout=8 -o BatchMode=yes "worm@$host" cat /sys/class/net/wlan0/address 2>/dev/null || true)
    for k in $(seq 1 "$mins"); do
      where=$(python3 "$REPO/tools/routers/glinet.py" --host 192.168.80.1 call clients get_list 2>/dev/null | python3 -c "
import sys, json
for c in json.load(sys.stdin).get('clients', []):
    if c.get('mac', '').lower() == '${wlan,,}' and c.get('online'): print('on the Portal over Wi-Fi at', c.get('ip'))" 2>/dev/null)
      seen=$(curl -s --max-time 8 https://whs.makerlabkids.com/api/public/now | python3 -c "
import sys, json, time; j = json.load(sys.stdin); print('Surface heard burrow$n %ds ago' % (time.time() - (j['edges'].get('burrow$n', {}).get('ts') or 0)))" 2>/dev/null)
      echo "$(date +%H:%M:%S) | ${where:-not on the Portal over Wi-Fi} | $seen"
      sleep 60
    done
    ;;
  *) sed -n 2,13p "$0"; exit 2 ;;
esac
