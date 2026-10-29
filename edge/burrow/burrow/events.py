"""Events: things that happen on this Burrow, pushed to the Surface the moment they happen.

A snapshot every 60 s tells the cloud how things ARE; an event says something CHANGED, now:
a Bin went quiet or came back, a peer Burrow vanished, the cloud link came back after an
outage, the Opal watchdog switched upstream or rebooted the Opal, the service started.
`emit()` is cheap and never blocks the caller: it appends to a queue (kept on disk under the
data dir so a reboot loses nothing) and wakes a flusher thread that POSTs /v1/edge/events at
once. While the cloud is unreachable the queue grows and is retried with backoff and again
after every successful snapshot pass, so the history of an outage arrives in order when the
link returns. Levels: info, warn, alert (alert = the Surface notifies a human right away).
"""
import json
import os
import threading

from . import util
from .util import log

KEEP_LOCAL = 200          # recent events served at /api/events and in /api/status
QUEUE_CAP = 2000          # unsent events kept across an outage
BACKOFF = (5, 15, 30, 60, 120, 300)


class Events:
    def __init__(self, cfg, send=None, path=None):
        self.edge = cfg.get("edge")
        self.send = send                              # callable(list_of_events) -> True on success
        self.path = path or os.path.join(cfg.get("data_dir", "/tmp"), "events-queue.json")
        self.lock = threading.Lock()
        self.queue = self._load()
        self.recent = []
        self.state = {"sent": 0, "failed": 0, "queued": len(self.queue), "last_sent": None, "last_error": None}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._fails = 0
        self._thread = None

    def _load(self):
        try:
            with open(self.path) as f:
                q = json.load(f)
                return q if isinstance(q, list) else []
        except Exception:
            return []

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.queue[-QUEUE_CAP:], f, separators=(",", ":"))
            os.replace(tmp, self.path)
        except Exception as e:
            log("events: cannot persist queue: %s" % e)

    def emit(self, kind, text, level="info", data=None):
        ev = {"ts": util.now(), "edge": self.edge, "kind": kind, "level": level, "text": str(text)[:300]}
        if data:
            ev["data"] = data
        with self.lock:
            self.recent.append(ev)
            del self.recent[:-KEEP_LOCAL]
            self.queue.append(ev)
            del self.queue[:-QUEUE_CAP]
            self.state["queued"] = len(self.queue)
            self._save()
        log("event [%s] %s: %s" % (level, kind, text))
        self._wake.set()
        return ev

    def start(self):
        if self._thread or not self.send:
            return
        self._thread = threading.Thread(target=self._run, name="events", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def kick(self):
        """Something else (a successful snapshot) proved the link is up: try the queue now."""
        self._fails = 0
        self._wake.set()

    def flush_once(self):
        with self.lock:
            batch = list(self.queue[:100])
        if not batch:
            return True
        try:
            ok = self.send(batch)
        except Exception as e:
            ok = False
            self.state["last_error"] = str(e)[:120]
        if ok:
            with self.lock:
                self.queue = self.queue[len(batch):]
                self.state.update(sent=self.state["sent"] + len(batch), queued=len(self.queue),
                                  last_sent=util.now(), last_error=None)
                self._save()
            self._fails = 0
            return True
        self.state["failed"] += 1
        self._fails += 1
        return False

    def _run(self):
        while not self._stop.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop.is_set():
                break
            while self.queue and not self._stop.is_set():
                if self.flush_once():
                    continue
                wait = BACKOFF[min(self._fails, len(BACKOFF)) - 1]
                if self._wake.wait(wait):
                    self._wake.clear()
                    if self._fails and not self.queue:
                        break
            # queue empty: sleep until the next emit()


class QuietWatch:
    """Notices Bins and peers going quiet or coming back, and the cloud link returning.
    Call tick() every few seconds; it only emits on a transition."""

    def __init__(self, cfg, now, peers_state, cloud_state, events):
        self.edge = cfg.get("edge")
        self.stale_s = int(cfg.get("stale_s", 180))
        self.quiet_s = int(cfg.get("quiet_alert_s", 600))   # a Bin silent this long is worth a note
        self.now, self.peers_state, self.cloud_state, self.events = now, peers_state, cloud_state, events
        self.quiet = set()
        self.peer_down = {}
        self.cloud_was = None
        self.cloud_down_since = None

    def tick(self, t=None):
        t = t or util.now()
        snap = self.now.snapshot(now=t, max_age=7 * 86400)
        for uid, e in snap.items():
            if self.edge and e.get("edge") not in (None, self.edge):
                continue                      # another room's Bin, known through a peer: its Burrow watches it
            age = t - (e.get("ts") or 0)
            name = e.get("team") or e.get("name") or uid
            if age > self.quiet_s and uid not in self.quiet and e.get("src") != "live":
                self.quiet.add(uid)
                self.events.emit("bin.quiet", "%s (bin %s) silent for %d min" % (name, e.get("bin") if e.get("bin") is not None else "?", age // 60),
                                 "warn", {"uid": uid, "last_ts": e.get("ts"), "ip": (e.get("d") or {}).get("ip")})
            elif age <= self.stale_s and uid in self.quiet:
                self.quiet.discard(uid)
                self.events.emit("bin.back", "%s (bin %s) is reporting again" % (name, e.get("bin") if e.get("bin") is not None else "?"),
                                 "info", {"uid": uid})
        for peer, st in (self.peers_state or {}).items():
            ok = bool(st.get("ok"))
            was = self.peer_down.get(peer)
            if was is None:
                self.peer_down[peer] = (None if ok else t)
                if not ok and st.get("last_try"):
                    self.events.emit("peer.down", "%s unreachable (%s)" % (peer, st.get("error") or "no answer"), "warn", {"peer": peer})
            elif ok and was is not None:
                self.peer_down[peer] = None
                self.events.emit("peer.back", "%s reachable again after %d min" % (peer, (t - was) // 60), "info", {"peer": peer})
            elif not ok and was is None and st.get("last_try"):
                self.peer_down[peer] = t
                self.events.emit("peer.down", "%s unreachable (%s)" % (peer, st.get("error") or "no answer"), "warn", {"peer": peer})
        reach = self.cloud_state.get("reachable") if self.cloud_state else None
        if reach is not None:
            if self.cloud_was is None:
                self.cloud_was = reach
                self.cloud_down_since = None if reach else t
            elif reach and not self.cloud_was:
                self.events.emit("cloud.back", "cloud reachable again after %d min" % ((t - (self.cloud_down_since or t)) // 60), "warn",
                                 {"down_since": self.cloud_down_since})
                self.cloud_was, self.cloud_down_since = True, None
            elif not reach and self.cloud_was:
                self.cloud_was, self.cloud_down_since = False, t
                self.events.emit("cloud.down", "cloud unreachable: %s" % (self.cloud_state.get("error") or "no answer"), "warn")
