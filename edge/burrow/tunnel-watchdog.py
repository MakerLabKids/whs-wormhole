#!/usr/bin/env python3
"""tunnel-watchdog: keep this room's Opal (GL.iNet GL-SFT1200) on an upstream,
kick it when it is stuck, and report what it is doing.

Runs from a systemd timer every 2 minutes, next to the Opal it is wired to,
so it reaches the router over its LAN even when every radio is dead.

Each run:
  1. Is the cloud reachable from this Pi?  Is the Opal's repeater connected?
  2. Healthy: record diagnostics (state, upstream, signal, clients, uptime),
     drop the Wi-Fi fallback if it was up, done.
  3. Not healthy: re-send the join to the best upstream that is visible
     (config lists them in preference order), one attempt per 90 s. The rule
     (2026-10-28): a Tunnel prefers the Portal's backhaul while it carries
     internet; when it does not, every Tunnel walks the same failover list on
     its own, the phone hotspot first (turning it on means the regular
     network is broken even if it is up), then the school network, then the
     home networks. The Portal's own Pi (room 0) runs the same list minus
     the backhaul. Nobody waits to be rescued. An
     upstream marked "hidden": true is dialed blind (hidden SSIDs never
     appear in a scan); if that join does not connect, the next run moves
     on to the next upstream instead of redialing it.
  4. Still down after 15 min: reboot the Opal over RPC. Then once an hour,
     three times, then once a DAY, forever: a router that is down for a week
     still gets its daily kick. Never more than one reboot per hour.
  5. Down for 5 min and the Pi has a radio: join WormHole over Wi-Fi on the
     strongest access point that is NOT this room's Opal, so the Burrow's
     buffered castings and this report still reach the cloud. Dropped again
     when the cable is healthy.

Config /etc/burrow/tunnel.json (see etc/tunnel.json.example):
  {"host": "192.168.81.1", "password": "<router admin>",
   "upstreams": [            # preference order; the same list on every Opal
     {"ssid": "WormHole-Core", ...,  "device": "radio1", "band": "5g", "encryption": "sae", "hidden": true},
     {"ssid": "Q-tastic", ...,  "device": "radio0", "band": "2g", "encryption": "psk2"},
     {"ssid": "BYLD", "device": "radio0", "band": "2g", "encryption": "none"},
     {"ssid": "Loki", ..., "hidden": true},
     {"ssid": "Guess", ...}],
   "wifi_fallback": {"ssid": "WormHole", "key": "<wormhole>", "iface": "wlan0"},
   "cloud_url": "https://whs.makerlabkids.com"}
The old flat form (ssid/key/bssid/device/band/encryption at the top level) is
still accepted as a single upstream. cloud_url defaults to the Burrow's own
cloud.url from /etc/burrow/burrow.json.

Always exits 0 (an unreachable Opal is a finding, not a failed unit). The
whole picture is in /run/tunnel-watchdog.json; the Burrow serves it under
"tunnel" in /api/status and ships it in every cloud snapshot.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glinet  # noqa: E402  (copied next to this file by install.sh)

CONFIG = os.environ.get("TUNNEL_CONFIG", "/etc/burrow/tunnel.json")
BURROW_CONFIG = os.environ.get("BURROW_CONFIG", "/etc/burrow/burrow.json")
STATE = os.environ.get("TUNNEL_STATE", "/run/tunnel-watchdog.json")

HOLDOFF_S = 90            # do not re-send a join while one may still be in progress
REBOOT_AFTER_S = 15 * 60  # first reboot: 15 min of failure despite joins
REBOOT_HOURLY_N = 3       # then once an hour, this many times...
REBOOT_DAILY_S = 86400    # ...then once a day, forever
REBOOT_MIN_GAP_S = 3600   # never two reboots within an hour
REBOOT_SETTLE_S = 240     # after a reboot, give the Opal this long before judging it
WIFI_AFTER_S = 5 * 60     # bring the Pi's own Wi-Fi up after this long down
EVENTS_KEEP = 10


# ---------------------------------------------------------------------------
# Pure decisions (unit-tested; no network, no clock of their own)
# ---------------------------------------------------------------------------
def upstreams_of(cfg):
    """Preference-ordered list of repeater targets from the new or old config."""
    ups = cfg.get("upstreams")
    if ups:
        return list(ups)
    keys = ("ssid", "key", "bssid", "device", "band", "encryption")
    flat = {k: cfg[k] for k in keys if cfg.get(k)}
    return [flat] if flat.get("ssid") else []


def connect_params(up):
    params = {k: up[k] for k in ("ssid", "key", "bssid", "device", "band", "encryption") if up.get(k)}
    if up.get("encryption") == "none":
        params.pop("key", None)
    return params


def pick_upstream(upstreams, visible_ssids, current_ssid=None, current_failed=False, skip_ssid=None):
    """The upstream to join: the most preferred one that is visible. If the
    current one is connected but has no internet (current_failed), skip it so
    we try the next choice instead of re-joining a dead uplink. A hidden
    network ("hidden": true) never shows in a scan, so it always counts as
    visible and is tried blind; skip_ssid is the upstream whose last blind
    join did not connect, so the next run moves on down the list instead of
    dialing the same dark network forever."""
    for up in upstreams:
        if current_failed and up.get("ssid") == current_ssid:
            continue
        if skip_ssid and up.get("ssid") == skip_ssid:
            continue
        if visible_ssids is None or up.get("hidden") or up.get("ssid") in visible_ssids:
            return up
    return None


def decide(status, cloud_ok, last_join_at, now):
    """'ok' | 'join' | 'switch' | 'wait'.
    connected + cloud -> ok. connected, no cloud -> switch upstream (after
    holdoff). not connected -> join (after holdoff)."""
    connected = (status or {}).get("state_s") == "connected"
    if connected and cloud_ok is not False:      # None = no cloud_url to check against
        return "ok"
    if last_join_at and now - last_join_at < HOLDOFF_S:
        return "wait"
    return "switch" if connected else "join"


def reboot_due_at(down_since, reboots):
    """When the next reboot is allowed, given when the outage began and the
    times we already rebooted during it. 15 min, then hourly x3, then daily."""
    n = len(reboots)
    if n == 0:
        due = down_since + REBOOT_AFTER_S
    elif n <= REBOOT_HOURLY_N:
        due = down_since + REBOOT_AFTER_S + n * 3600
    else:
        due = reboots[-1] + REBOOT_DAILY_S
    if reboots:
        due = max(due, reboots[-1] + REBOOT_MIN_GAP_S)
    return due


def should_reboot(down_since, reboots, now):
    return bool(down_since) and now >= reboot_due_at(down_since, reboots)


def chrony_needs_kick(activity_text):
    """True when chrony still has NTP names it could not resolve (it started while
    the uplink was down and retries DNS only every few hours), so a restart now that
    the cloud answers gets the clock back in minutes instead of hours."""
    for line in (activity_text or "").splitlines():
        parts = line.split()
        if "unknown address" in line and parts and parts[0].isdigit():
            return int(parts[0]) > 0
    return False


def kick_chrony_if_stale(st, now):
    try:
        act = subprocess.run(["chronyc", "activity"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return False
    if not chrony_needs_kick(act):
        return False
    subprocess.run(["systemctl", "restart", "chrony"], capture_output=True, timeout=20)
    event(st, now, "chrony restarted: NTP names were unresolved from the outage")
    return True


def choose_fallback_bssid(scan_rows, ssid, exclude_bssids):
    """Strongest access point for `ssid` whose BSSID is not one of ours.
    scan_rows: [(bssid, ssid, signal_int)]."""
    ex = {b.lower() for b in exclude_bssids if b}
    best = None
    for bssid, s, sig in scan_rows:
        if s != ssid or not bssid or bssid.lower() in ex:
            continue
        if best is None or sig > best[1]:
            best = (bssid, sig)
    return best[0] if best else None


def parse_nmcli_scan(text):
    """nmcli -t -f BSSID,SSID,SIGNAL dev wifi list   (BSSID colons are escaped)."""
    rows = []
    for line in text.splitlines():
        parts = line.replace("\\:", "\0").split(":")
        if len(parts) < 3:
            continue
        bssid = parts[0].replace("\0", ":")
        ssid = parts[1].replace("\0", ":")
        try:
            sig = int(parts[2])
        except ValueError:
            sig = 0
        rows.append((bssid, ssid, sig))
    return rows


# ---------------------------------------------------------------------------
# Side effects, each behind a small function so tests can stub them
# ---------------------------------------------------------------------------
def cloud_reachable(url, timeout=6):
    """Any HTTP answer from the Surface means the internet path works; the
    endpoint itself may say 401, that is fine."""
    if not url:
        return None
    req = urllib.request.Request(url.rstrip("/") + "/v1/edge/ping", method="GET")
    try:
        urllib.request.urlopen(req, timeout=timeout).close()
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def nmcli(*args, timeout=30):
    try:
        out = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
        return out.returncode, (out.stdout or "") + (out.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


class WifiFallback:
    """The Pi's own radio, used only while the cable path is dead."""
    CON = "burrow-wifi"

    def __init__(self, cfg, run=nmcli):
        self.cfg = cfg or {}
        self.run = run
        self.iface = self.cfg.get("iface", "wlan0")

    def available(self):
        if not self.cfg.get("ssid"):
            return False
        rc, out = self.run("-t", "-f", "DEVICE,TYPE", "device", "status")
        return rc == 0 and any(l.split(":")[0] == self.iface for l in out.splitlines())

    def is_up(self):
        rc, out = self.run("-t", "-f", "NAME,DEVICE", "connection", "show", "--active")
        return rc == 0 and any(l.startswith(self.CON + ":") for l in out.splitlines())

    def scan(self):
        self.run("radio", "wifi", "on")
        self.run("device", "wifi", "rescan", "ifname", self.iface, timeout=20)
        time.sleep(4)
        rc, out = self.run("-t", "-f", "BSSID,SSID,SIGNAL", "device", "wifi", "list", "ifname", self.iface)
        return parse_nmcli_scan(out) if rc == 0 else []

    def up(self, exclude_bssids):
        bssid = choose_fallback_bssid(self.scan(), self.cfg["ssid"], exclude_bssids)
        if not bssid:
            return None
        rc, out = self.run("-t", "-f", "NAME", "connection", "show")
        exists = rc == 0 and self.CON in out.splitlines()
        common = ["connection.autoconnect", "no", "ipv4.route-metric", "50", "ipv6.method", "disabled",
                  "802-11-wireless.bssid", bssid, "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", self.cfg["key"]]
        if exists:
            self.run("connection", "modify", self.CON, *common)
        else:
            self.run("connection", "add", "type", "wifi", "ifname", self.iface, "con-name", self.CON,
                     "ssid", self.cfg["ssid"], *common)
        rc, out = self.run("connection", "up", self.CON, timeout=60)
        return bssid if rc == 0 else None

    def down(self):
        if self.is_up():
            self.run("connection", "down", self.CON)
        self.run("radio", "wifi", "off")


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------
def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_state(st):
    try:
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f)
        os.replace(tmp, STATE)
    except OSError:
        pass


