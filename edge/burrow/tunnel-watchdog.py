#!/usr/bin/env python3
"""tunnel-watchdog: keep this room's Tunnel (GL.iNet Opal) joined to the Portal.

The Opal's repeater drops to "idle" when the Portal's radios restart and does
not retry (seen 2026-10-16 and 2026-10-19). The Burrow sits next to its Tunnel,
so every run (systemd timer, 2 min) it asks the Tunnel for its repeater state
and re-sends the join when it is not connected. Config: /etc/burrow/tunnel.json
  {"host": "192.168.81.1", "password": "<router admin>",
   "ssid": "WormHole-Core", "key": "<backhaul>", "bssid": "94:83:c4:84:d2:0c",
   "device": "radio1", "band": "5g", "encryption": "psk2"}
Exit 0 = connected (or just re-sent), 1 = could not talk to the Tunnel.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glinet  # noqa: E402  (copied next to this file by install.sh)

CONFIG = os.environ.get("TUNNEL_CONFIG", "/etc/burrow/tunnel.json")
STATE = "/run/tunnel-watchdog.json"
HOLDOFF_S = 90          # do not re-send a join while one may still be in progress


def decide(status, last_join_at, now):
    """Pure: given `repeater get_status`, when we last sent a join, and the
    time, return 'ok' | 'join' | 'wait'."""
    if (status or {}).get("state_s") == "connected":
        return "ok"
    if last_join_at and now - last_join_at < HOLDOFF_S:
        return "wait"
    return "join"


def main():
    cfg = json.load(open(CONFIG))
    try:
        st = json.load(open(STATE))
    except (OSError, ValueError):
        st = {}
    r = glinet.Router(cfg["host"], timeout=8)
    try:
        r.login(cfg["password"])
        status = r.call("repeater", "get_status")
    except Exception as e:
        print("tunnel %s unreachable: %s" % (cfg["host"], str(e)[:120]))
        return 1
    now = time.time()
    what = decide(status, st.get("last_join_at"), now)
    if what == "ok":
        print("connected to %s (%s dBm)" % (status.get("ssid"), status.get("signal")))
        return 0
    if what == "wait":
        print("repeater %s; join sent %ds ago, waiting" % (status.get("state_s"), now - st["last_join_at"]))
        return 0
    params = {k: cfg[k] for k in ("ssid", "key", "bssid", "device", "band", "encryption") if cfg.get(k)}
    if cfg.get("encryption") == "none":
        params.pop("key", None)
    try:
        r.timeout = 40
        r.call("repeater", "connect", params)
        print("repeater was %s: re-sent join to %s" % (status.get("state_s"), cfg["ssid"]))
    except Exception as e:
        print("join failed: %s" % str(e)[:120])
    try:
        json.dump({"last_join_at": now}, open(STATE, "w"))
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
