#!/usr/bin/env python3
"""site_check.py: the install-day test. Every device, every link, one table, in a minute.

  tools/fleet/site_check.py                      # cloud mode: through the Cloudflare tunnels (from anywhere)
  tools/fleet/site_check.py --lan                # + ssh checks (laptop cabled to any Opal): services, Opal forwards
  tools/fleet/site_check.py --measure            # + a fresh throughput/ping run on every Burrow (adds ~2 min)
  tools/fleet/site_check.py --site school        # expect the Portal on BYLD (home: Loki/Guess/Q-tastic)

Reads LIVE_KEY from /workspace/.env for the tunnels (never printed). Prints PASS / WARN / FAIL
per check with the number that decided it; exit code 1 when anything FAILs.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

ROOMS = (0, 1, 2, 3)
DOMAIN = "whs.makerlabkids.com"
LAN = {0: "192.168.80.10", 1: "192.168.80.21", 2: "192.168.80.22", 3: "192.168.80.23"}
SCHOOL_UPSTREAMS = ("BYLD",)
HOME_UPSTREAMS = ("Loki", "Guess", "Q-tastic")


def env_value(key, path="/workspace/.env"):
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return None


def fetch_json(url, headers=None, timeout=12):
    h = {"User-Agent": "wormhole-site-check/1 (curl-like; python-urllib is bot-blocked at the edge)", "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def resolve(host):
    """Cloudflare's own resolver: the container's cache may still say NXDOMAIN for new names."""
    try:
        j = fetch_json("https://cloudflare-dns.com/dns-query?name=%s&type=A" % host, {"accept": "application/dns-json"})
        return (j.get("Answer") or [{}])[0].get("data")
    except Exception:
        return None


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, where, check, detail=""):
        self.rows.append((level, where, check, detail))

    def ok(self, where, check, detail=""): self.add("PASS", where, check, detail)
    def warn(self, where, check, detail=""): self.add("WARN", where, check, detail)
    def fail(self, where, check, detail=""): self.add("FAIL", where, check, detail)

    def print(self):
        w = max(len(r[1]) for r in self.rows) if self.rows else 8
        for level, where, check, detail in self.rows:
            print("%-4s %-*s %-28s %s" % (level, w, where, check, detail))
        n = {"PASS": 0, "WARN": 0, "FAIL": 0}
        for r in self.rows:
            n[r[0]] += 1
        print("\n%d pass, %d warn, %d fail" % (n["PASS"], n["WARN"], n["FAIL"]))
        return n["FAIL"]


def judge_status(rep, room, st, site, now=None):
    """Pure: the checks on one Burrow's /api/status. Tested."""
    now = now or int(time.time())
    who = "burrow%d" % room
    rep.ok(who, "reachable", "v%s, up %s" % (st.get("version"), fmt_dur(st.get("up_s"))))
    clk = st.get("clk")
    (rep.ok if clk in ("ntp", "peer") else rep.warn)(who, "clock", clk or "?")
    cloud = st.get("cloud") or {}
    (rep.ok if cloud.get("reachable") else rep.fail)(who, "cloud", "reachable" if cloud.get("reachable") else (cloud.get("error") or "unreachable"))
    if cloud.get("captive"):
        rep.fail(who, "captive portal", "the school net is intercepting HTTP")
    disk = st.get("disk_pct")
    (rep.ok if (disk or 0) < 80 else rep.warn)(who, "disk", "%s%% used" % disk)
    t = st.get("tunnel") or {}
    rep_ = t.get("repeater") or {}
    up, sig = t.get("upstream") or rep_.get("ssid"), t.get("signal") if t.get("signal") is not None else rep_.get("signal")
    state = t.get("state")
    if not t:
        rep.warn(who, "Opal watchdog", "no state (watchdog not installed?)")
    else:
        (rep.ok if state == "ok" else rep.fail)(who, "Opal", "%s via %s %s dBm" % (state, up, sig))
        if room == 0:
            want = SCHOOL_UPSTREAMS if site == "school" else HOME_UPSTREAMS
            (rep.ok if up in want else rep.warn)(who, "Portal upstream", "%s (expected one of %s)" % (up, ", ".join(want)))
        elif up and up != "WormHole-Core":
            rep.warn(who, "Tunnel upstream", "%s, not the Portal backhaul (forwards are open on that net)" % up)
        if sig is not None:
            (rep.ok if sig >= -65 else rep.warn if sig >= -75 else rep.fail)(who, "signal", "%s dBm" % sig)
        if t.get("down_since"):
            rep.fail(who, "Opal down", "since %s" % time.strftime("%H:%M", time.localtime(t["down_since"])))
    net = st.get("net") or {}
    if not net:
        rep.warn(who, "throughput", "no measurements yet")
    for name, n in sorted(net.items()):
        age = now - (n.get("at") or 0) if n.get("at") else None
        if not n.get("at"):
            rep.warn(who, "net " + name, "not measured yet"); continue
        if n.get("error") and n.get("up_mbps") is None:
            rep.fail(who, "net " + name, n["error"]); continue
        detail = "up %s / down %s Mbit/s, %s ms, %s%% loss, %s ago" % (n.get("up_mbps"), n.get("down_mbps"), n.get("ms"), n.get("loss_pct"), fmt_dur(age))
        slow = (n.get("down_mbps") or 0) < (5 if name == "internet" else 20)
        lossy = (n.get("loss_pct") or 0) >= 20
        (rep.fail if lossy else rep.warn if (slow or age > 2400) else rep.ok)(who, "net " + name, detail)
    ev = st.get("events") or {}
    (rep.ok if not ev.get("queued") else rep.warn)(who, "events", "%d queued" % (ev.get("queued") or 0) + (", last error %s" % ev["last_error"] if ev.get("last_error") else ""))
    q = st.get("quiet") or []
    (rep.ok if not q else rep.warn)(who, "quiet bins", "%d silent over 10 min" % len(q) if q else "none")
    rep.ok(who, "bins", "%s known, %s live viewers" % (st.get("bins"), st.get("live_clients")))


