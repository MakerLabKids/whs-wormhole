"""The Burrow service: wires store, rollups, state, server, peers, cloud, sweep
together and runs the background loops."""
import json
import os
import threading
import time

from . import VERSION, clock, config, server, util
from .cloud import Cloud
from .events import Events, QuietWatch
from .peers import Peers
from .rollups import Rollups
from .state import Broadcaster, Now
from .store import Store
from .sweep import Sweep
from .netstat import NetStat
from .opal import OpalLink
from .watch import Watch
from .util import Every, log


class Service:
    version = VERSION

    def __init__(self, cfg):
        self.cfg = cfg
        self.started = util.now()
        os.makedirs(cfg["data_dir"], exist_ok=True)
        self.store = Store(cfg)
        self.rollups = Rollups(os.path.join(cfg["data_dir"], "rollups.sqlite"))
        self.now = Now(stale_s=int(cfg["stale_s"]))
        self.bus = Broadcaster()
        self.peers = Peers(cfg, self.store, on_mirrored=self._on_mirrored)
        self.cloud = Cloud(cfg, self.store, self.now, self.api_status_brief)
        self.sweep = Sweep(cfg, self.now, self.ingest)
        self.watch = Watch(cfg, self.now, self.bus, clk=self.clk)
        self.net = NetStat(cfg)
        self.opal = OpalLink(cfg)
        self.events = Events(cfg, send=self.cloud.send_events)
        self.quietwatch = QuietWatch(cfg, self.now, self.peers.state, self.cloud.state, self.events)
        self.live_key = Cloud._read(cfg["cloud"].get("live_key_file"))
        self.store.on_sealed.append(self._on_sealed)
        self.counts = {"ingest": 0, "push": 0, "pull": 0, "rejected": 0}
        self._backfill_seen = {}
        self._stop = threading.Event()
        self._replay_open()
        if not self.rollups.uids() and self.store.metas:
            threading.Thread(target=self.rollups.rebuild, args=(self.store,), daemon=True,
                             name="rebuild").start()

    # ---- startup -------------------------------------------------------
    def _replay_open(self):
        """Warm the 'now' table from the open log and the newest castings so a
        reboot does not blank the dashboard."""
        n = 0
        for row in self.store.read_open():
            if row.get("uid"):
                self.now.update(row)
                n += 1
        if n == 0:
            recent = self.store.list_metas()[-3:]
            for m in recent:
                try:
                    for row in self.store.rows_of(m["id"]):
                        if row.get("uid"):
                            self.now.update(row)
                except Exception:
                    pass
        log("service: warmed now-table with %d bins" % len(self.now.bins))

    # ---- ingest --------------------------------------------------------
    def clk(self):
        return clock.quality()

    def ingest(self, d, src="push", ip=None):
        uid = d.get("id")
        if not uid or not isinstance(uid, str) or len(uid) > 64:
            self.counts["rejected"] += 1
            return None
        if ip and not d.get("ip"):
            d["ip"] = ip
        row = {"ts": util.now(), "clk": self.clk(), "uid": uid, "name": d.get("name"),
               "room": self.cfg["room"], "edge": self.cfg["edge"], "src": src, "d": d}
        self.store.append(row)
        entry = self.now.update(row)
        self.bus.publish("row", {"uid": uid, "entry": entry})
        self.counts["ingest"] += 1
        self.counts[src] = self.counts.get(src, 0) + 1
        return row

    def ingest_batch(self, body, ip=None):
        """Backfill from a Bin's flash buffer: rows it could not push while
        every Burrow was out of reach. Rows keep their own timestamps and
        go into the open log as src "backfill" (sealed into the castings
        of their own windows, never into the now-table). A row stamped by
        an estimated clock ("est"/"none") is re-based by the difference
        between our clock and the Bin's `now`, if it comes from the same
        boot as `now`; an estimate from an earlier boot stays as it is.
        Rows that still land before 2017 or in the future are dropped."""
        uid = body.get("id")
        rows = body.get("rows")
        if not uid or not isinstance(uid, str) or len(uid) > 64 or not isinstance(rows, list):
            return None
        now = util.now()
        try:
            shift = now - int(body.get("now") or now)
        except (TypeError, ValueError):
            shift = 0
        boot = body.get("boot")
        ident = {k: body[k] for k in ("name", "bin") if body.get(k) is not None}
        n = dup = dropped = 0
        for r in rows:
            try:
                ts = int(r["ts"])
                clk = r.get("clk", "none")
                if clk != "ok":
                    if r.get("boot") == boot:
                        ts += shift
                    clk = "est"
                if ts < 1500000000 or ts > now + 600:
                    dropped += 1
                    continue
                key = (uid, ts)
                if key in self._backfill_seen:
                    dup += 1
                    continue
                self._backfill_seen[key] = True
                if len(self._backfill_seen) > 50000:
                    for k in list(self._backfill_seen)[:10000]:
                        del self._backfill_seen[k]
                d = dict(r.get("d") or {})
                d.update(ident)
                d["id"] = uid
                if ip and not d.get("ip"):
                    d["ip"] = ip
                row = {"ts": ts, "clk": "bin-" + clk, "uid": uid, "name": ident.get("name"),
                       "room": self.cfg["room"], "edge": self.cfg["edge"], "src": "backfill", "d": d}
                self.store.append(row)
                n += 1
            except (KeyError, TypeError, ValueError):
                dropped += 1
        self.counts["backfill"] = self.counts.get("backfill", 0) + n
        if n or dropped:
            log("backfill: %s sent %d rows: %d kept, %d dup, %d unplaceable (shift %+ds)"
                % (ident.get("name") or uid, len(rows), n, dup, dropped, shift))
        return {"ok": True, "n": n, "dup": dup, "dropped": dropped, "ts": now}

    def _on_sealed(self, meta, rows):
        try:
            self.rollups.ingest_casting(rows)
        except Exception as e:
            log("service: rollups for %s failed: %s" % (meta["id"], e))

    def _on_mirrored(self, meta):
        try:
            rows = self.store.rows_of(meta["id"])
            self.rollups.ingest_casting(rows)
            # A mirrored casting also tells us about Bins we never heard directly.
            for row in rows[-200:]:
                if row.get("uid"):
                    self.now.merge(row["uid"], Now.entry_from_row(row))
        except Exception as e:
            log("service: mirror post-processing failed:", e)

    # ---- API -----------------------------------------------------------
    def api_now(self):
        return {"ts": util.now(), "edge": self.cfg["edge"], "room": self.cfg["room"],
                "edges": {self.cfg["edge"]: self.api_status_brief()},
                "bins": self.now.snapshot()}

    def api_bins(self):
        out = {}
        for uid, e in self.now.snapshot(max_age=365 * 86400).items():
            out[uid] = {"name": e.get("name"), "team": e.get("team"), "period": e.get("period"),
                        "bin": e.get("bin"), "room": e.get("home_room") or e.get("room"), "seen": e.get("ts")}
        return out

    def api_history(self, q):
        uid = (q.get("uid") or [None])[0]
        if not uid:
            raise ValueError("uid required")
        now = util.now()
        t_to = int((q.get("to") or [now])[0])
        t_from = int((q.get("from") or [t_to - 86400])[0])
        step = (q.get("step") or [None])[0]
        if step not in ("5m", "1h"):
            step = "5m" if (t_to - t_from) <= 3 * 86400 else "1h"
        pts = self.rollups.query(uid, t_from, t_to, step)
        return {"uid": uid, "step": step, "from": t_from, "to": t_to, "points": pts}

    def tunnel_state(self):
        """What tunnel-watchdog.py last found out about this room's Opal
        (/run/tunnel-watchdog.json), or {} when it is not installed."""
        path = self.cfg.get("tunnel_state", "/run/tunnel-watchdog.json")
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def tunnel_brief(self):
        t = self.tunnel_state()
        if not t:
            return None
        ev = (t.get("events") or [[None, None]])[-1]
        rep = t.get("repeater") or {}
        return {"state": t.get("state"), "checked": t.get("last_check"), "down_since": t.get("down_since"),
                "upstream": rep.get("ssid"), "signal": rep.get("signal"), "cloud_ok": t.get("cloud_ok"),
                "clients": t.get("clients"), "reboots": len(t.get("reboots") or []),
                "wifi_fallback": t.get("wifi_fallback"), "last_event": ev[1], "last_event_at": ev[0]}

    def api_status_brief(self):
        st = self.store.stats()
        return {"edge": self.cfg["edge"], "room": self.cfg["room"], "ts": util.now(),
                "clk": self.clk(), "up_s": util.now() - self.started, "version": VERSION,
                "castings": st["castings"], "unverified": st["unverified"],
                "disk_pct": round(st["disk_pct"], 1),
                "cloud_ok": self.cloud.state.get("reachable"), "cloud_last_ok": self.cloud.state.get("last_ok"),
                "peers_ok": sum(1 for p in self.peers.state.values() if p.get("ok")),
                "bins": len(self.now.snapshot()), "live_clients": self.bus.count(),
                "watching": len(self.watch.status()), "net": self.net.brief(),
                "events": self.events.state, "quiet": sorted(self.quietwatch.quiet),
                "tunnel": self.tunnel_brief()}

    def api_status(self):
        b = self.api_status_brief()
        b.update({"store": self.store.stats(), "peers": self.peers.status(), "cloud": self.cloud.status(),
                  "sweep": self.sweep.last, "watch": self.watch.status(), "net": self.net.state, "counts": self.counts,
                  "recent_events": self.events.recent[-50:],
                  "clock": clock.detail(),
                  "tunnel": self.tunnel_state() or None,
                  "config": {k: v for k, v in self.cfg.items() if k not in ("cloud",)}})
        return b

    # ---- loops ---------------------------------------------------------
    def _loop(self, name, every_s, fn, first_delay=0):
        def run():
            if first_delay:
                self._stop.wait(first_delay)
            tick = Every(every_s)
            while not self._stop.is_set():
                if tick.ready():
                    try:
                        fn()
                    except Exception as e:
                        log("%s: loop error: %r" % (name, e))
                self._stop.wait(1)
        t = threading.Thread(target=run, name=name, daemon=True)
        t.start()
        return t

    def _cloud_pass(self):
        if self.cloud.pass_once():
            self.events.kick()          # the link is proven: push anything still queued

    def start(self):
        self.httpd = server.serve(self)
        c = self.cfg
        self.events.start()
        self.events.emit("burrow.start", "%s v%s started (room %s)" % (c["edge"], VERSION, c["room"]), "info",
                         {"version": VERSION, "queued": self.events.state["queued"]})
        self._loop("fsync", int(c["fsync_s"]), self.store.fsync)
        self._loop("seal", 10, self.store.seal)
        self._loop("peers", int(c["replicate_every_s"]), self.peers.replicate_all, first_delay=15)
        self._loop("cloud", int(c["cloud"]["every_s"]), self._cloud_pass, first_delay=20)
        self._loop("quiet", 10, self.quietwatch.tick, first_delay=30)
        self._loop("peerwatch", 20, self.peers.watch, first_delay=25)
        self._loop("sweep", int(c["sweep"]["every_s"]), self.sweep.run, first_delay=60)
        self._loop("reclaim", 3600, self.store.reclaim, first_delay=300)
        # staggered by room so two Burrows never test the same iperf3 server at once
        if self.net.every_s > 0:
            self._loop("net", self.net.every_s, self.net.run_all, first_delay=120 + 200 * int(c["room"]))
        log("service: %s (room %s) v%s up" % (c["edge"], c["room"], VERSION))

    def stop(self):
        self._stop.set()
        self.events.stop()
        try:
            self.store.fsync()
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


def main(argv=None):
    import argparse
    import signal
    ap = argparse.ArgumentParser(description="Burrow edge service")
    ap.add_argument("--config", help="path to burrow.json")
    ap.add_argument("--rebuild-rollups", action="store_true", help="recompute rollups.sqlite from castings and exit")
    a = ap.parse_args(argv)
    cfg = config.load(a.config)
    svc = Service(cfg)
    if a.rebuild_rollups:
        svc.rollups.rebuild(svc.store)
        return 0
    svc.start()
    done = threading.Event()
    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, lambda *_: done.set())
    while not done.is_set():
        time.sleep(0.5)
    log("service: stopping")
    svc.stop()
    return 0
