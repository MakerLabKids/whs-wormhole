import json
import os
import shutil
import tempfile
import time
import unittest

from burrow.events import Events, QuietWatch
from burrow.state import Now


class EventsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sent = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def events(self, send=None):
        return Events({"edge": "burrow1", "data_dir": self.tmp}, send=send)

    def test_emit_is_pushed_at_once_and_kept_locally(self):
        ev = self.events(send=lambda batch: self.sent.extend(batch) or True)
        ev.start()
        ev.emit("bin.quiet", "Dirt Vader silent", "warn", {"uid": "abc"})
        for _ in range(50):
            if self.sent:
                break
            time.sleep(0.02)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual((self.sent[0]["kind"], self.sent[0]["level"], self.sent[0]["edge"]), ("bin.quiet", "warn", "burrow1"))
        self.assertEqual(ev.state["sent"], 1)
        self.assertEqual(ev.state["queued"], 0)
        self.assertEqual(len(ev.recent), 1)
        ev.stop()

    def test_outage_buffers_on_disk_then_flushes_in_order(self):
        refuse = {"on": True}
        def send(batch):
            if refuse["on"]:
                raise OSError("no route")
            self.sent.extend(batch); return True
        ev = self.events(send=send)
        ev.start()
        ev.emit("a", "first"); ev.emit("b", "second")
        time.sleep(0.3)
        self.assertEqual(self.sent, [])
        self.assertEqual(ev.state["queued"], 2)
        self.assertIn("no route", ev.state["last_error"])
        self.assertEqual(len(json.load(open(os.path.join(self.tmp, "events-queue.json")))), 2)   # survives a reboot
        refuse["on"] = False
        ev.kick()
        for _ in range(50):
            if len(self.sent) == 2:
                break
            time.sleep(0.02)
        self.assertEqual([e["text"] for e in self.sent], ["first", "second"])
        self.assertEqual(ev.state["queued"], 0)
        ev.stop()
        # a new instance after a "reboot" starts from the persisted (now empty) queue
        self.assertEqual(Events({"edge": "burrow1", "data_dir": self.tmp}).state["queued"], 0)

    def test_queue_reloads_after_restart(self):
        ev = self.events()               # no sender: nothing leaves
        ev.emit("x", "kept")
        again = self.events()
        self.assertEqual(again.state["queued"], 1)
        self.assertEqual(again.queue[0]["text"], "kept")


class QuietWatchTest(unittest.TestCase):
    def setUp(self):
        self.now = Now(stale_s=180)
        self.emitted = []
        class Ev:
            def emit(s, kind, text, level="info", data=None): self.emitted.append((kind, level, text))
        self.peers = {"burrow2": {"ok": True, "last_try": 100}}
        self.cloud = {"reachable": True}
        self.w = QuietWatch({"stale_s": 180, "quiet_alert_s": 600}, self.now, self.peers, self.cloud, Ev())
        self.now.update({"ts": 1000, "uid": "u1", "edge": "burrow1", "room": 1, "src": "push",
                         "d": {"id": "u1", "ip": "192.168.81.5", "bin": {"team": "Dirt Vader", "bin": 7}}})

    def kinds(self, prefix=""):
        return [k for k, _, _ in self.emitted if k.startswith(prefix)]

    def test_bin_quiet_then_back_once_each(self):
        self.w.tick(t=1100); self.w.tick(t=1500)
        self.assertEqual(self.kinds(), [])
        self.w.tick(t=1700); self.w.tick(t=1800)
        self.assertEqual(self.kinds(), ["bin.quiet"])
        self.assertIn("Dirt Vader", self.emitted[0][2]); self.assertEqual(self.emitted[0][1], "warn")
        self.now.update({"ts": 1900, "uid": "u1", "edge": "burrow1", "room": 1, "src": "push", "d": {"id": "u1"}})
        self.w.tick(t=1905); self.w.tick(t=1910)
        self.assertEqual(self.kinds(), ["bin.quiet", "bin.back"])

    def test_peer_down_and_back(self):
        self.w.tick(t=1000)
        self.peers["burrow2"].update(ok=False, error="timed out")
        self.w.tick(t=1100); self.w.tick(t=1200)
        self.assertEqual(self.kinds("peer"), ["peer.down"])
        self.peers["burrow2"].update(ok=True)
        self.w.tick(t=1800)
        self.assertEqual(self.kinds("peer"), ["peer.down", "peer.back"])
        self.assertIn("13 min", [t for k, _, t in self.emitted if k == "peer.back"][0])

    def test_cloud_outage_is_reported_when_the_link_returns(self):
        self.w.tick(t=1000)
        self.cloud.update(reachable=False, error="HTTP 503")
        self.w.tick(t=1100)
        self.assertEqual(self.kinds("cloud"), ["cloud.down"])
        self.cloud.update(reachable=True)
        self.w.tick(t=1700)
        self.assertEqual(self.kinds("cloud"), ["cloud.down", "cloud.back"])
        self.assertIn("10 min", [t for k, _, t in self.emitted if k == "cloud.back"][0])


if __name__ == "__main__":
    unittest.main()
