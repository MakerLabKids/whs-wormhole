#!/usr/bin/env python3
"""roles.py: who this Pi is in its room, and keeping it that way without breaking anything.

An extra Pi must never break a room (2026-11-01). Three cases, checked every 2 minutes
(burrow-role.timer, as root), plus the shared "apply an identity" used at first boot:

  standby  (burrow.json "role": "standby"; burrowN-sb-xxxx, DHCP, no tunnel, no Opal watchdog)
           Nothing has answered at the room's .10 for PROMOTE_AFTER_S: ask the Surface to take
           over (POST /v1/edge/enrol promote: true). It agrees only if the room's Pi has not
           reported for 10 min; then become burrowN (its .10, its tunnel) and reboot. Data kept.
  primary  on ANOTHER room's Opal (its static .10 does not fit: the gateway does not answer for
           GUEST_AFTER_S): switch eth0 to DHCP and stay itself, a guest on that network, still
           uploading. On its own network again (or no address at all), back to its static .10.
  primary  whose token the Surface refuses (HTTP 401, someone took over) for DEMOTE_AFTER_S:
           ask again and become what the Surface says (a standby). Data kept.

    roles.py tick              the periodic check (the timer runs this)
    roles.py apply FILE        apply an identity file {edge, room, role, cloud_token, tunnel_token}
                               (first-boot-identity.sh calls this; prints nothing secret)
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

CFG = os.environ.get("BURROW_CONFIG", "/etc/burrow/burrow.json")
TUNNEL = os.environ.get("TUNNEL_CONFIG", "/etc/burrow/tunnel.json")
STATE = os.environ.get("BURROW_ROLE_STATE", "/data/burrow/role-state.json")
CLOUD_TOKEN = os.environ.get("BURROW_CLOUD_TOKEN", "/etc/burrow/cloud.token")
TUNNEL_TOKEN = os.environ.get("BURROW_TUNNEL_TOKEN", "/etc/cloudflared/token")
SECRET = os.environ.get("BURROW_ENROL_SECRET", "/etc/burrow/enrol.secret")
EVENTS = os.environ.get("BURROW_ROLE_LOG", "/data/burrow/role-events.log")
HOSTS = os.environ.get("BURROW_HOSTS", "/etc/hosts")

PROMOTE_AFTER_S = 6 * 60      # the room's .10 silent this long: ask to take over (the Surface also wants 10 min)
GUEST_AFTER_S = 5 * 60        # our gateway silent this long with the cable in: try DHCP (an Opal reboot is ~2 min)
DEMOTE_AFTER_S = 10 * 60      # our token refused this long: ask who we are now


def load(path, dflt):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return dflt


def save(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, path)


def log(text):
    line = "%s %s" % (time.strftime("%Y-%m-%dT%H:%M:%S"), text)
    print(line)
    try:
        with open(EVENTS, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---- the world, behind small functions the tests replace ------------------
class System:
    def run(self, *cmd, timeout=30):
        try:
            p = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, str(e)

    def http_ok(self, url, timeout=3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return 200 <= r.status < 500
        except urllib.error.HTTPError:
            return True                 # it answered
        except Exception:
            return False

    def ping(self, ip):
        return self.run("ping", "-c", "1", "-W", "2", ip, timeout=5)[0] == 0

    def eth_ipv4(self):
        rc, out = self.run("ip", "-4", "-o", "addr", "show", "eth0")
        for part in out.split():
            if part.count(".") == 3 and "/" in part:
                return part.split("/")[0]
        return None

    def carrier(self):
        try:
            with open("/sys/class/net/eth0/carrier") as f:
                return f.read().strip() == "1"
        except OSError:
            return False

    def eth_con(self):
        rc, out = self.run("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show")
        for line in out.splitlines():
            name, _, dev = line.rpartition(":")
            if dev == "eth0":
                return name
        return None

    def cloud_error(self):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/api/status", timeout=5) as r:
                return ((json.load(r).get("cloud") or {}).get("error")) or None
        except Exception:
            return None

    def enrol(self, url, body):
        req = urllib.request.Request(url.rstrip("/") + "/v1/edge/enrol", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    def serial(self):
        for p in ("/sys/firmware/devicetree/base/serial-number",):
            try:
                with open(p) as f:
                    return f.read().strip("\x00\n ")
            except OSError:
                pass
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("Serial"):
                        return line.split(":")[1].strip()
        except OSError:
            pass
        return None

    def mac(self, dev):
        try:
            with open("/sys/class/net/%s/address" % dev) as f:
                return f.read().strip()
        except OSError:
            return ""

    def reboot(self):
        self.run("systemctl", "reboot")


# ---- applying an identity --------------------------------------------------
def apply_identity(ident, sys_=None, net=True):
    """Become ident {edge, room, role?, cloud_token?, tunnel_token?}: burrow.json, tokens, tunnel,
    hostname, the cable address (primary: static .10; standby: DHCP). Never touches /data."""
    sys_ = sys_ or System()
    edge, room = ident["edge"], int(ident["room"])
    role = ident.get("role") or "primary"
    cfg = load(CFG, {})
    cfg.update(edge=edge, room=room, role=role)
    cfg["peers"] = {("burrow%d" % k): {"url": "http://192.168.80.%d:8080" % (10 if k == 0 else 20 + k)}
                    for k in range(4) if "burrow%d" % k != edge}
    save(CFG, cfg)
    if ident.get("cloud_token"):
        write_secret(CLOUD_TOKEN, ident["cloud_token"])
    if role == "primary" and ident.get("tunnel_token"):
        write_secret(TUNNEL_TOKEN, ident["tunnel_token"])
        sys_.run("systemctl", "enable", "cloudflared")
    else:
        # a clone carries the donor's tunnel token: running it would join THAT room's tunnel and
        # take some of its traffic. No token of our own (a standby, or a room with none): none at all.
        try:
            os.remove(TUNNEL_TOKEN)
        except OSError:
            pass
        sys_.run("systemctl", "disable", "--now", "cloudflared")
    t = load(TUNNEL, None)
    if t is not None:
        t["host"] = "192.168.8%d.1" % room
        if room == 0:
            t["upstreams"] = [u for u in (t.get("upstreams") or []) if u.get("ssid") != "WormHole-Core"]
        save(TUNNEL, t)
    sys_.run("hostnamectl", "set-hostname", edge)
    set_hosts(edge)
    if net:
        con = sys_.eth_con()
        if con and role == "primary":
            sys_.run("nmcli", "connection", "modify", con, "ipv4.method", "manual",
                     "ipv4.addresses", "192.168.8%d.10/24" % room, "ipv4.gateway", "192.168.8%d.1" % room,
                     "ipv4.dns", "192.168.8%d.1" % room)
        elif con:
            sys_.run("nmcli", "connection", "modify", con, "ipv4.method", "auto",
                     "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", "")
    log("identity: %s (room %d, %s)" % (edge, room, role))
    return cfg


def write_secret(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(value)
    os.chmod(path, 0o600)


def set_hosts(edge, path=None):
    path = path or HOSTS
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except OSError:
        return
    out = [l for l in lines if not l.startswith("127.0.1.1")] + ["127.0.1.1\t%s" % edge]
    try:
        with open(path, "w") as f:
            f.write("\n".join(out) + "\n")
    except OSError:
        pass


# ---- the periodic check ------------------------------------------------------
def ask(sys_, cfg, promote):
    secret = (open(SECRET).read().strip() if os.path.exists(SECRET) else "")
    url = (cfg.get("cloud") or {}).get("url") or "https://whs.makerlabkids.com"
    body = {"secret": secret, "serial": sys_.serial(), "room": int(cfg["room"]),
            "eth_mac": sys_.mac("eth0"), "wlan_mac": sys_.mac("wlan0")}
    if promote:
        body["promote"] = True
    r = sys_.enrol(url, body)
    return {"edge": r["edge"], "room": r["room"], "role": r.get("role") or "primary",
            "cloud_token": r["token"], "tunnel_token": r.get("tunnel_token")}


def tick(now=None, sys_=None):
    """One check. Returns what it did: 'ok', 'waiting', 'promoted', 'demoted', 'guest', 'home', 'error: ...'."""
    sys_ = sys_ or System()
    now = now or time.time()
    cfg = load(CFG, {})
    if "edge" not in cfg or "room" not in cfg:
        return "no identity yet"
    st = load(STATE, {})
    room = int(cfg["room"])
    role = cfg.get("role") or "primary"
    out = "ok"

    if role == "standby":
        home = "192.168.8%d.10" % room
        alive = sys_.http_ok("http://%s:8080/health" % home) or sys_.ping(home)
        if alive:
            st["primary_gone_since"] = None
        else:
            st["primary_gone_since"] = st.get("primary_gone_since") or now
            if now - st["primary_gone_since"] >= PROMOTE_AFTER_S:
                try:
                    ident = ask(sys_, cfg, promote=True)
                except Exception as e:
                    out = "error: %s" % str(e)[:80]
                else:
                    if ident["role"] == "primary":
                        log("standby: burrow%d silent %d min and the Surface agrees: taking over" % (room, (now - st["primary_gone_since"]) / 60))
                        apply_identity(ident, sys_)
                        st["primary_gone_since"] = None
                        save(STATE, st)
                        sys_.reboot()
                        return "promoted"
                    out = "waiting"          # the Surface still hears the room's Pi
            else:
                out = "waiting"
        save(STATE, st)
        return out

    # primary: 1. a guest on another room's network?
    gw = "192.168.8%d.1" % room
    ip = sys_.eth_ipv4()
    if st.get("guest"):
        if ip and ip.startswith("192.168.8%d." % room):
            log("guest: back on our own network (%s): static .10 again" % ip)
            set_static(sys_, room)
            st["guest"] = False
            out = "home"
        elif not ip and now - (st.get("guest_since") or now) >= GUEST_AFTER_S:
            log("guest: no address from any Opal: static .10 again")
            set_static(sys_, room)
            st["guest"] = False
            out = "home"
        else:
            out = "guest"
    elif sys_.carrier() and not (sys_.ping(gw) or sys_.http_ok("http://%s/" % gw)):   # either answer will do
        st["gw_gone_since"] = st.get("gw_gone_since") or now
        if now - st["gw_gone_since"] >= GUEST_AFTER_S:
            con = sys_.eth_con()
            if con:
                log("guest: our gateway %s silent %d min with the cable in: trying DHCP (another room's Opal?)" % (gw, (now - st["gw_gone_since"]) / 60))
                sys_.run("nmcli", "connection", "modify", con, "ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", "", "ipv4.dns", "")
                sys_.run("nmcli", "connection", "up", con, timeout=60)
                st["guest"], st["guest_since"], st["gw_gone_since"] = True, now, None
                out = "guest"
    else:
        st["gw_gone_since"] = None

    # 2. replaced? (our token refused)
    err = sys_.cloud_error()
    if err and "401" in str(err):
        st["refused_since"] = st.get("refused_since") or now
        if now - st["refused_since"] >= DEMOTE_AFTER_S:
            try:
                ident = ask(sys_, cfg, promote=False)
            except Exception as e:
                save(STATE, st)
                return "error: %s" % str(e)[:80]
            log("replaced: the Surface refused our token %d min; it says we are %s (%s) now" % ((now - st["refused_since"]) / 60, ident["edge"], ident["role"]))
            apply_identity(ident, sys_)
            st["refused_since"] = None
            save(STATE, st)
            sys_.reboot()
            return "demoted" if ident["role"] == "standby" else "re-enrolled"
    else:
        st["refused_since"] = None
    save(STATE, st)
    return out


def set_static(sys_, room):
    con = sys_.eth_con()
    if con:
        sys_.run("nmcli", "connection", "modify", con, "ipv4.method", "manual",
                 "ipv4.addresses", "192.168.8%d.10/24" % room, "ipv4.gateway", "192.168.8%d.1" % room,
                 "ipv4.dns", "192.168.8%d.1" % room)
        sys_.run("nmcli", "connection", "up", con, timeout=60)


def main(argv):
    if len(argv) >= 3 and argv[1] == "apply":
        apply_identity(load(argv[2], {}))
        return 0
    if len(argv) >= 2 and argv[1] == "tick":
        print(tick())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
