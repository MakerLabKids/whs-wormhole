"""Live state: the 'now' table (latest row per Bin) and the SSE broadcaster."""
import json
import queue
import threading

from . import util


class Now:
    def __init__(self, stale_s=180):
        self.lock = threading.Lock()
        self.bins = {}          # uid -> entry
        self.stale_s = stale_s

    @staticmethod
    def entry_from_row(row):
        d = row.get("d") or {}
        b = d.get("bin") or {}
        return {
            "ts": row.get("ts"), "clk": row.get("clk"), "src": row.get("src"),
            "edge": row.get("edge"), "room": row.get("room"),
            "name": row.get("name") or d.get("name"),
            "team": b.get("team"), "period": b.get("period"), "bin": b.get("bin"),
            "home_room": b.get("room"),
            "d": d,
        }

    def update(self, row):
        e = self.entry_from_row(row)
        with self.lock:
            old = self.bins.get(row["uid"])
            if old and old.get("ts", 0) > e.get("ts", 0):
                return old
            self.bins[row["uid"]] = e
        return e

    def merge(self, uid, entry):
        """Fold in an entry learned from a peer/snapshot (keep the newest)."""
        with self.lock:
            old = self.bins.get(uid)
            if old and old.get("ts", 0) >= entry.get("ts", 0):
                return
            self.bins[uid] = entry

    def snapshot(self, now=None, max_age=86400):
        now = now if now is not None else util.now()
        with self.lock:
            out = {}
            for uid, e in self.bins.items():
                if now - (e.get("ts") or 0) > max_age:
                    continue
                x = dict(e)
                x["stale"] = (now - (e.get("ts") or 0)) > self.stale_s
                out[uid] = x
            return out

    def quiet(self, now=None, quiet_s=300):
        """Bins we have not heard from in quiet_s (uid -> last ip)."""
        now = now if now is not None else util.now()
        with self.lock:
            return {uid: (e.get("d") or {}).get("ip") for uid, e in self.bins.items()
                    if now - (e.get("ts") or 0) > quiet_s}

    def known_ips(self):
        with self.lock:
            return set((e.get("d") or {}).get("ip") for e in self.bins.values()) - {None}


class Broadcaster:
    """Fan-out of rows to SSE clients. Slow clients drop events, never block ingest."""

    def __init__(self, maxq=200):
        self.lock = threading.Lock()
        self.clients = set()
        self.maxq = maxq

    def subscribe(self):
        q = queue.Queue(self.maxq)
        with self.lock:
            self.clients.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.clients.discard(q)

    def publish(self, event, obj):
        msg = "event: %s\ndata: %s\n\n" % (event, json.dumps(obj, separators=(",", ":")))
        with self.lock:
            cs = list(self.clients)
        for q in cs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    def count(self):
        with self.lock:
            return len(self.clients)
