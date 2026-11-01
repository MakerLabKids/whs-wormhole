#!/usr/bin/env python3
"""join-backhaul.py N: tell Tunnel N's Opal (192.168.8N.1) to join the Portal's
hidden 5 GHz backhaul (WormHole-Core) right now, the way the Pi's watchdog
does every two minutes, and switch on the Opal's own auto-connect to saved
networks so it never needs telling again. For the evening when the Pi is
down and the Tunnel flashes white: run it from any laptop on that Tunnel's LAN.

The backhaul key and the router admin password come from the repo's .env
(backhaul_key, router_admin); nothing is printed.

    python3 tools/routers/join-backhaul.py 2
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
BACKHAUL = {"ssid": "WormHole-Core", "bssid": "94:83:c4:84:d2:0c", "device": "radio1", "band": "5g", "encryption": "sae",
            "remember": True}   # without it GL.iNet saves nothing and auto-connect has nothing to rejoin


def env_value(key):
  try:
    with open(os.path.join(REPO, ".env")) as f:
      for line in f:
        if line.startswith(key + "="):
          return line.split("=", 1)[1].strip().strip("'\"")
  except OSError:
    pass
  return None


def call(host, obj, method, params=None):
  cmd = [sys.executable, os.path.join(HERE, "glinet.py"), "--host", host, "call", obj, method]
  if params is not None:
    cmd.append(json.dumps(params))
  out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
  if out.returncode != 0:
    raise SystemExit("router call failed: " + (out.stderr or out.stdout)[:200].replace(env_value("backhaul_key") or "\0", "***"))
  try:
    return json.loads(out.stdout)
  except ValueError:
    return out.stdout


def main():
  if len(sys.argv) != 2 or not sys.argv[1].isdigit():
    print(__doc__)
    return 2
  n = int(sys.argv[1])
  host = "192.168.8%d.1" % n
  key = env_value("backhaul_key")
  if not key:
    print("no backhaul_key in .env")
    return 1
  rc = call(host, "repeater", "get_config")
  if isinstance(rc, dict) and "auto" in rc and not rc.get("auto"):
    call(host, "repeater", "set_config", {"auto": True})
    print("Tunnel %d: auto-connect to saved networks was OFF; switched on (it rejoins by itself from now on)" % n)
  st = call(host, "repeater", "get_status")
  if isinstance(st, dict) and st.get("bssid", "").lower() == BACKHAUL["bssid"] and (st.get("wpa_status") or {}).get("wpa_state") == "COMPLETED":
    print("Tunnel %d is already on the backhaul" % n)
    return 0
  print("Tunnel %d: joining WormHole-Core (hidden: dialed by name and BSSID, and saved)..." % n)
  call(host, "repeater", "connect", dict(BACKHAUL, key=key))
  for _ in range(8):
    time.sleep(5)
    st = call(host, "repeater", "get_status")
    w = (st.get("wpa_status") or {}) if isinstance(st, dict) else {}
    if w.get("wpa_state") == "COMPLETED":
      print("joined: %s on %s" % (w.get("bssid"), w.get("freq") or "5 GHz"))
      return 0
  print("not joined yet (%s); the Portal may still be booting" % (st.get("state_s") if isinstance(st, dict) else st))
  return 1


if __name__ == "__main__":
  sys.exit(main())