def event(st, now, text):
    """Append to the short event log; a repeat of the last line is folded into
    it with a count, so a join every 90 s cannot push a reboot out of view."""
    print(text)
    ev = st.setdefault("events", [])
    if ev and ev[-1][1] == text[:160]:
        ev[-1] = [int(now), text[:160], ev[-1][2] + 1 if len(ev[-1]) > 2 else 2]
    else:
        ev.append([int(now), text[:160]])
    st["events"] = ev[-EVENTS_KEEP:]


def opal_facts(r):
    """Cheap diagnostics in one go; each call is best-effort."""
    facts = {}
    try:
        s = r.call("system", "get_status") or {}
        sysinfo = s.get("system") or s
        facts["uptime_s"] = sysinfo.get("uptime")
        facts["load"] = sysinfo.get("load") or sysinfo.get("loadavg")
    except Exception:
        pass
    try:
        cl = r.call("clients", "get_list") or {}
        lst = cl.get("clients") if isinstance(cl, dict) else cl
        facts["clients"] = len([c for c in (lst or []) if (c.get("online") if isinstance(c, dict) else True)])
    except Exception:
        pass
    try:
        w = r.call("wifi", "get_config") or {}
        bssids = []
        for radio in (w.get("res") or w.get("wifi") or []):
            for iface in radio.get("ifaces") or []:
                if iface.get("bssid") or iface.get("macaddr"):
                    bssids.append(iface.get("bssid") or iface.get("macaddr"))
        facts["own_bssids"] = bssids
    except Exception:
        pass
    return facts


