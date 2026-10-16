"""Derived, rebuildable 5-minute and hourly aggregates in SQLite.

rollups(uid, step, ts, data)  data = JSON {metric: [min, avg, max, n]}
The database is an index over castings. Losing it costs a rebuild, nothing more.
"""
import json
import os
import sqlite3
import threading

from . import util
from .util import log

STEP_S = {"5m": 300, "1h": 3600}


def bucketize(rows, step="5m"):
    """rows -> {(uid, bucket_ts): {metric: [min, sum, max, n]}} then finalized
    to [min, avg, max, n]."""
    s = STEP_S[step]
    acc = {}
    for r in rows:
        uid = r.get("uid")
        ts = r.get("ts")
        if not uid or ts is None:
            continue
        b = int(ts) - int(ts) % s
        slot = acc.setdefault((uid, b), {})
        for k, v in util.metrics(r.get("d") or {}).items():
            a = slot.get(k)
            if a is None:
                slot[k] = [v, v, v, 1]
            else:
                if v < a[0]:
                    a[0] = v
                a[1] += v
                if v > a[2]:
                    a[2] = v
                a[3] += 1
    out = []
    for (uid, b), slot in acc.items():
        data = {k: [a[0], round(a[1] / a[3], 3), a[2], a[3]] for k, a in slot.items()}
        out.append({"uid": uid, "step": step, "ts": b, "data": data})
    out.sort(key=lambda x: (x["uid"], x["ts"]))
    return out


def merge_hourly(fivemin_rows):
    """Combine 5m rollups into 1h rollups (weighted avg, min of min, max of max)."""
    acc = {}
    for r in fivemin_rows:
        b = r["ts"] - r["ts"] % 3600
        slot = acc.setdefault((r["uid"], b), {})
        for k, (mn, av, mx, n) in r["data"].items():
            a = slot.get(k)
            if a is None:
                slot[k] = [mn, av * n, mx, n]
            else:
                a[0] = min(a[0], mn)
                a[1] += av * n
                a[2] = max(a[2], mx)
                a[3] += n
    out = []
    for (uid, b), slot in acc.items():
        out.append({"uid": uid, "step": "1h", "ts": b,
                    "data": {k: [a[0], round(a[1] / a[3], 3), a[2], a[3]] for k, a in slot.items()}})
    out.sort(key=lambda x: (x["uid"], x["ts"]))
    return out


class Rollups:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS rollups(
            uid TEXT NOT NULL, step TEXT NOT NULL, ts INTEGER NOT NULL, data TEXT NOT NULL,
            PRIMARY KEY(uid, step, ts))""")
        self.db.execute("CREATE INDEX IF NOT EXISTS rollups_ts ON rollups(step, ts)")
        self.db.commit()

    def put(self, rows):
        if not rows:
            return 0
        with self.lock:
            self.db.executemany(
                "INSERT OR REPLACE INTO rollups(uid, step, ts, data) VALUES(?,?,?,?)",
                [(r["uid"], r["step"], int(r["ts"]), json.dumps(r["data"], separators=(",", ":"))) for r in rows])
            self.db.commit()
        return len(rows)

    def ingest_casting(self, rows):
        """Add a casting's rows: 5m buckets directly, and refresh the 1h
        buckets those touch from ALL 5m rows in each hour."""
        fm = bucketize(rows, "5m")
        self.put(fm)
        hours = sorted(set((r["uid"], r["ts"] - r["ts"] % 3600) for r in fm))
        hourly = []
        for uid, h in hours:
            fives = self.query(uid, h, h + 3599, "5m")
            hourly.extend(merge_hourly([{"uid": uid, "ts": t, "data": d} for t, d in fives]))
        self.put(hourly)
        return len(fm), len(hourly)

    def query(self, uid, t_from, t_to, step="5m"):
        with self.lock:
            cur = self.db.execute(
                "SELECT ts, data FROM rollups WHERE uid=? AND step=? AND ts>=? AND ts<=? ORDER BY ts",
                (uid, step, int(t_from), int(t_to)))
            return [(ts, json.loads(d)) for ts, d in cur.fetchall()]

    def uids(self):
        with self.lock:
            return [r[0] for r in self.db.execute("SELECT DISTINCT uid FROM rollups")]

    def rebuild(self, store):
        """Wipe and recompute from every casting on disk."""
        with self.lock:
            self.db.execute("DELETE FROM rollups")
            self.db.commit()
        n = 0
        for m in store.list_metas():
            try:
                self.ingest_casting(store.rows_of(m["id"]))
                n += 1
            except Exception as e:
                log("rollups: rebuild skipped %s: %s" % (m["id"], e))
        log("rollups: rebuilt from %d castings" % n)
        return n
