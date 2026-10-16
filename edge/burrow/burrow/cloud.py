"""Uploader: snapshots, castings, rollups, and the verify read-back.

Everything here is idempotent and retried forever. 'reachable' is decided by
GET /v1/edge/ping answering with our JSON (a captive portal answers with HTML).
"""
import gzip
import json
import time
import urllib.error
import urllib.request

from . import clock, rollups, util
from .util import log


class Cloud:
    def __init__(self, cfg, store, now, status_fn):
        self.cfg = cfg
        self.c = cfg["cloud"]
        self.store = store
        self.now = now
        self.status_fn = status_fn
        self.token = self._read(self.c.get("token_file"))
        self.base = (self.c.get("url") or "").rstrip("/")
        self.state = {"reachable": False, "last_ok": 0, "last_try": 0, "error": None,
                      "uploaded": 0, "verified": 0, "captive": False, "server_ts": None,
                      "snapshots": 0}
        self.timeout = 20
        self._roster_sent = 0

    @staticmethod
    def _read(path):
        try:
            with open(path) as f:
                return f.read().strip()
        except Exception:
            return None

    def enabled(self):
        return bool(self.base and self.token)

    def _call(self, method, path, body=None, headers=None, raw=False):
        h = {"Authorization": "Bearer " + self.token, "User-Agent": "burrow/" + self.cfg["edge"],
             "Accept": "application/json"}
        if headers:
            h.update(headers)
        data = None
        if body is not None:
            if raw:
                data = body
                h.setdefault("Content-Type", "application/gzip")
            else:
                data = json.dumps(body, separators=(",", ":")).encode("utf-8")
                h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            txt = r.read().decode("utf-8")
            date = r.headers.get("Date")
            try:
                return json.loads(txt), date
            except ValueError:
                raise RuntimeError("non-JSON reply (captive portal?)")

    # ---- reachability + clock ------------------------------------------
    def ping(self):
        self.state["last_try"] = util.now()
        try:
            j, date = self._call("GET", "/v1/edge/ping")
            if not (isinstance(j, dict) and j.get("ok")):
                raise RuntimeError("unexpected ping reply")
            self.state.update(reachable=True, last_ok=util.now(), error=None, captive=False,
                              server_ts=j.get("ts"))
            self._maybe_fix_clock(j.get("ts"))
            return True
        except urllib.error.HTTPError as e:
            self.state.update(reachable=False, error="HTTP %d" % e.code, captive=(e.code in (302, 511)))
        except Exception as e:
            msg = str(e)
            self.state.update(reachable=False, error=msg[:120], captive=("captive" in msg))
        return False

    def _maybe_fix_clock(self, server_ts):
        if not server_ts:
            return
        drift = abs(int(server_ts) - util.now())
        if drift > 60 and clock.quality(force=True) == "free":
            clock.step_to(int(server_ts), "cloud said %d, we said %d" % (server_ts, util.now()))

    # ---- snapshot ------------------------------------------------------
    def snapshot(self):
        bins = self.now.snapshot()
        body = {"edge": self.cfg["edge"], "room": self.cfg["room"], "ts": util.now(),
                "clk": clock.quality(), "bins": bins, "status": self.status_fn()}
        if util.now() - self._roster_sent > 3600:
            body["roster"] = [{"uid": uid, "name": e.get("name"), "team": e.get("team"),
                               "period": e.get("period"), "bin": e.get("bin"), "room": e.get("home_room")}
                              for uid, e in bins.items()]
        j, _ = self._call("POST", "/v1/edge/snapshot", body)
        if body.get("roster") is not None:
            self._roster_sent = util.now()
        self.state["snapshots"] += 1
        return j

    # ---- castings ------------------------------------------------------
    def pending(self):
        """Castings that still need something from the cloud, oldest first,
        own castings before mirrors (so each Burrow prefers its own work)."""
        out = []
        for m in self.store.list_metas():
            c = m.get("cloud") or {}
            if c.get("verified_at") and c.get("rollups_at"):
                continue
            out.append(m)
        mine = self.cfg["edge"]
        out.sort(key=lambda m: (0 if m.get("origin") == mine else 1, m.get("t0", 0)))
        return out

    def upload_casting(self, m):
        cid = m["id"]
        gz = self.store.gz_bytes(cid)
        meta = {k: m[k] for k in ("id", "room", "edge", "t0", "t1", "rows", "sha256", "size", "created", "origin")
                if k in m}
        j, _ = self._call("PUT", "/v1/edge/castings/" + cid, gz, raw=True,
                          headers={"X-Casting-Meta": json.dumps(meta, separators=(",", ":"))})
        if not j.get("ok"):
            raise RuntimeError("upload refused: %s" % j)
        if j.get("sha256") and j["sha256"] != m["sha256"]:
            raise RuntimeError("cloud hashed %s, we have %s" % (j["sha256"], m["sha256"]))
        self.store.mark_cloud(cid, uploaded_at=util.now(), by=self.cfg["edge"])
        self.state["uploaded"] += 1

    def upload_rollups(self, m):
        cid = m["id"]
        rows = self.store.rows_of(cid)
        fm = rollups.bucketize(rows, "5m")
        j, _ = self._call("POST", "/v1/edge/rollups", {"casting": cid, "rows": fm})
        if not j.get("ok"):
            raise RuntimeError("rollups refused: %s" % j)
        self.store.mark_cloud(cid, rollups_at=util.now())

    def verify(self, ids):
        if not ids:
            return
        j, _ = self._call("POST", "/v1/edge/verify", {"ids": ids})
        ts = util.now()
        for cid in j.get("verified") or []:
            m = self.store.metas.get(cid)
            if m and not m["cloud"].get("verified_at"):
                self.store.mark_cloud(cid, verified_at=ts, by=m["cloud"].get("by") or "cloud",
                                      uploaded_at=m["cloud"].get("uploaded_at") or ts)
                self.state["verified"] += 1
        for cid in j.get("rollups") or []:
            m = self.store.metas.get(cid)
            if m and not m["cloud"].get("rollups_at"):
                self.store.mark_cloud(cid, rollups_at=ts)
        for cid in j.get("missing") or []:
            m = self.store.metas.get(cid)
            if m and m["cloud"].get("uploaded_at"):
                log("cloud: %s reported missing; will re-upload" % cid)
                self.store.mark_cloud(cid, uploaded_at=None, verified_at=None)

    def pass_once(self, budget_s=45):
        """One upload pass: ping, snapshot, then as many castings as fit."""
        if not self.enabled():
            self.state["error"] = "no cloud url/token configured"
            return False
        if not self.ping():
            return False
        t_end = time.monotonic() + budget_s
        try:
            self.snapshot()
        except Exception as e:
            self.state["error"] = "snapshot: %s" % str(e)[:100]
            log("cloud: snapshot failed:", e)
        todo = self.pending()
        to_verify = []
        for m in todo:
            if time.monotonic() > t_end:
                break
            c = m["cloud"]
            try:
                if not c.get("uploaded_at"):
                    self.upload_casting(m)
                if not c.get("rollups_at"):
                    self.upload_rollups(m)
                if not c.get("verified_at"):
                    to_verify.append(m["id"])
            except Exception as e:
                self.state["error"] = "%s: %s" % (m["id"], str(e)[:100])
                log("cloud: %s: %s" % (m["id"], e))
                if isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError):
                    break               # link went away; stop the pass (an HTTP error is per-casting)
        # Verify everything not yet verified (cheap; the Worker reads R2 back).
        unverified = [m["id"] for m in self.store.list_metas() if not m["cloud"].get("verified_at")
                      and m["cloud"].get("uploaded_at")]
        for i in range(0, len(unverified), 40):
            if time.monotonic() > t_end + 30:
                break
            try:
                self.verify(unverified[i:i + 40])
            except Exception as e:
                self.state["error"] = "verify: %s" % str(e)[:100]
                log("cloud: verify failed:", e)
                break
        return True

    def status(self):
        s = dict(self.state)
        s["enabled"] = self.enabled()
        s["url"] = self.base
        return s
