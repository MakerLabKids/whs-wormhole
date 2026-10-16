"""Castings: the append log, sealing, the casting index, retention.

Layout under data_dir:
  open/r<room>.jsonl                    append-only, fsync'd on a timer
  castings/r<room>/<YYYY-MM-DD>/<id>.jsonl.gz   immutable
  castings/r<room>/<YYYY-MM-DD>/<id>.meta.json  small, rewritten atomically
  reclaimed.log                         one line per reclaimed casting
"""
import gzip
import json
import os
import threading
import time

from . import util
from .util import log

OPEN_DIR = "open"
CAST_DIR = "castings"


def casting_id(room, window_start):
    return "r%d-%s" % (room, util.utc_id(window_start))


def parse_id(cid):
    """'r1-20261016T1415' -> (room, window_start_unix). None if malformed."""
    try:
        r, stamp = cid.split("-", 1)
        stamp = stamp.split("-")[0]           # tolerate a dedup suffix
        room = int(r[1:])
        t = time.strptime(stamp, "%Y%m%dT%H%M")
        import calendar
        return room, calendar.timegm(t)
    except Exception:
        return None


class Store:
    def __init__(self, cfg):
        self.cfg = cfg
        self.room = int(cfg["room"])
        self.edge = cfg["edge"]
        self.data_dir = cfg["data_dir"]
        self.window = int(cfg["seal_minutes"]) * 60
        self.lock = threading.RLock()
        self.metas = {}            # id -> meta (every casting on this disk)
        self._open = None          # file handle for the open log
        self._open_path = os.path.join(self.data_dir, OPEN_DIR, "r%d.jsonl" % self.room)
        self._dirty = False
        self.on_sealed = []        # callbacks(meta, rows) after a seal
        os.makedirs(os.path.join(self.data_dir, OPEN_DIR), exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, CAST_DIR), exist_ok=True)
        self._load_index()
        self._reopen()

    # ---- index ---------------------------------------------------------
    def _load_index(self):
        n = 0
        root = os.path.join(self.data_dir, CAST_DIR)
        for roomdir in sorted(os.listdir(root)):
            rpath = os.path.join(root, roomdir)
            if not os.path.isdir(rpath):
                continue
            for day in sorted(os.listdir(rpath)):
                dpath = os.path.join(rpath, day)
                if not os.path.isdir(dpath):
                    continue
                for fn in os.listdir(dpath):
                    if not fn.endswith(".meta.json"):
                        continue
                    meta = util.read_json(os.path.join(dpath, fn))
                    if not meta or "id" not in meta:
                        continue
                    if not os.path.exists(self.gz_path(meta["id"])):
                        continue           # orphan sidecar: gz lost; ignore
                    self.metas[meta["id"]] = meta
                    n += 1
        log("store: %d castings indexed" % n)

    def _dir_for(self, cid):
        p = parse_id(cid)
        room, t0 = p if p else (self.room, 0)
        return os.path.join(self.data_dir, CAST_DIR, "r%d" % room, util.utc_day(t0))

    def gz_path(self, cid):
        return os.path.join(self._dir_for(cid), cid + ".jsonl.gz")

    def meta_path(self, cid):
        return os.path.join(self._dir_for(cid), cid + ".meta.json")

    def has(self, cid):
        return cid in self.metas

    def list_metas(self, since=None):
        with self.lock:
            out = [m for m in self.metas.values() if since is None or m.get("created", 0) >= since]
        out.sort(key=lambda m: (m.get("t0", 0), m["id"]))
        return out

    def save_meta(self, meta):
        with self.lock:
            self.metas[meta["id"]] = meta
            util.atomic_write_json(self.meta_path(meta["id"]), meta)

    # ---- the open log --------------------------------------------------
    def _reopen(self):
        if self._open:
            try:
                self._open.close()
            except OSError:
                pass
        self._open = open(self._open_path, "ab")

    def append(self, row):
        """Append one row to the open log. Durable within fsync_s."""
        line = (json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8")
        with self.lock:
            self._open.write(line)
            self._open.flush()
            self._dirty = True

    def fsync(self):
        with self.lock:
            if not self._dirty:
                return
            try:
                os.fsync(self._open.fileno())
            except OSError as e:
                log("store: fsync failed:", e)
            self._dirty = False

    def read_open(self):
        """All well-formed rows in the open log (a torn last line is dropped)."""
        rows = []
        try:
            with open(self._open_path, "rb") as f:
                for line in f:
                    if not line.endswith(b"\n"):
                        break                 # torn tail from a power cut
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        except FileNotFoundError:
            pass
        return rows

    # ---- sealing -------------------------------------------------------
    def window_of(self, ts):
        return int(ts) - (int(ts) % self.window)

    def seal_due(self, now=None):
        """Windows that have closed (plus grace) and have rows waiting."""
        now = now if now is not None else util.now()
        cutoff = self.window_of(now - int(self.cfg["seal_grace_s"]))
        rows = self.read_open()
        pending = {}
        for r in rows:
            w = self.window_of(r.get("ts", 0))
            if w < cutoff:
                pending.setdefault(w, []).append(r)
        return pending, rows

    def seal(self, now=None):
        """Seal every closed window in the open log into castings.
        Returns the list of new metas."""
        with self.lock:
            pending, rows = self.seal_due(now)
            if not pending:
                return []
            made = []
            for w in sorted(pending):
                wrows = sorted(pending[w], key=lambda r: r.get("ts", 0))
                meta = self._write_casting(self.room, w, wrows)
                made.append((meta, wrows))
            # rewrite the open log with only the still-open rows, atomically
            cutoff = self.window_of((now if now is not None else util.now()) - int(self.cfg["seal_grace_s"]))
            keep = [r for r in rows if self.window_of(r.get("ts", 0)) >= cutoff]
            util.atomic_write(self._open_path,
                              b"".join((json.dumps(r, separators=(",", ":")) + "\n").encode() for r in keep))
            self._reopen()
            self._dirty = False
        for meta, wrows in made:
            for cb in self.on_sealed:
                try:
                    cb(meta, wrows)
                except Exception as e:
                    log("store: on_sealed callback failed:", e)
        return [m for m, _ in made]

    def _write_casting(self, room, w, wrows):
        cid = casting_id(room, w)
        if cid in self.metas:
            # Same window sealed before (clock went backwards?). Keep the old
            # one immutable; file this one under a suffix.
            n = 2
            while ("%s-%d" % (cid, n)) in self.metas:
                n += 1
            cid = "%s-%d" % (cid, n)
        body = b"".join((json.dumps(r, separators=(",", ":")) + "\n").encode("utf-8") for r in wrows)
        gz = gzip.compress(body, compresslevel=6, mtime=0)
        gzp = self.gz_path(cid)
        util.atomic_write(gzp, gz)
        meta = {
            "id": cid, "room": room, "edge": self.edge,
            "t0": wrows[0].get("ts", w), "t1": wrows[-1].get("ts", w),
            "window": w, "rows": len(wrows),
            "sha256": util.sha256_bytes(gz), "size": len(gz),
            "created": util.now(), "origin": self.edge,
            "replicas": {}, "cloud": {"uploaded_at": None, "rollups_at": None,
                                       "verified_at": None, "by": None},
        }
        self.save_meta(meta)
        log("store: sealed %s (%d rows, %d bytes)" % (cid, len(wrows), len(gz)))
        return meta

    # ---- mirrored castings from peers ----------------------------------
    def store_mirror(self, meta, gz, from_edge):
        """Store a casting pulled from a peer. Verifies the hash. Returns
        the stored meta, or None if the bytes do not match."""
        if util.sha256_bytes(gz) != meta.get("sha256"):
            log("store: mirror %s from %s: hash mismatch, dropped" % (meta.get("id"), from_edge))
            return None
        cid = meta["id"]
        with self.lock:
            if cid in self.metas:
                return self.metas[cid]
            util.atomic_write(self.gz_path(cid), gz)
            mine = dict(meta)
            mine["replicas"] = dict(meta.get("replicas") or {})
            mine["replicas"][self.edge] = util.now()
            mine["mirrored_from"] = from_edge
            self.save_meta(mine)
        log("store: mirrored %s from %s" % (cid, from_edge))
        return mine

    def rows_of(self, cid):
        """Decode a casting's rows (own or mirrored)."""
        with gzip.open(self.gz_path(cid), "rb") as f:
            return [json.loads(l) for l in f if l.strip()]

    def gz_bytes(self, cid):
        with open(self.gz_path(cid), "rb") as f:
            return f.read()

    # ---- cloud bookkeeping --------------------------------------------
    def mark_cloud(self, cid, **fields):
        with self.lock:
            m = self.metas.get(cid)
            if not m:
                return
            m.setdefault("cloud", {})
            m["cloud"].update(fields)
            self.save_meta(m)

    def note_replica(self, cid, edge, ts=None):
        with self.lock:
            m = self.metas.get(cid)
            if not m:
                return
            m.setdefault("replicas", {})[edge] = ts or util.now()
            self.save_meta(m)

    # ---- retention -----------------------------------------------------
    def reclaimable(self, now=None):
        now = now if now is not None else util.now()
        limit = int(self.cfg["retain_days"]) * 86400
        out = []
        with self.lock:
            for m in self.metas.values():
                if not (m.get("cloud") or {}).get("verified_at"):
                    continue
                if now - int(m.get("t1", now)) < limit:
                    continue
                out.append(m["id"])
        return sorted(out)

    def reclaim(self, now=None):
        """Delete castings that are >= retain_days old AND cloud-verified.
        Nothing else ever deletes a casting."""
        ids = self.reclaimable(now)
        if not ids:
            return 0
        logp = os.path.join(self.data_dir, "reclaimed.log")
        with self.lock:
            with open(logp, "a") as lf:
                for cid in ids:
                    m = self.metas.pop(cid)
                    for p in (self.gz_path(cid), self.meta_path(cid)):
                        try:
                            os.remove(p)
                        except FileNotFoundError:
                            pass
                    lf.write(json.dumps({"id": cid, "at": util.now(), "sha256": m.get("sha256"),
                                         "verified_at": m["cloud"].get("verified_at")}) + "\n")
                lf.flush()
                os.fsync(lf.fileno())
        log("store: reclaimed %d verified castings older than %s days" % (len(ids), self.cfg["retain_days"]))
        return len(ids)

    def close(self):
        with self.lock:
            try:
                if self._open:
                    self._open.close()
            except OSError:
                pass
            self._open = None

    # ---- stats ---------------------------------------------------------
    def stats(self):
        with self.lock:
            n = len(self.metas)
            unverified = sum(1 for m in self.metas.values() if not (m.get("cloud") or {}).get("verified_at"))
            size = sum(int(m.get("size", 0)) for m in self.metas.values())
            own = sum(1 for m in self.metas.values() if m.get("origin") == self.edge)
        try:
            st = os.statvfs(self.data_dir)
            free = st.f_bavail * st.f_frsize
            total = st.f_blocks * st.f_frsize
        except OSError:
            free = total = 0
        return {"castings": n, "own": own, "unverified": unverified, "bytes": size,
                "disk_free": free, "disk_total": total,
                "disk_pct": (100.0 * (total - free) / total) if total else 0}