def fmt_dur(s):
    if s is None:
        return "?"
    s = int(s)
    return "%d s" % s if s < 120 else "%d min" % (s // 60) if s < 7200 else "%.1f h" % (s / 3600) if s < 2 * 86400 else "%.1f d" % (s / 86400)


def cloud_checks(rep, site, measure):
    key = env_value("LIVE_KEY")
    if not key:
        rep.fail("surface", "LIVE_KEY", "not in /workspace/.env; cannot read the Burrows through their tunnels")
    try:
        pub = fetch_json("https://%s/api/public/now" % DOMAIN)
        now = int(time.time())
        for edge, e in sorted((pub.get("edges") or {}).items()):
            age = now - (e.get("seen") or 0)
            (rep.ok if age < 180 else rep.fail)("surface", "snapshot " + edge, "%s ago" % fmt_dur(age))
        rep.ok("surface", "bins on the feed", str(len(pub.get("bins") or {})))
    except Exception as e:
        rep.fail("surface", "public feed", str(e)[:80])
    if not key:
        return
    for room in ROOMS:
        host = "burrow%d.%s" % (room, DOMAIN)
        a = resolve(host)
        if not a:
            rep.fail("burrow%d" % room, "tunnel hostname", "no DNS record for %s" % host); continue
        try:
            st = fetch_json("https://%s/api/status" % host, {"X-Burrow-Key": key})
        except Exception as e:
            rep.fail("burrow%d" % room, "reachable via tunnel", str(e)[:80]); continue
        judge_status(rep, room, st, site)


def lan_checks(rep, measure):
    for room in ROOMS:
        ip = LAN[room]; who = "burrow%d" % room
        cmd = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", "worm@" + ip,
               "echo cf=$(systemctl is-active cloudflared) iperf=$(systemctl is-active iperf3) burrow=$(systemctl is-active burrow) wd=$(systemctl is-active tunnel-watchdog.timer); "
               "chronyc tracking 2>/dev/null | sed -n 's/^Stratum *: *//p'; "
               "sudo -n python3 -c \"import json,sys; sys.path.insert(0,'/opt/burrow'); import glinet; c=json.load(open('/etc/burrow/tunnel.json')); r=glinet.Router(c['host'],timeout=8); r.login(c['password']); f=(r.call('firewall','get_port_forward_list') or {}).get('res') or []; print('forwards='+','.join(sorted(x.get('src_dport','') for x in f)))\" 2>/dev/null"
               + (" ; cd /opt/burrow && sudo -n -u burrow python3 -c \"from burrow import config; from burrow.netstat import NetStat; import json; print('net='+json.dumps(NetStat(config.load()).run_all()))\" 2>/dev/null" if measure else "")]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=240 if measure else 40).stdout.strip().splitlines()
        except Exception as e:
            rep.fail(who, "ssh", str(e)[:60]); continue
        if not out:
            rep.fail(who, "ssh", "no answer at %s (cable on an Opal? forwards up?)" % ip); continue
        svc = dict(kv.split("=", 1) for kv in out[0].split() if "=" in kv)
        for name, label in (("burrow", "burrow service"), ("cf", "cloudflared"), ("iperf", "iperf3 server"), ("wd", "watchdog timer")):
            (rep.ok if svc.get(name) == "active" else rep.fail)(who, label, svc.get(name, "?"))
        stratum = next((l for l in out[1:] if l.strip().isdigit()), None)
        if stratum is not None:
            (rep.ok if int(stratum) < 10 else rep.warn)(who, "chrony stratum", stratum)
        fw = next((l for l in out if l.startswith("forwards=")), None)
        if room != 0:
            if fw is None:
                rep.warn(who, "Opal forwards", "could not read")
            else:
                have = set(fw[9:].split(",")) - {""}
                (rep.ok if {"8080", "22", "5201"} <= have else rep.fail)(who, "Opal forwards", ",".join(sorted(have)) or "none")
        for l in out:
            if l.startswith("net="):
                for name, n in sorted(json.loads(l[4:]).items()):
                    (rep.fail if n.get("error") and n.get("up_mbps") is None else rep.ok)(who, "fresh net " + name,
                        n.get("error") or "up %s / down %s Mbit/s, %s ms" % (n.get("up_mbps"), n.get("down_mbps"), n.get("ms")))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lan", action="store_true", help="also ssh to each Pi over the Portal LAN (laptop cabled to any Opal)")
    ap.add_argument("--measure", action="store_true", help="with --lan: run a fresh throughput/ping test on every Burrow now")
    ap.add_argument("--site", choices=("school", "home"), default="school")
    a = ap.parse_args()
    rep = Report()
    cloud_checks(rep, a.site, a.measure)
    if a.lan or a.measure:
        lan_checks(rep, a.measure)
    return 1 if rep.print() else 0


if __name__ == "__main__":
    sys.exit(main())
