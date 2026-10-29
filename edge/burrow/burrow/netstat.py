"""Measured throughput between Burrows: what the links actually carry, not what the
signal bars suggest.

Every `net.every_s` (15 min) this Burrow runs iperf3 against every other Burrow it can
reach (the Portal's Pi at 192.168.80.10 and the Tunnels' WAN addresses 192.168.80.2N,
where each Tunnel forwards 5201 to its Pi), 3 s up and 3 s down, and keeps the result:
up_mbps / down_mbps / at / error plus a short history. The latest numbers ride in the
status brief, so the cloud snapshot and the admin Devices page show them remotely.
Burrows start their runs staggered by room so two clients never hit one server at once
(iperf3 serves one test at a time and answers "busy" otherwise).

The same run also measures the way OUT: a timed download and upload against Cloudflare's
speed-test endpoint (speed.cloudflare.com, no account needed), so the "internet" row on the
Devices page says what the school uplink really gives this room.

Every row also gets a real ping: 5 ICMP echoes (ms = average round trip, ms_max, loss_pct) to
the peer, and to 1.1.1.1 for the internet row (ttfb_ms keeps the HTTPS first-byte time, which
includes the TLS handshake and so runs about three times the ping).
"""
import json
import re
import shutil
import subprocess
import time
import urllib.request

from . import util
from .util import log

HOSTS = {0: "192.168.80.10", 1: "192.168.80.21", 2: "192.168.80.22", 3: "192.168.80.23"}


def default_targets(room):
    return {"burrow%d" % r: h for r, h in HOSTS.items() if r != room}


