"""Pull fallback: poll /data on quiet Bins and on unknown addresses in our subnet."""
import json
import socket
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import util
from .util import log


def own_ip(gateway_guess="192.168.80.1"):
    """Our address on the classroom LAN (route-based; no traffic is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((gateway_guess, 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def fetch_data(ip, timeout):
    req = urllib.request.Request("http://%s/data" % ip, headers={"User-Agent": "burrow-sweep"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8"))
        return d if isinstance(d, dict) else None


class Sweep:
    def __init__(self, cfg, now, ingest):
        self.cfg = cfg["sweep"]
        self.room = cfg["room"]
        self.now = now
        self.ingest = ingest
        self.last = {"at": 0, "polled": 0, "found": 0, "subnet": None}

    def subnet(self):
        if self.cfg.get("subnet"):
            return self.cfg["subnet"]
        ip = own_ip("192.168.8%d.1" % self.room) or own_ip()
        if not ip:
            return None
        return ip.rsplit(".", 1)[0] + ".0/24"

    def targets(self):
        sn = self.subnet()
        if not sn:
            return []
        base = sn.split("/")[0].rsplit(".", 1)[0]
        quiet = self.now.quiet(quiet_s=int(self.cfg["quiet_s"]))
        known_active = self.now.known_ips() - set(quiet.values())
        ips = []
        for ip in quiet.values():
            if ip and ip.startswith(base + "."):
                ips.append(ip)
        for i in range(int(self.cfg["first"]), int(self.cfg["last"]) + 1):
            ip = "%s.%d" % (base, i)
            if ip not in known_active and ip not in ips:
                ips.append(ip)
        self.last["subnet"] = sn
        return ips

    def run(self):
        if not self.cfg.get("enabled", True):
            return 0
        ips = self.targets()
        if not ips:
            return 0
        found = 0
        timeout = float(self.cfg["timeout_s"])

        def one(ip):
            try:
                return ip, fetch_data(ip, timeout)
            except Exception:
                return ip, None

        with ThreadPoolExecutor(max_workers=int(self.cfg["workers"])) as ex:
            for ip, d in ex.map(one, ips):
                if d and d.get("id"):
                    d.setdefault("ip", ip)
                    if self.ingest(d, src="pull", ip=ip) is not None:
                        found += 1
        self.last.update(at=util.now(), polled=len(ips), found=found)
        if found:
            log("sweep: polled %d addresses, pulled %d Bins" % (len(ips), found))
        return found