FORWARDS = (("Burrow", "8080"), ("BurrowSSH", "22"), ("BurrowIperf", "5201"))


def ensure_forwards(r, host, room):
    """Keep this Pi reachable from the Portal LAN without a cable turn: TCP 8080 (dashboard),
    22 (ssh) and 5201 (iperf3, throughput tests) on the Tunnel's WAN side forward to the Pi
    at .10. Never on the Portal
    itself (room 0): its WAN is the school net. Returns the ports added this run."""
    if room not in (1, 2, 3):
        return []
    pi = host.rsplit(".", 1)[0] + ".10"
    have = (r.call("firewall", "get_port_forward_list") or {}).get("res") or []
    added = []
    for name, port in FORWARDS:
        if any(f.get("src_dport") == port and f.get("dest_ip") == pi and f.get("proto") == "tcp" for f in have):
            continue
        r.call("firewall", "add_port_forward", {"name": name, "proto": "tcp", "src": "wan", "src_dport": port,
                                                "dest": "lan", "dest_ip": pi, "dest_port": port, "enabled": True})
        added.append(port)
    return added


def main(now=None, router_factory=None, cloud_check=cloud_reachable, wifi_factory=None):
    now = now or time.time()
    cfg = load_json(CONFIG, None)
    if cfg is None:
        print("no config at", CONFIG)
        return 0
    bcfg = load_json(BURROW_CONFIG, {})
    cloud_url = cfg.get("cloud_url") or (bcfg.get("cloud") or {}).get("url")
    st = load_json(STATE, {})
    st["last_check"] = int(now)
    upstreams = upstreams_of(cfg)
    wifi = (wifi_factory or WifiFallback)(cfg.get("wifi_fallback"))

    cloud_ok = cloud_check(cloud_url)
    st["cloud_ok"] = cloud_ok

    r = (router_factory or glinet.Router)(cfg["host"], timeout=8)
    try:
        r.login(cfg["password"])
        status = r.call("repeater", "get_status") or {}
    except Exception as e:
        # The Opal's LAN itself is gone: nothing to join or reboot, just report
        # and get our own radio up so the report leaves the building.
        st["opal_reachable"] = False
        st["state"] = "opal-unreachable"
        if not st.get("down_since"):      # a healthy run leaves None behind; setdefault would keep it
            st["down_since"] = int(now)
        event(st, now, "opal %s unreachable: %s" % (cfg["host"], str(e)[:100]))
        _maybe_wifi(st, wifi, now, cloud_ok)
        save_state(st)
        return 0

    st["opal_reachable"] = True
    st["repeater"] = {k: status.get(k) for k in ("state_s", "ssid", "signal", "band") if k in status}
    ip4 = status.get("ipv4") or {}
    if isinstance(ip4, dict) and ip4.get("ip"):
        st["repeater"]["ip"] = ip4.get("ip")
    st.update(opal_facts(r))
    try:
        for port in ensure_forwards(r, cfg["host"], bcfg.get("room")):
            event(st, now, "port forward added: tcp %s -> Pi" % port)
    except Exception as e:
        print("forwards: %s" % e)

    what = decide(status, cloud_ok, st.get("last_join_at"), now)
    if what == "ok":
        if st.get("down_since"):
            event(st, now, "recovered after %d min (%d reboots)"
                  % ((now - st["down_since"]) / 60, len(st.get("reboots") or [])))
        st["state"] = "ok"
        st["down_since"] = None
        st["reboots"] = []
        st["last_ok"] = int(now)
        if wifi.available() and wifi.is_up():
            wifi.down()
            event(st, now, "cable healthy again: Wi-Fi fallback dropped")
        st["wifi_fallback"] = "off" if wifi.available() else "unavailable"
        if cloud_ok:
            kick_chrony_if_stale(st, now)
        save_state(st)
        print("ok: %s via %s (%s dBm), cloud %s" % (cfg["host"], status.get("ssid"), status.get("signal"), cloud_ok))
        return 0

    if not st.get("down_since"):      # a healthy run leaves None behind; setdefault would keep it
        st["down_since"] = int(now)
    st["state"] = "upstream-down" if status.get("state_s") != "connected" else "no-internet"

    if what == "wait":
        print("repeater %s; join sent %ds ago, waiting" % (status.get("state_s"), now - st["last_join_at"]))
    else:
        visible = None
        try:
            r.timeout = 40
            scan = r.call("repeater", "scan") or {}
            visible = {x.get("ssid") for x in (scan.get("res") or scan.get("list") or []) if x.get("ssid")}
        except Exception:
            visible = None          # scan failed: try the preferred upstream blind
        # a hidden upstream we dialed blind last time and that did not connect:
        # move on down the list this run (visible ones are simply retried)
        missed = None
        if what == "join" and st.get("last_join_at"):
            hidden = {u.get("ssid") for u in upstreams if u.get("hidden")}
            if st.get("last_join_ssid") in hidden:
                missed = st["last_join_ssid"]
        up = pick_upstream(upstreams, visible, status.get("ssid"), current_failed=(what == "switch"), skip_ssid=missed)
        if up is None:
            up = pick_upstream(upstreams, visible)   # nothing else visible: re-try the one we have
        if up is None:
            event(st, now, "repeater %s and no configured upstream visible (%s)"
                  % (status.get("state_s"), ", ".join(sorted(visible or [])) or "scan empty"))
        else:
            try:
                r.timeout = 40
                r.call("repeater", "connect", connect_params(up))
                event(st, now, "repeater %s: joined %s" % (status.get("state_s"), up.get("ssid")))
            except Exception as e:
                event(st, now, "join %s failed: %s" % (up.get("ssid"), str(e)[:100]))
            st["last_join_at"] = int(now)
            st["last_join_ssid"] = up.get("ssid")

    reboots = st.get("reboots") or []
    if reboots and now - reboots[-1] < REBOOT_SETTLE_S:
        pass                        # it is still coming back up; judge it next run
    elif should_reboot(st["down_since"], reboots, now):
        try:
            r.timeout = 20
            r.call("system", "reboot")
            event(st, now, "down %d min: rebooted the Opal (#%d)" % ((now - st["down_since"]) / 60, len(reboots) + 1))
        except Exception as e:
            event(st, now, "reboot request failed: %s" % str(e)[:100])
        reboots.append(int(now))
        st["reboots"] = reboots
        st["last_join_at"] = int(now)   # a fresh boot needs its 90 s before we join again
    st["next_reboot_at"] = int(reboot_due_at(st["down_since"], st.get("reboots") or []))

    _maybe_wifi(st, wifi, now, cloud_ok)
    save_state(st)
    return 0


def _maybe_wifi(st, wifi, now, cloud_ok):
    if not wifi.available():
        st["wifi_fallback"] = "unavailable"
        return
    if wifi.is_up():
        st["wifi_fallback"] = "up"
        return
    if st.get("down_since") and now - st["down_since"] >= WIFI_AFTER_S and not cloud_ok:
        bssid = wifi.up(st.get("own_bssids") or [])
        if bssid:
            st["wifi_fallback"] = "up"
            event(st, now, "Wi-Fi fallback up via %s" % bssid)
        else:
            st["wifi_fallback"] = "no-ap"
            event(st, now, "Wi-Fi fallback: no other WormHole access point in range")
    else:
        st["wifi_fallback"] = "off"


if __name__ == "__main__":
    sys.exit(main())
