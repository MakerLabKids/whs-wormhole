"""Peer replication: pull castings the other Burrows have and we lack."""
import json
import urllib.error
import urllib.request

from . import util
from .util import log


class Peers:
    def __init__(self, cfg, store, on_mirrored=None):
        self.cfg = cfg
        self.store = store
        self.peers = dict(cfg.get("peers") or {})
        self.state = {name: {"ok": False, "last_ok": 0, "last_try": 0, "error": None, "castings": 0}
                      for name in self.peers}
        self.on_mirrored = on_mirrored
        self.timeout = 8

    def add(self, name, url):
        self.peers[name] = url
        self.state.setdefault(name, {"ok": False, "last_ok": 0, "last_try": 0, "error": None, "castings": 0})

    def _get(self, url, binary=False):
        req = urllib.request.Request(url, headers={"User-Agent": "burrow/" + self.cfg["edge"]})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = r.read()
            return data if binary else json.loads(data.decode("utf-8"))

    def health(self, name):
        base = self.peers[name]
        st = self.state[name]
        st["last_try"] = util.now()
        try:
            h = self._get(base + "/health")
            st.update(ok=True, last_ok=util.now(), error=None, clk=h.get("clk"), ts=h.get("ts"))
            return h
        except Exception as e:
            st.update(ok=False, error=str(e)[:120])
            return None

    def replicate_from(self, name, limit=40):
        """Pull up to `limit` castings we lack from one peer. Returns count."""
        base = self.peers[name]
        st = self.state[name]
        try:
            idx = self._get(base + "/castings")
        except Exception as e:
            st.update(ok=False, error=str(e)[:120], last_try=util.now())
            return 0
        st.update(ok=True, last_ok=util.now(), error=None)
        metas = idx.get("castings") or []
        st["castings"] = len(metas)
        want = [m for m in metas if m.get("id") and not self.store.has(m["id"])]
        want.sort(key=lambda m: m.get("t0", 0), reverse=True)    # newest first
        got = 0
        for m in want[:limit]:
            try:
                gz = self._get(base + "/castings/" + m["id"], binary=True)
            except Exception as e:
                log("peers: %s: fetch %s failed: %s" % (name, m["id"], e))
                break
            stored = self.store.store_mirror(m, gz, name)
            if stored:
                got += 1
                if self.on_mirrored:
                    try:
                        self.on_mirrored(stored)
                    except Exception as e:
                        log("peers: on_mirrored failed:", e)
        # Learn what the peer knows about cloud verification of castings we share.
        for m in metas:
            mine = self.store.metas.get(m.get("id"))
            if not mine:
                continue
            c = m.get("cloud") or {}
            if c.get("verified_at") and not mine["cloud"].get("verified_at"):
                self.store.mark_cloud(m["id"], verified_at=c["verified_at"], by=c.get("by"),
                                      uploaded_at=c.get("uploaded_at") or mine["cloud"].get("uploaded_at"),
                                      rollups_at=c.get("rollups_at") or mine["cloud"].get("rollups_at"))
            if mine.get("origin") == self.cfg["edge"] and name not in (mine.get("replicas") or {}):
                self.store.note_replica(m["id"], name)
        if got:
            log("peers: mirrored %d castings from %s" % (got, name))
        return got

    def replicate_all(self):
        total = 0
        for name in self.peers:
            total += self.replicate_from(name)
        return total

    def status(self):
        return {name: dict(st, url=self.peers[name]) for name, st in self.state.items()}
