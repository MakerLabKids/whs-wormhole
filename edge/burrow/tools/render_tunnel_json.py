#!/usr/bin/env python3
"""render_tunnel_json.py: build a room's /etc/burrow/tunnel.json from the template and .env.

  edge/burrow/tools/render_tunnel_json.py --room 3 | ssh worm@192.168.83.10 'sudo tee /etc/burrow/tunnel.json >/dev/null'
  edge/burrow/tools/render_tunnel_json.py --room 0          # burrow0 on the Portal: no backhaul entry

The template is etc/tunnel.json.example; every "<...>" placeholder is filled from .env
(router_admin, backhaul_key, qtastic_psk, loki_psk, guess_psk, wormhole_psk). Room 0 is the
Pi cabled to the Portal (192.168.80.1), which is the backhaul AP itself, so the WormHole-Core
entry is dropped. Output goes to stdout only: pipe it to the Pi, never into the repo.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "etc", "tunnel.json.example")
ENV_FILE = os.environ.get("GLINET_ENV_FILE", "/workspace/.env")
PLACEHOLDERS = {
    "<router admin password>": "router_admin",
    "<backhaul key>": "backhaul_key",
    "<phone hotspot key>": "qtastic_psk",
    "<home key>": None,            # Loki and Guess differ: resolved per ssid below
    "<WormHole key>": "wormhole_psk",
}
HOME_KEYS = {"Loki": "loki_psk", "Guess": "guess_psk"}


def read_env(path):
    out = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def render(template, env, room):
    cfg = json.loads(json.dumps(template))
    cfg["host"] = "192.168.8%d.1" % room
    cfg["password"] = env[PLACEHOLDERS["<router admin password>"]]
    ups = []
    for u in cfg["upstreams"]:
        if u["ssid"] == "WormHole-Core":
            if room == 0:
                continue
            u["key"] = env[PLACEHOLDERS["<backhaul key>"]]
        elif u.get("key") == "<home key>":
            u["key"] = env[HOME_KEYS[u["ssid"]]]
        elif u.get("key") in PLACEHOLDERS:
            u["key"] = env[PLACEHOLDERS[u["key"]]]
        ups.append(u)
    cfg["upstreams"] = ups
    cfg["wifi_fallback"]["key"] = env[PLACEHOLDERS["<WormHole key>"]]
    missing = [k for k, v in cfg.items() if isinstance(v, str) and v.startswith("<")]
    missing += ["upstream " + u["ssid"] for u in ups if str(u.get("key", "")).startswith("<")]
    if missing:
        raise SystemExit("unfilled placeholders: %s" % ", ".join(missing))
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--room", type=int, required=True, choices=(0, 1, 2, 3))
    a = ap.parse_args()
    with open(TEMPLATE) as f:
        template = json.load(f)
    cfg = render(template, read_env(ENV_FILE), a.room)
    json.dump(cfg, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
