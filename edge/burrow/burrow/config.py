"""Configuration: one JSON file, every knob with a sane default."""
import json
import os

DEFAULTS = {
    "edge": "burrow1",             # this Burrow's name
    "room": 1,                     # classroom number 1..3
    "listen": "0.0.0.0",
    "port": 8080,
    "data_dir": "/data/burrow",    # the read-write partition
    "www_dir": "/opt/burrow/www",  # the dashboard
    "peers": {                     # the OTHER Burrows, as reached from here
        "burrow2": "http://192.168.80.22:8080",
        "burrow3": "http://192.168.80.23:8080",
    },
    "cloud": {
        "url": "https://whs.makerlabkids.com",
        "token_file": "/etc/burrow/cloud.token",   # per-Burrow bearer token
        "live_key_file": "/etc/burrow/live.key",   # shared secret the Worker sends on /live
        "every_s": 60,
    },
    "seal_minutes": 15,            # casting window
    "seal_grace_s": 20,            # seal this long after the boundary
    "fsync_s": 30,                 # open-log fsync cadence
    "retain_days": 7,              # never reclaim younger than this
    "replicate_every_s": 120,
    "sweep": {                     # pull fallback: poll quiet Bins at /data
        "enabled": True,
        "every_s": 300,
        "subnet": None,            # None = derive from own address (x.y.z.0/24)
        "first": 100, "last": 249,
        "quiet_s": 300,            # a Bin not heard from for this long gets polled
        "timeout_s": 0.6,
        "workers": 16,
    },
    "stale_s": 180,                # a Bin is "stale" after this with no row
    "quiet_alert_s": 600,          # ...and an event goes to the cloud when it has been silent this long
    "net": {                       # measured throughput to the other Burrows (iperf3, see netstat.py)
        "every_s": 900,
        "seconds": 3,              # per direction, per target
        "port": 5201,
        "targets": None,           # None = burrow0 at 192.168.80.10 + the other Tunnels' WAN 192.168.80.2N
        "internet_url": "https://speed.cloudflare.com",   # timed download/upload + latency; 0 bytes = off
        "internet_bytes_down": 8000000,
        "internet_bytes_up": 2000000,
    },
    "watch": {                     # 1 Hz live view: poll a watched Bin's /data while anyone watches it
        "every_s": 1.0,
        "timeout_s": 0.8,
        "max_bins": 8,             # at most this many Bins watched at once per Burrow
    },
    "snapshot_every_s": 60,
    "max_body": 65536,
}


def load(path=None):
    """Merge /etc/burrow/burrow.json (or $BURROW_CONFIG) over DEFAULTS."""
    path = path or os.environ.get("BURROW_CONFIG", "/etc/burrow/burrow.json")
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(path) as f:
            user = json.load(f)
    except FileNotFoundError:
        user = {}
    if isinstance(user.get("peers"), dict):
        cfg["peers"] = {}            # the file's peer list replaces the default one, it does not extend it
    _merge(cfg, user)
    cfg["peers"].pop(cfg["edge"], None)   # never peer with ourselves
    cfg["_path"] = path
    return cfg


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
