"""Uploader: snapshots, castings, rollups, and the verify read-back.

Everything here is idempotent and retried forever. 'reachable' is decided by
GET /v1/edge/ping answering with our JSON (a captive portal answers with HTML).
"""
import gzip
import json
import os
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
        # Messages set on the website for the Bins, as the last snapshot reply
        # listed them: {uid: [item, ...]}. Handed to a Bin in its /ingest reply;
        # the Bin acks by seq in its next push (d.msg_seq), the Surface sees
        # that in our snapshot and stops listing them.
        self.messages = {}
        self.msg_state_fn = None        # set by the service: () -> {uid: {rev, slots, at}}

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
        if self.msg_state_fn:
            state = self.msg_state_fn()
            if state:
                body["messages_state"] = state      # what each Bin says is on its screen
        if util.now() - self._roster_sent > 3600:
            body["roster"] = [{"uid": uid, "name": e.get("name"), "team": e.get("team"),
                               "period": e.get("period"), "bin": e.get("bin"), "room": e.get("home_room")}
                              for uid, e in bins.items()]
        j, _ = self._call("POST", "/v1/edge/snapshot", body)
        if body.get("roster") is not None:
            self._roster_sent = util.now()
        self.state["snapshots"] += 1
        if isinstance(j, dict) and isinstance(j.get("update_to"), dict):
            self._request_update(j["update_to"])
        if isinstance(j, dict) and isinstance(j.get("messages"), list):
            by_uid = {}
            for it in j["messages"]:
                if isinstance(it, dict) and isinstance(it.get("uid"), str):
                    by_uid.setdefault(it["uid"], []).append(it)
            self.messages = by_uid
            self.state["messages"] = sum(len(v) for v in by_uid.values())
        return j

    def _request_update(self, upd):
        """The admin clicked Update for this Burrow: leave {build, sha256, url}
        in the data dir for burrow-update.service (root, watching that path),
        which downloads, verifies, installs and restarts us. Once per build."""
        build, sha, url = upd.get("build"), upd.get("sha256"), upd.get("url")
        if not (isinstance(build, str) and isinstance(sha, str) and isinstance(url, str)):
            return
        if self.state.get("update_requested") == build:
            return
        path = os.path.join(self.cfg["data_dir"], "update-request.json")
        try:
            util.atomic_write_json(path, {"build": build, "sha256": sha, "url": url, "at": util.now()})
            self.state["update_requested"] = build
            log("update: asked to move to %s; handing it to the updater" % build)
        except Exception as e:
            log("update: could not write the request:", e)

    def messages_for(self, uid):
        """Pending website messages for one Bin (each with uid, slot, seq, pin...)."""
        return list(self.messages.get(uid) or [])

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

    def send_events(self, events):
        """POST a batch of events; True when the Surface took them."""
        if not self.enabled():
            return False
        j, _ = self._call("POST", "/v1/edge/events", {"edge": self.cfg["edge"], "events": events})
        return bool(isinstance(j, dict) and j.get("ok"))

    def status(self):
        s = dict(self.state)
        s["enabled"] = self.enabled()
        s["url"] = self.base
        return s
