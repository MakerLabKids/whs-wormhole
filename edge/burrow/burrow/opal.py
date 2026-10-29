"""OpalLink: this Pi's view of its own Opal, fresh enough to walk around with.

GET /api/signal asks the Opal (host + admin password from /etc/burrow/tunnel.json, the same
file the watchdog uses) for `repeater get_status`: the signal of ITS upstream link, which for
a Tunnel is the 5 GHz hop to the Portal and for the Portal is the school/home network. One
login session is kept and renewed when it dies; replies are cached for 300 ms so a dozen
phones polling twice a second cost the Opal one RPC call per 300 ms. The Portal also lists
its wireless clients with their signal when the firmware reports it (the Tunnels, seen from
the other end of each hop).
"""
import json
import os
import sys
import threading
import time

from . import util

try:
    import glinet                      # /opt/burrow/glinet.py on a Pi (install.sh copies it)
except ImportError:                    # the repo layout (tests)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "tools", "routers"))
    try:
        import glinet
    except ImportError:
        glinet = None


class OpalLink:
    def __init__(self, cfg, router_factory=None, path=None):
        self.path = path or cfg.get("tunnel_json", "/etc/burrow/tunnel.json")
        self.room = cfg.get("room")
        self.factory = router_factory or (glinet.Router if glinet else None)
        self.lock = threading.Lock()
        self.router = None
        self.cache = None
        self.cache_at = 0.0
        self.cache_s = 0.3
        self.calls = 0

    def _config(self):
        with open(self.path) as f:
            c = json.load(f)
        return c.get("host"), c.get("password")

    def _connect(self):
        host, pw = self._config()
        if not (host and pw and self.factory):
            raise RuntimeError("no Opal configured (tunnel.json) or glinet missing")
        r = self.factory(host, timeout=3)
        r.login(pw)
        self.router = r
        return r

    def _ask(self):
        r = self.router or self._connect()
        try:
            st = r.call("repeater", "get_status") or {}
        except Exception:
            r = self._connect()            # the session died (Opal rebooted): one retry
            st = r.call("repeater", "get_status") or {}
        out = {"ts": util.now(), "host": getattr(r, "host", None) or self._config()[0], "state": st.get("state_s"),
               "ssid": st.get("ssid"), "signal": st.get("signal"), "band": st.get("band"),
               "ip": (st.get("ipv4") or {}).get("ip"), "error": None}
        if self.room == 0:
            try:
                cl = r.call("clients", "get_list") or {}
                lst = cl.get("clients") if isinstance(cl, dict) else cl
                out["clients"] = [{"name": c.get("name") or c.get("mac"), "mac": c.get("mac"), "ip": c.get("ip"),
                                   "signal": c.get("signal") if c.get("signal") not in ("", None) else None, "band": c.get("band")}
                                  for c in (lst or []) if isinstance(c, dict) and c.get("online") and not c.get("remote")]
            except Exception:
                pass
        return out

    def signal(self):
        with self.lock:
            now = time.monotonic()
            if self.cache and now - self.cache_at < self.cache_s:
                return self.cache
            try:
                self.calls += 1
                self.cache = self._ask()
            except Exception as e:
                self.router = None
                self.cache = {"ts": util.now(), "state": None, "ssid": None, "signal": None, "band": None, "ip": None,
                              "error": str(e)[:120]}
            self.cache_at = now
            return self.cache
