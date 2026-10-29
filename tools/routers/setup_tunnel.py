#!/usr/bin/env python3
"""setup_tunnel.py: make one Opal a complete Tunnel N, the way Tunnel 2 is (2026-10-28).

  tools/routers/setup_tunnel.py --room 1 [--host 192.168.8.1] [--dry-run]

What a Tunnel is (the template is Tunnel 2, captured 2026-10-28):
  firmware 4.8.3; 2.4 GHz WormHole (WPA2, room channel 1/6/11, width auto) for the Bins;
  5 GHz radio repeating the Portal's hidden WPA3 WormHole-Core (auto-switch OFF, smart
  reconnect on); TCP 8080, 22 and 5201 forwarded to the room's Burrow at 192.168.8N.10
  (dashboard, ssh and iperf3 reachable from the Portal LAN at 192.168.80.2N, so no cable
  turn is needed to maintain a Pi and Burrows can measure each other); LAN 192.168.8N.1.

Order matters and the script keeps it: a factory box gets its admin password first; the LAN
address goes LAST because the box moves and the laptop's lease is stale afterwards. Every
step is skipped when the box already has it, so the script is safe to re-run. Secrets come
from /workspace/.env (router_admin, wormhole_psk, backhaul_key); nothing is printed.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glinet  # noqa: E402

TARGET_FW = "4.8.3"
PORTAL_CORE_BSSID = "94:83:c4:84:d2:0c"
ROOM_CHANNEL = {1: 1, 2: 6, 3: 11}


def desired(room, wormhole_key, backhaul_key):
    lan_ip = "192.168.8%d.1" % room
    return {
        "lan_ip": lan_ip,
        "burrow_ip": "192.168.8%d.10" % room,
        "radio0": {"iface_name": "default_radio0", "device": "radio0", "ssid": "WormHole",
                   "key": wormhole_key, "encryption": "psk2", "hidden": False, "hwmode": "11g/n",
                   "htmode": "auto", "channel": ROOM_CHANNEL[room], "txpower": "Max",
                   "random_bssid": False},
        "repeater_cfg": {"auto": False, "smart_reconnect": True},
        "backhaul": {"ssid": "WormHole-Core", "key": backhaul_key, "bssid": PORTAL_CORE_BSSID,
                     "device": "radio1", "band": "5g", "encryption": "sae"},
        "forwards": [{"name": "Burrow", "proto": "tcp", "src": "wan", "src_dport": "8080",
                      "dest": "lan", "dest_ip": "192.168.8%d.10" % room, "dest_port": "8080",
                      "enabled": True},
                     {"name": "BurrowSSH", "proto": "tcp", "src": "wan", "src_dport": "22",
                      "dest": "lan", "dest_ip": "192.168.8%d.10" % room, "dest_port": "22",
                      "enabled": True},
                     {"name": "BurrowIperf", "proto": "tcp", "src": "wan", "src_dport": "5201",
                      "dest": "lan", "dest_ip": "192.168.8%d.10" % room, "dest_port": "5201",
                      "enabled": True}],
    }


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def plan(state, want):
    """Pure: which steps the box still needs, in the order to do them.
    state = {"fw", "wifi", "repeater_cfg", "repeater_status", "forwards", "lan_ip"}."""
    steps = []
    if state.get("fw") != TARGET_FW:
        return [("upgrade", state.get("fw"))]      # nothing else is safe to script before this
    r0 = None
    for radio in (state.get("wifi") or {}).get("res", []):
        if radio.get("device") == "radio0":
            r0 = radio
    iface = next((i for i in (r0 or {}).get("ifaces", []) if i.get("iface_name", i.get("name")) == "default_radio0"), {})
    w = want["radio0"]
    if not (iface.get("ssid") == w["ssid"] and iface.get("encryption") == w["encryption"]
            and iface.get("enabled", True) and _int((r0 or {}).get("channel")) == w["channel"]):
        steps.append(("wifi", w))
    rc = state.get("repeater_cfg") or {}
    if rc.get("auto") is not False or rc.get("smart_reconnect") is not True:
        steps.append(("repeater_cfg", want["repeater_cfg"]))
    rs = state.get("repeater_status") or {}
    if not (rs.get("state_s") == "connected" and rs.get("ssid") == want["backhaul"]["ssid"]):
        steps.append(("backhaul", want["backhaul"]))
    for f in want["forwards"]:
        have = any(x.get("src_dport") == f["src_dport"] and x.get("dest_ip") == f["dest_ip"]
                   and x.get("proto") == f["proto"] for x in state.get("forwards") or [])
        if not have:
            steps.append(("forward", f))
    if state.get("lan_ip") != want["lan_ip"]:
        steps.append(("lan", {"interface": "lan", "ip": want["lan_ip"], "netmask": "255.255.255.0", "ap_isolate": 0}))
    return steps


def read_state(r):
    info = r.call("system", "get_info") or {}
    fwds = (r.call("firewall", "get_port_forward_list") or {}).get("res") or []
    lan = next((i for i in (r.call("lan", "get_config_list") or {}).get("interfaces", []) if i.get("interface") == "lan"), {})
    r.timeout = 20
    try:
        status = r.call("repeater", "get_status") or {}
    except glinet.RpcError:
        status = {}
    return {"fw": info.get("firmware_version"), "mac": info.get("mac"), "wifi": r.call("wifi", "get_config"),
            "repeater_cfg": r.call("repeater", "get_config"), "repeater_status": status,
            "forwards": fwds, "lan_ip": lan.get("ip")}


def redact(params):
    return {k: ("<key>" if k == "key" else v) for k, v in params.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--room", type=int, required=True, choices=(1, 2, 3))
    ap.add_argument("--host", default=None, help="the box's current address (default: factory 192.168.8.1)")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    a = ap.parse_args()
    host = a.host or "192.168.8.1"
    pw = glinet.password_from_env(key="router_admin")
    want = desired(a.room, glinet.password_from_env(key="wormhole_psk"), glinet.password_from_env(key="backhaul_key"))
    if not (pw and want["radio0"]["key"] and want["backhaul"]["key"]):
        sys.exit("missing router_admin / wormhole_psk / backhaul_key in .env")

    r = glinet.Router(host, timeout=10)
    if not r.is_initialized():
        print("factory box: setting the admin password")
        if not a.dry_run:
            r.init(pw)
            time.sleep(3)
    r.login(pw)
    st = read_state(r)
    print("box %s fw %s mac %s lan %s repeater %s/%s" % (host, st["fw"], st["mac"], st["lan_ip"],
          (st["repeater_status"] or {}).get("state_s"), (st["repeater_status"] or {}).get("ssid")))
    steps = plan(st, want)
    if not steps:
        print("already a complete Tunnel %d" % a.room)
        return 0
    for what, params in steps:
        print("step:", what, json.dumps(redact(params)) if isinstance(params, dict) else params)
    if steps[0][0] == "upgrade":
        print("firmware %s is not %s: upgrade it first (tools/routers/README.md, 'Firmware upgrade'), then re-run" % (steps[0][1], TARGET_FW))
        return 2
    if a.dry_run:
        return 0
    for what, params in steps:
        if what == "wifi":
            r.call("wifi", "set_config", params)
        elif what == "repeater_cfg":
            r.call("repeater", "set_config", params)
        elif what == "backhaul":
            r.timeout = 40
            r.call("repeater", "connect", params)
            for _ in range(8):
                time.sleep(3)
                s = r.call("repeater", "get_status") or {}
                if s.get("state_s") == "connected":
                    print("   backhaul connected: %s %s dBm" % ((s.get("ipv4") or {}).get("ip"), s.get("signal")))
                    break
            else:
                print("   backhaul not connected yet (%s); the Burrow watchdog retries every 2 min" % s.get("state_s"))
            r.timeout = 10
        elif what == "forward":
            r.call("firewall", "add_port_forward", params)
        elif what == "lan":
            print("moving the LAN to %s: the box drops off this address now; renew the laptop's lease and reach it at %s"
                  % (params["ip"], params["ip"]))
            try:
                r.call("lan", "set_config", params)
            except Exception as e:          # the reply often dies with the old address
                print("   (reply lost, expected: %s)" % str(e)[:60])
        print("done:", what)
    return 0


if __name__ == "__main__":
    sys.exit(main())
