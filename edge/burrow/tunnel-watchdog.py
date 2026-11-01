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
NEEDS_IDENTITY = os.environ.get("BURROW_NEEDS_IDENTITY", "/etc/burrow/needs-identity")  # clone-card.sh write; removed by first-boot-identity.sh
STATE = os.environ.get("TUNNEL_STATE", "/run/tunnel-watchdog.json")

HOLDOFF_S = 90            # do not re-send a join while one may still be in progress
SWITCH_AFTER_S = 100      # connected but no cloud: switch upstream only when it lasts this long (two runs);
                          # 2026-11-01 10:00 ONE failed 8 s check moved Tunnel 1 off a healthy backhaul
RETURN_AFTER_S = 15 * 60  # rooms 1-3 on a fallback (Loki/BYLD) with good internet this long: try the backhaul again
RETURN_MAX_BACKOFF_S = 4 * 3600
REBOOT_AFTER_S = 15 * 60  # first reboot: 15 min of failure despite joins
REBOOT_HOURLY_N = 3       # then once an hour, this many times...
REBOOT_DAILY_S = 86400    # ...then once a day, forever
REBOOT_MIN_GAP_S = 3600   # never two reboots within an hour
REBOOT_SETTLE_S = 240     # after a reboot, give the Opal this long before judging it
WIFI_AFTER_S = 90         # bring the Pi's own Wi-Fi up after this long down (the next 2-min run after the first miss: 2-4 min after the outage)
# Election, decentralised: an Opal offers the backhaul (its hidden WormHole-Core)
# only after PROBATION_S of clean internet on its own upstream, drops the offer
# after DROP_AFTER_S without internet, and may not offer again for BAR_S.
# Followers join the strongest offer they hear. No vote: whoever is good, is.
PROBATION_S = 10 * 60
DROP_AFTER_S = 2 * 60
BAR_S = 30 * 60
BACKHAUL_IFACE = "default_radio1"     # the 5 GHz iface that carries WormHole-Core (wifi get_config)
ELECTION_ACTS = False                 # observe-only until a follower can safely lose its AP (see backhaul_election)
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


