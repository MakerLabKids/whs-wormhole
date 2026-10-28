"""Watch mode: the 1 Hz live view.

While anyone is watching a Bin (an SSE client connected with ?watch=<uid>), one
thread polls that Bin's /data page once a second and publishes each reading on
the bus as `event: live`. Nothing is written to the store, the now-table or the
cloud: the archive keeps its 60 s cadence. One poller per Bin no matter how many
viewers; it stops when the last viewer disconnects.
"""
import threading
import time

from . import util
from .sweep import fetch_data
from .state import Now
from .util import log


class Watch:
    def __init__(self, cfg, now, bus, clk=lambda: "free", fetch=fetch_data):
        w = cfg.get("watch") or {}
        self.every_s = float(w.get("every_s", 1.0))
        self.timeout_s = float(w.get("timeout_s", 0.8))
        self.max_bins = int(w.get("max_bins", 8))
        self.edge, self.room = cfg.get("edge"), cfg.get("room")
        self.now, self.bus, self.clk, self.fetch = now, bus, clk, fetch
        self.lock = threading.Lock()
        self.bins = {}      # uid -> {"viewers", "stop", "thread", "polls", "errors", "last_ok", "ip"}

    def ip_of(self, uid):
        """The Bin's address, only when its latest row came through THIS Burrow: a Bin we
        know from a peer's casting lives on another room's LAN and cannot be polled from here."""
        with self.now.lock:
            e = self.now.bins.get(uid)
        if not e or e.get("edge") != self.edge:
            return None
        return (e.get("d") or {}).get("ip")

    def add(self, uid):
        """One more viewer for uid. Returns False when the Bin is unknown here (no address on
        this LAN to poll) or too many Bins are being watched already."""
        if not uid or not self.ip_of(uid):
            return False
        with self.lock:
            w = self.bins.get(uid)
            if w:
                w["viewers"] += 1
                return True
            if len(self.bins) >= self.max_bins:
                return False
            stop = threading.Event()
            w = {"viewers": 1, "stop": stop, "polls": 0, "errors": 0, "last_ok": None, "ip": None}
            w["thread"] = threading.Thread(target=self._run, args=(uid, w), name="watch-" + uid[:8], daemon=True)
            self.bins[uid] = w
            w["thread"].start()
        log("watch: %s started (1 poll every %.1f s)" % (uid, self.every_s))
        return True

    def remove(self, uid):
        with self.lock:
            w = self.bins.get(uid)
            if not w:
                return
            w["viewers"] -= 1
            if w["viewers"] > 0:
                return
            w["stop"].set()
            del self.bins[uid]
        log("watch: %s stopped after %d polls (%d errors)" % (uid, w["polls"], w["errors"]))

    def status(self):
        with self.lock:
            return {uid: {"viewers": w["viewers"], "polls": w["polls"], "errors": w["errors"],
                          "last_ok": w["last_ok"], "ip": w["ip"]} for uid, w in self.bins.items()}

    def _run(self, uid, w):
        stop = w["stop"]
        while not stop.is_set():
            t0 = time.monotonic()
            ip = self.ip_of(uid)
            w["ip"] = ip
            try:
                d = self.fetch(ip, self.timeout_s) if ip else None
                if d and d.get("id") == uid:
                    d.setdefault("ip", ip)
                    row = {"ts": util.now(), "clk": self.clk(), "uid": uid, "name": d.get("name"),
                           "room": self.room, "edge": self.edge, "src": "live", "d": d}
                    self.bus.publish("live", {"uid": uid, "entry": Now.entry_from_row(row)})
                    w["last_ok"] = row["ts"]
                else:
                    w["errors"] += 1
            except Exception:
                w["errors"] += 1
            w["polls"] += 1
            stop.wait(max(0.05, self.every_s - (time.monotonic() - t0)))
