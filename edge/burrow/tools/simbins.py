#!/usr/bin/env python3
"""Pretend to be N worm-bin Picos pushing to a Burrow. For testing without hardware.

  python3 tools/simbins.py --edge http://127.0.0.1:8080 --n 17 --every 10

Each fake Bin has a stable uid/name, drifts its readings slowly, and posts
the same shape of JSON the real firmware does (see PROTOCOL.md)."""
import argparse
import json
import math
import random
import time
import urllib.request

NAMES = ["Dirt Vader", "Compost Malone", "Worm Rangers", "Soil Mates", "Night Crawlers",
         "Bin Diesel", "Harry Rotter", "Mud Max", "The Sodfather", "Peaty Blinders",
         "Rot and Roll", "Global Worming", "Can of Worms", "Grime Time", "Humus Heroes",
         "Wu-Tang Clay", "Nine Inch Worms", "Scoop Dogg", "Game of Loam", "Breaking Mud"]


def payload(i, t, room):
    uid = "e661%012x" % (0xabc000 + i)
    base = 20 + (i % 5)
    d = {
        "id": uid, "name": NAMES[i % len(NAMES)], "ip": "192.168.8%d.%d" % (room, 100 + i),
        "ssid": "WormHole", "mode": "joined", "net": "WormHole", "ok": True,
        "in_temp_c": round(base + 2 * math.sin(t / 900 + i) + random.uniform(-0.1, 0.1), 1),
        "in_hum_pct": round(65 + 10 * math.sin(t / 1800 + i) + random.uniform(-0.5, 0.5), 1),
        "in_press_hpa": round(1012 + 3 * math.sin(t / 7200), 1),
        "out_temp_c": round(base + 1 + random.uniform(-0.1, 0.1), 1),
        "moist1_pct": round(45 + 15 * math.sin(t / 3600 + i / 2), 1),
        "moist2_pct": round(50 + 12 * math.sin(t / 4000 + i / 3), 1),
        "light_pct": round(max(0, 40 + 40 * math.sin(t / 43200)), 1),
        "sound_pct": round(random.uniform(1, 8), 1),
        "surface_mm": 120 + i,
        "probe_temps_c": [round(base - 0.5 + random.uniform(-0.1, 0.1), 1), round(base - 0.7, 1)],
        "probes": 2, "probe_count": 2, "probe_ok": [True, True],
        "big": 90, "small": 90, "relay": 0,
        "parts": [{"name": "BME280 in (0x76)", "ok": True}, {"name": "ADS1115 bank (0x48)", "ok": i % 7 != 3}],
        "bin": {"team": NAMES[i % len(NAMES)], "period": 1 + i % 3, "bin": 1 + i, "room": room},
        "up": int(t) % 100000, "rssi": -50 - (i % 30),
    }
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edge", default="http://127.0.0.1:8080")
    ap.add_argument("--n", type=int, default=17)
    ap.add_argument("--every", type=float, default=60)
    ap.add_argument("--room", type=int, default=1)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    while True:
        t = time.time()
        ok = 0
        for i in range(a.n):
            body = json.dumps(payload(i, t, a.room)).encode()
            req = urllib.request.Request(a.edge + "/ingest", data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=3) as r:
                    if json.loads(r.read()).get("ok"):
                        ok += 1
            except Exception as e:
                print("bin %d: %s" % (i, e))
        print(time.strftime("%H:%M:%S"), "posted %d/%d" % (ok, a.n))
        if a.once:
            break
        time.sleep(max(0.5, a.every - (time.time() - t)))


if __name__ == "__main__":
    main()
