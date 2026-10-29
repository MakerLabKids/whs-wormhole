import json
import os
import shutil
import socket
import tempfile
import time
import unittest
import urllib.request

from burrow import config, store, util
from burrow.service import Service
from tests.fake_surface import FakeSurface


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http(method, url, body=None, headers=None, raw=False):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = body if raw else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw_body = r.read()
            return r.status, (raw_body if raw else json.loads(raw_body.decode()))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def make_service(tmp, edge, room, peers=None, cloud_url=None, token_file=None, live_key_file=None):
    cfg = config.load("/nonexistent")
    port = free_port()
    cfg.update(edge=edge, room=room, data_dir=os.path.join(tmp, edge), listen="127.0.0.1", port=port,
               www_dir=os.path.join(tmp, "www"), peers=peers or {}, seal_grace_s=0)
    cfg["cloud"].update(url=cloud_url or "", token_file=token_file or "/nonexistent",
                        live_key_file=live_key_file or "/nonexistent")
    cfg["sweep"]["enabled"] = False
    svc = Service(cfg)
    svc.start()
    svc.url = "http://127.0.0.1:%d" % port
    return svc


def bin_payload(uid="e66118604b7c2b2a", name="Dirt Vader", **extra):
    d = {"id": uid, "name": name, "ip": "192.168.81.120", "ssid": "WormHole", "mode": "joined",
         "net": "WormHole", "in_temp_c": 21.4, "in_hum_pct": 60.1, "moist1_pct": 44.0,
         "probe_temps_c": [20.5], "relay": 0, "ok": True,
         "bin": {"team": name, "period": 3, "bin": 7, "room": 1}, "up": 1234, "rssi": -61}
    d.update(extra)
    return d


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "www"))
        with open(os.path.join(self.tmp, "www", "index.html"), "w") as f:
            f.write("<h1>dash</h1>")
        self.services = []

    def tearDown(self):
        for s in self.services:
            s.stop()
            s.store.close()
        shutil.rmtree(self.tmp)

    def svc(self, *a, **k):
        s = make_service(self.tmp, *a, **k)
        self.services.append(s)
        return s

    def test_ingest_now_history_and_static(self):
        s = self.svc("burrow1", 1)
        code, j = http("POST", s.url + "/ingest", bin_payload())
        self.assertEqual(code, 200)
        self.assertTrue(j["ok"])
        self.assertEqual(j["edge"], "burrow1")
        code, now = http("GET", s.url + "/api/now")
        e = now["bins"]["e66118604b7c2b2a"]
        self.assertEqual(e["team"], "Dirt Vader")
        self.assertEqual(e["d"]["in_temp_c"], 21.4)
        self.assertFalse(e["stale"])
        code, h = http("GET", s.url + "/health")
        self.assertEqual(h["room"], 1)
        code, bins = http("GET", s.url + "/api/bins")
        self.assertEqual(bins["e66118604b7c2b2a"]["bin"], 7)
        code, body = http("GET", s.url + "/", raw=True)
        self.assertIn(b"dash", body)
        code, body = http("GET", s.url + "/bin/anything", raw=True)   # SPA fallback
        self.assertIn(b"dash", body)
        code, j = http("POST", s.url + "/ingest", {"nope": 1})
        self.assertEqual(code, 400)
        # the row is in the open log
        self.assertEqual(len(s.store.read_open()), 1)
        # history is empty until a seal; force one by backdating
        s.store.read_open()[0]
        rows = s.store.read_open()
        rows[0]["ts"] -= 2000
        util.atomic_write(s.store._open_path, (json.dumps(rows[0]) + "\n").encode())
        s.store._reopen()
        made = s.store.seal()
        self.assertEqual(len(made), 1)
        code, hist = http("GET", s.url + "/api/history?uid=e66118604b7c2b2a&from=%d&to=%d" % (
            rows[0]["ts"] - 600, rows[0]["ts"] + 100))
        self.assertEqual(hist["step"], "5m")
        self.assertEqual(len(hist["points"]), 1)
        self.assertEqual(hist["points"][0][1]["in_temp_c"][3], 1)
        code, st = http("GET", s.url + "/api/status")
        self.assertEqual(st["store"]["castings"], 1)
        self.assertEqual(st["counts"]["push"], 1)

    def test_tunnel_requests_need_key(self):
        kf = os.path.join(self.tmp, "live.key")
        with open(kf, "w") as f:
            f.write("sekrit\n")
        s = self.svc("burrow1", 1, live_key_file=kf)
        code, _ = http("GET", s.url + "/api/now", headers={"CF-Ray": "abc"})
        self.assertEqual(code, 403)
        code, _ = http("GET", s.url + "/api/now", headers={"CF-Ray": "abc", "X-Burrow-Key": "wrong"})
        self.assertEqual(code, 403)
        code, _ = http("GET", s.url + "/api/now", headers={"CF-Ray": "abc", "X-Burrow-Key": "sekrit"})
        self.assertEqual(code, 200)
        code, _ = http("GET", s.url + "/api/now")        # LAN: open
        self.assertEqual(code, 200)

    def test_sse_hello_and_row(self):
        s = self.svc("burrow1", 1)
        http("POST", s.url + "/ingest", bin_payload())
        req = urllib.request.Request(s.url + "/live")
        r = urllib.request.urlopen(req, timeout=5)
        line = r.readline().decode()
        self.assertEqual(line.strip(), "event: hello")
        data = json.loads(r.readline().decode()[6:])
        self.assertIn("e66118604b7c2b2a", data["bins"])
        r.readline()
        http("POST", s.url + "/ingest", bin_payload(in_temp_c=30.0))
        self.assertEqual(r.readline().decode().strip(), "event: row")
        row = json.loads(r.readline().decode()[6:])
        self.assertEqual(row["entry"]["d"]["in_temp_c"], 30.0)
        r.close()

    def test_watch_streams_live_events_while_connected(self):
        """?watch=<uid> makes the Burrow poll that Bin's /data once a second and fan it out as
        `event: live`; the poller stops when the client goes away; nothing is stored."""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        calls = {"n": 0}

        class Pico(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                calls["n"] += 1
                body = json.dumps(bin_payload(in_temp_c=40.0 + calls["n"])).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        pico = HTTPServer(("127.0.0.1", 0), Pico)
        threading.Thread(target=pico.serve_forever, daemon=True).start()
        s = self.svc("burrow1", 1)
        s.cfg["watch"]["every_s"] = 0.1
        s.watch.every_s = 0.1
        http("POST", s.url + "/ingest", bin_payload(ip="127.0.0.1:%d" % pico.server_port))
        r = urllib.request.urlopen(urllib.request.Request(s.url + "/live?watch=e66118604b7c2b2a,nobody"), timeout=5)
        self.assertEqual(r.readline().decode().strip(), "event: hello")
        hello = json.loads(r.readline().decode()[6:])
        self.assertEqual(hello["watching"], ["e66118604b7c2b2a"])
        r.readline()
        self.assertEqual(r.readline().decode().strip(), "event: live")
        live = json.loads(r.readline().decode()[6:])
        self.assertEqual(live["entry"]["src"], "live")
        self.assertGreater(live["entry"]["d"]["in_temp_c"], 40.0)
        self.assertEqual(s.api_status()["watch"]["e66118604b7c2b2a"]["viewers"], 1)
        self.assertEqual(s.api_status_brief()["watching"], 1)
        r.close()
        for _ in range(30):
            if not s.watch.status():
                break
            time.sleep(0.1)
        self.assertEqual(s.watch.status(), {})
        n = calls["n"]
        time.sleep(0.3)
        self.assertEqual(calls["n"], n)                           # poller gone with the client
        self.assertEqual(s.api_now()["bins"]["e66118604b7c2b2a"]["d"]["in_temp_c"], 21.4)   # the pushed value, not a live one
        self.assertEqual(s.counts["ingest"], 1)
        pico.shutdown()

    def test_events_reach_the_surface_and_the_watchdog_can_report(self):
        fs = FakeSurface(token="tok1")
        tf = os.path.join(self.tmp, "tok1"); open(tf, "w").write("tok1")
        s = self.svc("burrow1", 1, cloud_url=fs.url, token_file=tf)
        for _ in range(50):           # the start event goes out on its own
            if fs.events: break
            time.sleep(0.05)
        self.assertEqual(fs.events[0]["kind"], "burrow.start")
        code, j = http("POST", s.url + "/api/event", {"kind": "opal", "level": "alert", "text": "down 15 min: rebooted the Opal (#1)"})
        self.assertEqual((code, j["ok"]), (200, True))
        for _ in range(50):
            if len(fs.events) >= 2: break
            time.sleep(0.05)
        self.assertEqual((fs.events[1]["kind"], fs.events[1]["level"]), ("opal", "alert"))
        code, j = http("GET", s.url + "/api/events")
        self.assertEqual([e["kind"] for e in j["events"]], ["burrow.start", "opal"])
        self.assertEqual(s.api_status_brief()["events"]["sent"], 2)
        fs.close()

    def test_peer_replication_and_cloud_cycle(self):
        tok = os.path.join(self.tmp, "cloud.token")
        with open(tok, "w") as f:
            f.write("test-token\n")
        surface = FakeSurface()
        try:
            a = self.svc("burrow1", 1, cloud_url=surface.url, token_file=tok)
            b = self.svc("burrow2", 2, peers={"burrow1": a.url})
            # Burrow 1 gets a casting (backdated row so it seals immediately)
            http("POST", a.url + "/ingest", bin_payload())
            rows = a.store.read_open()
            rows[0]["ts"] -= 2000
            util.atomic_write(a.store._open_path, (json.dumps(rows[0]) + "\n").encode())
            a.store._reopen()
            m = a.store.seal()[0]
            # Burrow 2 pulls it
            self.assertEqual(b.peers.replicate_all(), 1)
            self.assertTrue(b.store.has(m["id"]))
            self.assertEqual(b.store.metas[m["id"]]["mirrored_from"], "burrow1")
            # ...and now knows the bin for its own dashboard + history
            code, now = http("GET", b.url + "/api/now")
            self.assertIn("e66118604b7c2b2a", now["bins"])
            pts = b.rollups.query("e66118604b7c2b2a", rows[0]["ts"] - 400, rows[0]["ts"] + 400, "5m")
            self.assertEqual(len(pts), 1)
            # second pass: nothing new, peer marked ok
            self.assertEqual(b.peers.replicate_all(), 0)
            self.assertTrue(b.peers.state["burrow1"]["ok"])
            # Burrow 1 uploads: casting, rollups, verify -> verified
            self.assertTrue(a.cloud.pass_once())
            c = a.store.metas[m["id"]]["cloud"]
            self.assertTrue(c["uploaded_at"])
            self.assertTrue(c["rollups_at"])
            self.assertTrue(c["verified_at"])
            self.assertEqual(c["by"], "burrow1")
            self.assertEqual(len(surface.snapshots), 1)
            self.assertIn("roster", surface.snapshots[0])
            self.assertEqual(surface.snapshots[0]["bins"]["e66118604b7c2b2a"]["team"], "Dirt Vader")
            self.assertIn(("PUT", "/v1/edge/castings/" + m["id"]), surface.calls)
            # Burrow 2 learns verification from its peer on the next pull
            b.peers.replicate_all()
            self.assertTrue(b.store.metas[m["id"]]["cloud"]["verified_at"])
            # and Burrow 1, once it polls burrow2's index, records it as a replica holder
            a.peers.add("burrow2", b.url)
            a.peers.replicate_all()
            self.assertIn("burrow2", a.store.metas[m["id"]]["replicas"])
            # a second cloud pass does not re-upload
            n_puts = sum(1 for c in surface.calls if c[0] == "PUT")
            a.cloud.pass_once()
            self.assertEqual(sum(1 for c in surface.calls if c[0] == "PUT"), n_puts)
            # cloud deletes the object -> verify reports missing -> re-upload next pass
            surface.objects.pop(m["id"])
            a.store.mark_cloud(m["id"], verified_at=None)
            a.cloud.pass_once()
            self.assertIsNone(a.store.metas[m["id"]]["cloud"]["uploaded_at"])
            a.cloud.pass_once()
            self.assertTrue(a.store.metas[m["id"]]["cloud"]["verified_at"])
        finally:
            surface.close()

    def test_captive_portal_is_not_reachable(self):
        tok = os.path.join(self.tmp, "cloud.token")
        with open(tok, "w") as f:
            f.write("test-token\n")
        surface = FakeSurface(captive=True)
        try:
            a = self.svc("burrow1", 1, cloud_url=surface.url, token_file=tok)
            self.assertFalse(a.cloud.pass_once())
            self.assertFalse(a.cloud.state["reachable"])
            self.assertTrue(a.cloud.state["captive"])
        finally:
            surface.close()

    def test_no_cloud_configured(self):
        a = self.svc("burrow1", 1)
        self.assertFalse(a.cloud.enabled())
        self.assertFalse(a.cloud.pass_once())
        code, st = http("GET", a.url + "/api/status")
        self.assertFalse(st["cloud"]["enabled"])


if __name__ == "__main__":
    unittest.main()


class TunnelStateTest(ServiceTest):
    """The Opal watchdog's state file rides along in /api/status and in the
    status block of every cloud snapshot."""

    def test_brief_and_full_tunnel_state(self):
        path = os.path.join(self.tmp, "tunnel-state.json")
        with open(path, "w") as f:
            json.dump({"state": "upstream-down", "last_check": 1000, "down_since": 400, "cloud_ok": False,
                       "repeater": {"state_s": "idle", "ssid": None, "signal": None}, "clients": 3,
                       "uptime_s": 999, "reboots": [900], "wifi_fallback": "up",
                       "events": [[500, "repeater idle: joined BYLD", 4], [900, "down 8 min: rebooted the Opal (#1)"]]}, f)
        s = self.svc("burrow1", 1)
        s.cfg["tunnel_state"] = path
        brief = s.api_status_brief()["tunnel"]
        self.assertEqual(brief["state"], "upstream-down")
        self.assertEqual(brief["down_since"], 400)
        self.assertEqual(brief["reboots"], 1)
        self.assertEqual(brief["wifi_fallback"], "up")
        self.assertEqual(brief["clients"], 3)
        self.assertEqual(brief["last_event"], "down 8 min: rebooted the Opal (#1)")
        full = s.api_status()["tunnel"]
        self.assertEqual(full["uptime_s"], 999)
        self.assertEqual(len(full["events"]), 2)

    def test_no_watchdog_means_null(self):
        s = self.svc("burrow2", 2)
        s.cfg["tunnel_state"] = os.path.join(self.tmp, "absent.json")
        self.assertIsNone(s.api_status_brief()["tunnel"])
        self.assertIsNone(s.api_status()["tunnel"])
