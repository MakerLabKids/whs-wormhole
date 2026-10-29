"""Measured throughput between Burrows: what the links actually carry, not what the
signal bars suggest.

Every `net.every_s` (15 min) this Burrow runs iperf3 against every other Burrow it can
reach (the Portal's Pi at 192.168.80.10 and the Tunnels' WAN addresses 192.168.80.2N,
where each Tunnel forwards 5201 to its Pi), 3 s up and 3 s down, and keeps the result:
up_mbps / down_mbps / at / error plus a short history. The latest numbers ride in the
status brief, so the cloud snapshot and the admin Devices page show them remotely.
Burrows start their runs staggered by room so two clients never hit one server at once
(iperf3 serves one test at a time and answers "busy" otherwise).
"""
import json
import shutil
import subprocess

from . import util
from .util import log

HOSTS = {0: "192.168.80.10", 1: "192.168.80.21", 2: "192.168.80.22", 3: "192.168.80.23"}


def default_targets(room):
    return {"burrow%d" % r: h for r, h in HOSTS.items() if r != room}


class NetStat:
    def __init__(self, cfg, runner=None, which=shutil.which):
        n = cfg.get("net") or {}
        self.every_s = int(n.get("every_s", 900))
        self.seconds = int(n.get("seconds", 3))
        self.port = int(n.get("port", 5201))
        self.targets = n.get("targets") or default_targets(int(cfg.get("room", 1)))
        self.runner = runner or self._iperf
        self.which = which
        self.state = {name: {"host": host, "up_mbps": None, "down_mbps": None, "at": None, "error": None, "history": []}
                      for name, host in self.targets.items()}

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
        if not self.which("iperf3"):
            st["error"] = "iperf3 not installed"
            return st
        try:
            up = self.parse(self.runner(st["host"], False))      # we send, they receive
            down = self.parse(self.runner(st["host"], True))     # -R: they send, we receive
            st.update(up_mbps=up, down_mbps=down, error=None)
            st["history"].append([st["at"], up, down])
            del st["history"][:-96]                              # a day at 15 min
        except Exception as e:
            st["error"] = str(e)[:120]
        return st

    def run_all(self):
        for name in self.targets:
            st = self.measure(name)
            if st["error"]:
                log("net: %s (%s): %s" % (name, st["host"], st["error"]))
            else:
                log("net: %s (%s): up %s / down %s Mbit/s" % (name, st["host"], st["up_mbps"], st["down_mbps"]))
        return self.brief()

    def brief(self):
        return {name: {k: st[k] for k in ("up_mbps", "down_mbps", "at", "error")} for name, st in self.state.items()}
