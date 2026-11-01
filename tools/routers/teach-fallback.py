#!/usr/bin/env python3
"""teach-fallback.py HOST SSID [KEY_ENV]: give an Opal a VISIBLE network to fall back to by
itself, then put it back on the Portal's backhaul.

Why: an Opal's "auto-connect to saved networks" only rejoins networks it can see, and the
backhaul (WormHole-Core) is hidden. A Tunnel whose backhaul drops while its Pi is down sits idle
forever unless it has a visible network saved (2026-11-01: Tunnel 2, idle all evening). GL.iNet
saves a network when it joins it, so this joins SSID (the home net, or BYLD at school), waits,
then rejoins the backhaul by its BSSID. Run it from a machine that reaches HOST (the Tunnel's LAN,
or the Portal's LAN at 192.168.80.2N). Keys come from /workspace/.env (backhaul_key, and
KEY_ENV for the SSID, e.g. loki_psk; omit for an open network like BYLD); nothing is printed.

    python3 tools/routers/teach-fallback.py 192.168.82.1 Loki loki_psk
    python3 tools/routers/teach-fallback.py 192.168.82.1 BYLD
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


def call(host, obj, method, params=None, quiet=False):
    cmd = [sys.executable, os.path.join(HERE, "glinet.py"), "--host", host, "call", obj, method]
    if params is not None:
        cmd.append(json.dumps(params))
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    try:
        return json.loads(out.stdout)
    except ValueError:
        return {}


def state(host):
    s = call(host, "repeater", "get_status")
    return s.get("state_s"), s.get("ssid")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    host, ssid = sys.argv[1], sys.argv[2]
    key = env_value(sys.argv[3]) if len(sys.argv) > 3 else None
    bk = env_value("backhaul_key")
    if not bk:
        print("no backhaul_key in .env")
        return 1
    call(host, "repeater", "set_config", {"auto": True})
    params = {"ssid": ssid, "remember": True}
    if key:
        params["key"] = key
    call(host, "repeater", "connect", params)
    time.sleep(20)
    print("after joining %s: %s" % (ssid, state(host)))
    call(host, "repeater", "connect", dict(BACKHAUL, key=bk))
    time.sleep(20)
    st = state(host)
    print("after rejoining the backhaul: %s" % (st,))
    return 0 if st == ("connected", "WormHole-Core") else 1


if __name__ == "__main__":
    sys.exit(main())