def backhaul_election(r, st, now, cloud_ok, status):
    """Offer or withdraw this Opal's backhaul by its own measured internet.
    st keeps: clean_since (first clean check in the current run of good ones),
    bad_since, backhaul ("on"/"off"/"barred"), barred_until. Only an Opal on
    a real upstream (not itself a follower on WormHole-Core) can offer."""
    on_backhaul = (status.get("ssid") or "") == "WormHole-Core"
    if cloud_ok and not on_backhaul:
        if not st.get("clean_since"):
            st["clean_since"] = int(now)
        st["bad_since"] = None
    else:
        st["clean_since"] = None
        if not st.get("bad_since"):
            st["bad_since"] = int(now)
    want = None
    if st.get("barred_until") and now < st["barred_until"]:
        want = False
        st["backhaul"] = "barred"
    elif st.get("clean_since") and now - st["clean_since"] >= PROBATION_S:
        want = True
    elif st.get("bad_since") and now - st["bad_since"] >= DROP_AFTER_S:
        want = False
    # 2026-11-01: switching a follower's own backhaul AP off left it unable to rejoin WormHole-Core
    # (radio1 STA) after its next drop, and the Tunnels are pinned to the Portal's BSSID anyway, so a
    # new provider could not be followed. Until both are solved the election only REPORTS who would
    # qualify (st["backhaul_candidate"]), and switches a disabled backhaul AP back ON (heal).
    st["backhaul_candidate"] = bool(want)
    if not ELECTION_ACTS:
        try:
            cfg = r.call("wifi", "get_config") or {}
            for radio in cfg.get("res", []):
                for i in radio.get("ifaces", []):
                    if i.get("name") == BACKHAUL_IFACE and not i.get("enabled"):
                        old_timeout = getattr(r, "timeout", None)
                        try:
                            r.timeout = 60
                            try:
                                r.call("wifi", "set_config", {"iface_name": BACKHAUL_IFACE, "enabled": True})
                            except Exception:
                                pass
                        finally:
                            if old_timeout is not None:
                                r.timeout = old_timeout
                        event(st, now, "backhaul AP %s was off: switched back on (heal)" % BACKHAUL_IFACE)
        except Exception as e:
            event(st, now, "backhaul heal check failed: %s" % str(e)[:80])
        return
    if want is None:
        return
    try:
        cfg = r.call("wifi", "get_config") or {}
        cur = None
        for radio in cfg.get("res", []):
            for i in radio.get("ifaces", []):
                if i.get("name") == BACKHAUL_IFACE:
                    cur = bool(i.get("enabled"))
        if cur is None or cur == want:
            if cur is not None:
                st["backhaul"] = "on" if want else ("barred" if st.get("backhaul") == "barred" else "off")
            return
        # GL.iNet 4.x: flat {iface_name, enabled} (read from the router's rpc/wifi; the nested
        # {"ifaces": [...]} form get_config returns is a 500). Proven on Tunnel 1, 2026-11-01:
        # toggling an AP iface leaves the repeater link up.
        # applying a Wi-Fi change restarts the radio: give it a minute, and if the call
        # itself times out, believe the router's state rather than the timeout
        old_timeout = getattr(r, "timeout", None)
        try:
            r.timeout = 60
            try:
                r.call("wifi", "set_config", {"iface_name": BACKHAUL_IFACE, "enabled": bool(want)})
            except Exception:
                time.sleep(5)
                now_on = None
                for radio in (r.call("wifi", "get_config") or {}).get("res", []):
                    for i in radio.get("ifaces", []):
                        if i.get("name") == BACKHAUL_IFACE:
                            now_on = bool(i.get("enabled"))
                if now_on != want:
                    raise
        finally:
            if old_timeout is not None:
                r.timeout = old_timeout
        if want:
            st["backhaul"] = "on"
            event(st, now, "backhaul offered: %d min of clean internet on %s" % (PROBATION_S // 60, status.get("ssid") or "?"))
        else:
            st["backhaul"] = "barred" if not cloud_ok else "off"
            if not cloud_ok:
                st["barred_until"] = int(now + BAR_S)
                event(st, now, "backhaul withdrawn: no internet for %d min; not offered again for %d min" % (DROP_AFTER_S // 60, BAR_S // 60))
    except Exception as e:
        event(st, now, "backhaul toggle failed: %s" % str(e)[:80])


PORTAL_SILENT_KICK_S = 600      # no Tunnel's Pi reachable over the Portal LAN this long -> kick the backhaul AP
PORTAL_KICK_EVERY_S = 3600      # at most one kick an hour


def tcp_reachable(url, timeout=3):
    """True if the host:port in an http URL accepts a TCP connection."""
    import socket
    from urllib.parse import urlparse
    u = urlparse(url)
    try:
        with socket.create_connection((u.hostname, u.port or 80), timeout=timeout):
            return True
    except OSError:
        return False


def set_backhaul_ap(r, enabled):
    """Flat GL.iNet 4.x wifi set_config on the backhaul AP iface. Applying it restarts the
    radio and the call often times out while still applying: read the state back."""
    old_timeout = getattr(r, "timeout", None)
    try:
        r.timeout = 60
        try:
            r.call("wifi", "set_config", {"iface_name": BACKHAUL_IFACE, "enabled": bool(enabled)})
        except Exception:
            time.sleep(5)
            for radio in (r.call("wifi", "get_config") or {}).get("res", []):
                for i in radio.get("ifaces", []):
                    if i.get("name") == BACKHAUL_IFACE and bool(i.get("enabled")) == bool(enabled):
                        return
            raise
    finally:
        if old_timeout is not None:
            r.timeout = old_timeout


def portal_backhaul_watch(r, st, now, bcfg, reachable=tcp_reachable):
    """Room 0 only (this Pi is cabled to the Portal, which IS the backhaul AP). 2026-11-01:
    after burrow0 switched the Portal's upstream (Loki -> Guess) the Portal's WormHole-Core AP
    kept the one Tunnel already on it but refused every new association for an hour; Tunnels 1
    and 3 fell back to Loki, Tunnel 2 sat dark after a reboot. Restarting that AP fixed it at
    once. So: if no Tunnel's Pi has been reachable over the Portal LAN for 10 min, switch the
    backhaul AP off and on (at most hourly). If every Tunnel has legitimately gone elsewhere,
    nobody is on the AP and the kick costs nothing."""
    if bcfg.get("room") != 0:
        return
    # burrow.json peers are "name": "http://..." (hand-made) or "name": {"url": ...} (first-boot-identity)
    peers = [p if isinstance(p, str) else (p or {}).get("url") for p in (bcfg.get("peers") or {}).values()]
    peers = [u for u in peers if u]
    if not peers:
        return
    if any(reachable(u) for u in peers):
        st["backhaul_peers_seen_at"] = int(now)
        return
    seen = st.setdefault("backhaul_peers_seen_at", int(now))     # first run after boot: start the clock
    kicked = st.get("backhaul_kicked_at")
    if now - seen < PORTAL_SILENT_KICK_S or (kicked and now - kicked < PORTAL_KICK_EVERY_S):
        return
    st["backhaul_kicked_at"] = int(now)
    try:
        set_backhaul_ap(r, False)
        time.sleep(5)
        set_backhaul_ap(r, True)
        event(st, now, "no Tunnel reachable over the Portal for %d min: backhaul AP restarted" % ((now - seen) // 60))
    except Exception as e:
        try:
            set_backhaul_ap(r, True)        # never leave it off
        except Exception:
            pass
        event(st, now, "backhaul AP restart failed: %s" % str(e)[:80])


def ensure_auto_connect(r, st, now):
    """The Opal must rejoin its saved networks by itself after a power cycle
    (repeater config "auto"); a Tunnel with it off sits flashing white until
    this watchdog runs, which is minutes after ITS Pi boots, or never if the
    Pi is down (2026-10-31). Switch it on whenever it is found off."""
    try:
        rc = r.call("repeater", "get_config") or {}
    except Exception:
        return
    if isinstance(rc, dict) and "auto" in rc and not rc.get("auto"):
        try:
            r.call("repeater", "set_config", {"auto": True})
            event(st, now, "opal auto-connect was off: switched on")
        except Exception as e:
            event(st, now, "could not switch opal auto-connect on: %s" % str(e)[:80])


def connect_params(up):
    # remember: GL.iNet only adds a network to its saved list (the one its own auto-connect
    # walks when the uplink drops) when the join says so. Without it every Opal's saved list
    # was empty (checked 2026-11-01 on the Portal and Tunnel 3), so "auto-connect" had nothing
    # to reconnect to, hidden or not. A saved hidden network keeps its directed-scan flag.
    params = {k: up[k] for k in ("ssid", "key", "bssid", "device", "band", "encryption") if up.get(k)}
    params["remember"] = True
    # manual: the saved network GL.iNet's auto-connect returns to after an outage is the one
    # flagged manual, i.e. the last one joined. A join WITHOUT this flag sometimes left the flag
    # on the previous network (Tunnel 2, 2026-11-01 11:2x: on WormHole-Core, flag still on Loki,
    # which is how Tunnel 1 stayed on Loki after a 60 s backhaul cut); with it the flag always
    # moves. (manual: false does not keep it off a fallback: the join takes it anyway.)
    params["manual"] = True
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


def decide(status, cloud_ok, last_join_at, now, no_cloud_since=None):
    """'ok' | 'hold' | 'join' | 'switch' | 'wait'.
    connected + cloud -> ok. connected, no cloud -> hold until that has lasted
    SWITCH_AFTER_S (no_cloud_since), then switch upstream (after holdoff).
    not connected -> join (after holdoff)."""
    connected = (status or {}).get("state_s") == "connected"
    if connected and cloud_ok is not False:      # None = no cloud_url to check against
        return "ok"
    if connected and (no_cloud_since is None or now - no_cloud_since < SWITCH_AFTER_S):
        return "hold"
    if last_join_at and now - last_join_at < HOLDOFF_S:
        return "wait"
    return "switch" if connected else "join"


def return_home(r, st, now, upstreams, status, cloud_ok):
    """Rooms 1-3 (preferred upstream WormHole-Core): after RETURN_AFTER_S on a fallback with good
    internet, rejoin the backhaul, but only when a scan shows the Portal (its BSSID prefix). Each try doubles the wait
    (to RETURN_MAX_BACKOFF_S); arriving home resets it. A failed join falls back by the usual path
    (the hidden-miss rule moves on to the next upstream next run)."""
    pref = upstreams[0] if upstreams else None
    if not pref or pref.get("ssid") != "WormHole-Core":
        return None
    if status.get("ssid") == pref.get("ssid"):
        st["off_home_since"] = None
        st["home_backoff"] = None
        return None
    if status.get("state_s") != "connected" or cloud_ok is not True:
        return None
    st["off_home_since"] = st.get("off_home_since") or int(now)
    if now - st["off_home_since"] < RETURN_AFTER_S:
        return None
    backoff = st.get("home_backoff") or RETURN_AFTER_S
    if st.get("home_try_at") and now - st["home_try_at"] < backoff:
        return None
    st["home_try_at"] = int(now)
    want = (pref.get("bssid") or "").lower()
    if want:
        old_timeout = getattr(r, "timeout", None)
        try:
            r.timeout = 40
            scan = r.call("repeater", "scan") or {}
        finally:
            if old_timeout is not None:
                r.timeout = old_timeout
        # The Opal's scan leaves hidden networks out (2026-11-01: 17 results, no WormHole-Core), so
        # look for the Portal itself: any BSSID of the same radio (first five bytes), e.g. its 2.4 GHz WormHole.
        prefix = want[:14]
        seen = [(x.get("bssid") or "").lower() for x in (scan.get("res") or scan.get("list") or [])]
        if not any(b.startswith(prefix) for b in seen):
            print("return home: no sign of the Portal (%s*) in the scan, staying on %s" % (prefix, status.get("ssid")))
            return "not-seen"
    st["home_backoff"] = min(backoff * 2, RETURN_MAX_BACKOFF_S)
    old_timeout = getattr(r, "timeout", None)
    try:
        r.timeout = 40
        r.call("repeater", "connect", connect_params(pref))
    finally:
        if old_timeout is not None:
            r.timeout = old_timeout
    st["last_join_at"] = int(now)
    st["last_join_ssid"] = pref.get("ssid")
    event(st, now, "back to the backhaul: %d min on %s with good internet"
          % ((now - st["off_home_since"]) / 60, status.get("ssid")))
    return "joined"


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


def same_opal(bssid, mac):
    """Is `bssid` an access point of the Opal whose station MAC is `mac`?
    GL.iNet derives them from one block: middle four octets equal, last
    octet within 2 (station 92:83:c4:84:ff:37 -> AP 94:83:c4:84:ff:37)."""
    if not bssid or not mac:
        return False
    a, b = bssid.lower().split(":"), mac.lower().split(":")
    if len(a) != 6 or len(b) != 6 or a[1:5] != b[1:5]:
        return False
    try:
        return abs(int(a[5], 16) - int(b[5], 16)) <= 2
    except ValueError:
        return False


def choose_fallback_bssid(scan_rows, ssid, exclude_bssids, own_mac=None):
    """Strongest access point for `ssid` that is not our own Opal's.
    scan_rows: [(bssid, ssid, signal_int)]."""
    ex = {b.lower() for b in exclude_bssids if b}
    best = None
    for bssid, s, sig in scan_rows:
        if s != ssid or not bssid or bssid.lower() in ex or same_opal(bssid, own_mac):
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
def cloud_reachable_via(url, iface, timeout=8):
    """The Surface answers through this interface (curl --interface): judges ONE path, so the
    Pi's Wi-Fi can neither fake nor mask the cable path, nor be trusted before it is proven."""
    if not url:
        return None
    try:
        out = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--interface", iface,
                              "--max-time", str(timeout), url.rstrip("/") + "/v1/edge/ping"],
                             capture_output=True, text=True, timeout=timeout + 4)
        return out.stdout.strip() not in ("", "000")
    except (OSError, subprocess.TimeoutExpired):
        return False


def cloud_reachable_cable(url, timeout=8):
    """The cable path (eth0). Falls back to the default route where there is no curl."""
    import shutil
    if shutil.which("curl") and os.path.exists("/sys/class/net/eth0"):
        return cloud_reachable_via(url, "eth0", timeout)
    return cloud_reachable(url, timeout)


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

    def __init__(self, cfg, run=nmcli, upstreams=None):
        self.cfg = cfg or {}
        self.run = run
        self.iface = self.cfg.get("iface", "wlan0")
        # the ladder when no other WormHole is in range: the Opal's own upstreams
        # (phone hotspot, school net, home nets), with their keys
        self.ladder = [u for u in (upstreams or []) if u.get("ssid") and u.get("ssid") != "WormHole-Core"]

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
        for _ in range(12):                    # the radio comes up "unavailable" for a second or two
            rc, out = self.run("-t", "-f", "DEVICE,STATE", "device", "status")
            st = [l.split(":")[1] for l in out.splitlines() if l.split(":")[0] == self.iface and ":" in l]
            if rc == 0 and st and st[0] != "unavailable":
                break
            time.sleep(1)
        self.run("device", "wifi", "rescan", "ifname", self.iface, timeout=20)
        time.sleep(6)
        rc, out = self.run("-t", "-f", "BSSID,SSID,SIGNAL", "device", "wifi", "list", "ifname", self.iface)
        return parse_nmcli_scan(out) if rc == 0 else []

    def up(self, exclude_bssids, own_mac=None, cloud_url=None, verify=None):
        """Join a way out that really reaches the internet: other WormHole
        access points strongest first (never our own Opal's), then the
        upstream ladder (hotspot, school, home) by name. Each join is proven
        over wlan0 before it is kept; a WormHole whose Opal has no internet
        (2026-11-01: burrow1 joined Tunnel 2's, which had none, and its Wi-Fi
        took the default route into a dead end) is dropped and the next one
        tried. Returns what was joined (a bssid, or an ssid), or None with
        the Wi-Fi down."""
        verify = verify or (lambda: cloud_reachable_via(cloud_url, self.iface) if cloud_url else True)
        seen = self.scan()
        persist_event("wifi fallback: scan saw %d access points (%s)" % (len(seen), ", ".join(sorted({r[1] for r in seen if r[1]}))[:120]), time.time())
        tried = set()
        for _ in range(4):
            bssid = choose_fallback_bssid(seen, self.cfg["ssid"], list(exclude_bssids) + list(tried), own_mac)
            if not bssid:
                break
            tried.add(bssid)
            if self._join(self.cfg["ssid"], self.cfg["key"], bssid):
                time.sleep(3)
                if verify():
                    persist_event("wifi fallback: %s reaches the internet: keeping it" % bssid, time.time())
                    return bssid
                persist_event("wifi fallback: %s has no internet: next" % bssid, time.time())
        visible = {s[1] for s in seen if isinstance(s, (tuple, list)) and len(s) > 1}
        for u in self.ladder:
            if u.get("hidden") or u["ssid"] in visible:
                if self._join(u["ssid"], u.get("key", ""), None, open_net=(u.get("encryption") == "none")):
                    time.sleep(3)
                    if verify():
                        persist_event("wifi fallback: %s reaches the internet: keeping it" % u["ssid"], time.time())
                        return u["ssid"]
                    persist_event("wifi fallback: %s has no internet: next" % u["ssid"], time.time())
        persist_event("wifi fallback: nothing in range reaches the internet; Wi-Fi off", time.time())
        self.down()
        return None

    def _join(self, ssid, key, bssid, open_net=False):
        rc, out = self.run("-t", "-f", "NAME", "connection", "show")
        exists = rc == 0 and self.CON in out.splitlines()
        common = ["connection.autoconnect", "no", "ipv4.route-metric", "50", "ipv6.method", "disabled",
                  "802-11-wireless.ssid", ssid, "802-11-wireless.bssid", bssid or ""]
        if open_net:
            common += ["wifi-sec.key-mgmt", "none"]
        else:
            common += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", key or ""]
        if exists:
            self.run("connection", "modify", self.CON, *common)
        else:
            self.run("connection", "add", "type", "wifi", "ifname", self.iface, "con-name", self.CON, "ssid", ssid, *common)
        rc, out = self.run("connection", "up", self.CON, timeout=60)
        persist_event("wifi fallback: join %s %s -> rc %s %s" % (ssid, bssid or "", rc, (out or "").strip()[-120:]), time.time())
        return rc == 0

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


ALERT_WORDS = ("rebooted", "no configured upstream", "reboot request failed", "fallback")


def tell_burrow(text, now):
    """Hand the event to the Burrow on this Pi so it reaches the Surface now, not at the next
    snapshot. Level: alert when the Opal is being rebooted or nothing is reachable, else warn."""
    import urllib.request
    level = "alert" if any(w in text for w in ALERT_WORDS) else "warn"
    body = json.dumps({"kind": "opal", "level": level, "text": text, "data": {"at": int(now)}}).encode()
    try:
        req = urllib.request.Request("http://127.0.0.1:8080/api/event", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass


EVENT_LOG = os.environ.get("TUNNEL_EVENT_LOG", "/data/burrow/watchdog-events.log")


def persist_event(text, now):
    """Keep the watchdog's story on the data partition: the journal and /run are in RAM and a
    reboot (the usual cure) erases the evidence of why the cure was needed. Trimmed at ~200 KB."""
    try:
        if os.path.exists(EVENT_LOG) and os.path.getsize(EVENT_LOG) > 200_000:
            with open(EVENT_LOG) as f:
                keep = f.readlines()[-1000:]
            with open(EVENT_LOG, "w") as f:
                f.writelines(keep)
        with open(EVENT_LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), text))
    except Exception:
        pass


def event(st, now, text):
    """Append to the short event log; a repeat of the last line is folded into
    it with a count, so a join every 90 s cannot push a reboot out of view."""
    print(text)
    ev = st.setdefault("events", [])
    if not (ev and ev[-1][1] == text[:160]):
        tell_burrow(text, now)
        persist_event(text, now)
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
    try:
        # the Opal's station MAC (repeater get_config); its access points use the same
        # vendor block with the first octet and the last nibble shifted, which is how the
        # Surface tells "this follower is on that Opal's backhaul" (sameOpal in alerts.js)
        rc = r.call("repeater", "get_config") or {}
        if isinstance(rc, dict) and rc.get("macaddr"):
            facts["own_mac"] = str(rc["macaddr"]).lower()
    except Exception:
        pass
    try:
        # what the Opal's own auto-connect can fall back to with no Pi involved
        sv = r.call("repeater", "get_saved_ap_list") or {}
        lst = sv.get("res") if isinstance(sv, dict) else sv
        facts["saved_networks"] = [n.get("ssid") for n in (lst or []) if isinstance(n, dict)]
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


def main(now=None, router_factory=None, cloud_check=None, wifi_factory=None):
    cloud_check = cloud_check or cloud_reachable_cable
    now = now or time.time()
    if os.path.exists(NEEDS_IDENTITY):
        # a fresh clone: its tunnel.json is the donor's and points at the donor's Opal (for
        # burrow0's card, the Portal). Hands off until enrolment has made it someone.
        print("needs identity (fresh clone): watchdog idle")
        return 0
    if (load_json(BURROW_CONFIG, {}) or {}).get("role") == "standby":
        # an extra Pi in the room (roles.py): the room's own Pi steers this Opal; two
        # watchdogs joining and rebooting the same Opal would fight
        print("standby: the room's Pi runs the watchdog; idle")
        return 0
    cfg = load_json(CONFIG, None)
    if cfg is None:
        print("no config at", CONFIG)
        return 0
    bcfg = load_json(BURROW_CONFIG, {})
    cloud_url = cfg.get("cloud_url") or (bcfg.get("cloud") or {}).get("url")
    st = load_json(STATE, {})
    st["last_check"] = int(now)
    upstreams = upstreams_of(cfg)
    wifi = (wifi_factory or WifiFallback)(cfg.get("wifi_fallback")) if wifi_factory else WifiFallback(cfg.get("wifi_fallback"), upstreams=cfg.get("upstreams"))

    st["cloud_url"] = cloud_url
    cloud_ok = cloud_check(cloud_url)
    st["cloud_ok"] = cloud_ok

    r = (router_factory or glinet.Router)(cfg["host"], timeout=8)
    try:
        r.login(cfg["password"])
        status = r.call("repeater", "get_status") or {}
        ensure_auto_connect(r, st, now)
        st["provider_bssid"] = (status.get("bssid") or (status.get("wpa_status") or {}).get("bssid") or "").lower() or None
        backhaul_election(r, st, now, cloud_ok, status)
        portal_backhaul_watch(r, st, now, bcfg)
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

    if status.get("state_s") == "connected" and cloud_ok is False:
        st["no_cloud_since"] = st.get("no_cloud_since") or int(now)
    else:
        st["no_cloud_since"] = None
    what = decide(status, cloud_ok, st.get("last_join_at"), now, st.get("no_cloud_since"))
    if what == "hold":
        st["state"] = "no-internet?"
        if not st.get("down_since"):      # the outage clock starts at the first failed check
            st["down_since"] = int(now)
        save_state(st)
        print("connected via %s but the cloud check failed (%ds): checking again before switching"
              % (status.get("ssid"), now - st["no_cloud_since"]))
        return 0
    if what == "ok":
        try:
            return_home(r, st, now, upstreams, status, cloud_ok)
        except Exception as e:
            print("return home: %s" % str(e)[:100])
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
        if st.get("wifi_fallback") != "unavailable":
            event(st, now, "Pi Wi-Fi fallback UNAVAILABLE: no %s (dtoverlay=disable-wifi in config.txt? install.sh removes it; reboot)" % getattr(wifi, "iface", "wlan0"))
        st["wifi_fallback"] = "unavailable"
        return
    if wifi.is_up():
        st["wifi_fallback"] = "up"
        return
    if st.get("down_since") and now - st["down_since"] >= WIFI_AFTER_S and not cloud_ok:
        bssid = wifi.up(st.get("own_bssids") or [], own_mac=st.get("own_mac"), cloud_url=st.get("cloud_url"))
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