class NetStat:
    def __init__(self, cfg, runner=None, which=shutil.which, http=None, pinger=None):
        n = cfg.get("net") or {}
        self.every_s = int(n.get("every_s", 900))
        self.seconds = int(n.get("seconds", 3))
        self.port = int(n.get("port", 5201))
        self.targets = n.get("targets") or default_targets(int(cfg.get("room", 1)))
        self.runner = runner or self._iperf
        self.which = which
        self.inet_url = n.get("internet_url", "https://speed.cloudflare.com")
        self.inet_down = int(n.get("internet_bytes_down", 8_000_000))
        self.inet_up = int(n.get("internet_bytes_up", 2_000_000))
        self.http = http or self._http
        self.pinger = pinger or self._ping
        self.ping_host = n.get("ping_host", "1.1.1.1")
        self.state = {name: {"host": host, "up_mbps": None, "down_mbps": None, "ms": None, "ms_max": None, "loss_pct": None,
                             "at": None, "error": None, "history": []}
                      for name, host in self.targets.items()}
        if self.inet_down or self.inet_up:
            self.state["internet"] = {"host": self.inet_url.split("//")[-1], "up_mbps": None, "down_mbps": None,
                                      "ms": None, "ms_max": None, "loss_pct": None, "ttfb_ms": None,
                                      "at": None, "error": None, "history": []}

    def _iperf(self, host, reverse):
        args = ["iperf3", "-c", host, "-p", str(self.port), "-t", str(self.seconds), "-J", "--connect-timeout", "3000"]
        if reverse:
            args.append("-R")
        p = subprocess.run(args, capture_output=True, text=True, timeout=self.seconds + 20)
        return p.stdout or p.stderr

    @staticmethod
    def parse(text):
        """Mbit/s the receiving side actually got (the honest number in both directions)."""
        d = json.loads(text)
        if d.get("error"):
            raise RuntimeError(d["error"])
        recv = (d.get("end") or {}).get("sum_received") or {}
        bps = recv.get("bits_per_second")
        if bps is None:
            raise RuntimeError("no sum_received in iperf3 output")
        return round(float(bps) / 1e6, 1)

    def measure(self, name):
        st = self.state[name]
        st["at"] = util.now()
        st["error"] = None
        self.ping(st, st["host"])
        if not self.which("iperf3"):
            st["error"] = "iperf3 not installed"
            return st
        try:
            up = self.parse(self.runner(st["host"], False))      # we send, they receive
            down = self.parse(self.runner(st["host"], True))     # -R: they send, we receive
            st.update(up_mbps=up, down_mbps=down)
            st["history"].append([st["at"], up, down, st["ms"], st["loss_pct"]])
            del st["history"][:-96]                              # a day at 15 min
        except Exception as e:
            st["error"] = str(e)[:120]
        return st

    @staticmethod
    def _ping(host, count=5):
        p = subprocess.run(["ping", "-n", "-q", "-c", str(count), "-i", "0.2", "-W", "1", host],
                           capture_output=True, text=True, timeout=count + 6)
        return p.stdout + p.stderr

    @staticmethod
    def parse_ping(text):
        """{'ms': avg, 'ms_max': max, 'loss_pct': n} from iputils' summary; all lost -> ms None."""
        loss = re.search(r"(\d+(?:\.\d+)?)% packet loss", text)
        rtt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/", text)
        out = {"loss_pct": float(loss.group(1)) if loss else 100.0, "ms": None, "ms_max": None}
        if rtt:
            out["ms"] = round(float(rtt.group(2)), 1)
            out["ms_max"] = round(float(rtt.group(3)), 1)
        return out

    def ping(self, st, host):
        try:
            st.update(self.parse_ping(self.pinger(host)))
        except Exception as e:
            st.update(ms=None, ms_max=None, loss_pct=100.0)
            st["error"] = (st.get("error") or "") or "ping: %s" % str(e)[:80]

    @staticmethod
    def _http(url, data=None, timeout=25):
        """One transfer: returns (bytes moved, seconds for the whole body, seconds to first byte)."""
        req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                     headers={"User-Agent": "burrow-netstat", "Content-Type": "application/octet-stream"})
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            first = time.monotonic() - t0
            n = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                n += len(chunk)
        return (len(data) if data is not None else n), time.monotonic() - t0, first

    def internet(self):
        st = self.state.get("internet")
        if not st:
            return None
        st["at"] = util.now()
        self.ping(st, self.ping_host)
        try:
            _, _, ttfb = self.http(self.inet_url + "/__down?bytes=0")
            st["ttfb_ms"] = round(ttfb * 1000)
            if self.inet_down:
                n, secs, _ = self.http(self.inet_url + "/__down?bytes=%d" % self.inet_down)
                st["down_mbps"] = round(n * 8 / max(secs, 1e-3) / 1e6, 1)
            if self.inet_up:
                n, secs, _ = self.http(self.inet_url + "/__up", data=b"\0" * self.inet_up)
                st["up_mbps"] = round(n * 8 / max(secs, 1e-3) / 1e6, 1)
            st["error"] = None
            st["history"].append([st["at"], st["up_mbps"], st["down_mbps"], st["ms"], st["loss_pct"]])
            del st["history"][:-96]
        except Exception as e:
            st["error"] = str(e)[:120]
        return st

    def run_all(self):
        st = self.internet()
        if st:
            log("net: internet: %s" % (st["error"] or "up %s / down %s Mbit/s, ping %s ms (%s%% loss), ttfb %s ms"
                                       % (st["up_mbps"], st["down_mbps"], st["ms"], st["loss_pct"], st["ttfb_ms"])))
        for name in self.targets:
            st = self.measure(name)
            if st["error"]:
                log("net: %s (%s): %s" % (name, st["host"], st["error"]))
            else:
                log("net: %s (%s): up %s / down %s Mbit/s, ping %s ms (%s%% loss)" % (name, st["host"], st["up_mbps"], st["down_mbps"], st["ms"], st["loss_pct"]))
        return self.brief()

    def brief(self):
        return {name: {k: st[k] for k in ("up_mbps", "down_mbps", "at", "error", "ms", "ms_max", "loss_pct", "ttfb_ms") if k in st}
                for name, st in self.state.items()}
