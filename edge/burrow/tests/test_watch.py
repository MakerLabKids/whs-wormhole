import threading
import time
import unittest

from burrow.state import Broadcaster, Now
from burrow.watch import Watch

UID = "e66118604b7c2b2a"


def cfg():
    return {"edge": "burrow1", "room": 1, "watch": {"every_s": 0.05, "timeout_s": 0.2, "max_bins": 2}}


class FakePico:
    """Answers like a Bin's /data page; counts the polls."""
    def __init__(self, uid=UID, fail=False):
        self.uid, self.fail, self.calls, self.ips = uid, fail, 0, []

    def __call__(self, ip, timeout):
        self.calls += 1
        self.ips.append(ip)
        if self.fail:
            raise OSError("no route")
        return {"id": self.uid, "name": "Dirt Vader", "in_temp_c": 20.0 + self.calls, "bin": {"team": "Dirt Vader", "bin": 7}}


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.now = Now()
        self.now.update({"ts": 1, "uid": UID, "edge": "burrow1", "room": 1, "src": "push",
                         "d": {"id": UID, "ip": "192.168.81.120"}})
        self.bus = Broadcaster()
        self.q = self.bus.subscribe()

    def drain(self, n, timeout=1.0):
        out, t0 = [], time.monotonic()
        while len(out) < n and time.monotonic() - t0 < timeout:
            try:
                out.append(self.q.get(timeout=0.1))
            except Exception:
                pass
        return out

    def test_polls_while_watched_and_stops_after(self):
        pico = FakePico()
        w = Watch(cfg(), self.now, self.bus, clk=lambda: "ntp", fetch=pico)
        self.assertTrue(w.add(UID))
        msgs = self.drain(3)
        self.assertEqual(len(msgs), 3)
        self.assertTrue(all(m.startswith("event: live\n") for m in msgs))
        self.assertIn('"src":"live"', msgs[0])
        self.assertIn('"ip":"192.168.81.120"', msgs[0])       # the address is filled in like a sweep pull
        self.assertEqual(pico.ips[0], "192.168.81.120")
        self.assertEqual(w.status()[UID]["viewers"], 1)
        w.remove(UID)
        self.assertEqual(w.status(), {})
        time.sleep(0.15)
        n = pico.calls
        time.sleep(0.2)
        self.assertEqual(pico.calls, n)                        # the thread really stopped
        self.assertEqual(self.now.bins[UID]["ts"], 1)          # now-table untouched: ts still 1

    def test_one_poller_for_many_viewers(self):
        pico = FakePico()
        w = Watch(cfg(), self.now, self.bus, fetch=pico)
        self.assertTrue(w.add(UID))
        self.assertTrue(w.add(UID))
        self.assertEqual(w.status()[UID]["viewers"], 2)
        self.assertEqual(sum(1 for t in threading.enumerate() if t.name.startswith("watch-")), 1)
        w.remove(UID)
        self.assertEqual(w.status()[UID]["viewers"], 1)         # still polling for the other viewer
        w.remove(UID)
        self.assertEqual(w.status(), {})

    def test_unknown_bin_or_too_many_is_refused(self):
        pico = FakePico()
        w = Watch(cfg(), self.now, self.bus, fetch=pico)
        self.assertFalse(w.add("nobody"))
        self.assertFalse(w.add(""))
        for i in range(2):
            uid = "aa%014d" % i
            self.now.update({"ts": 1, "uid": uid, "edge": "burrow1", "room": 1, "src": "push", "d": {"id": uid, "ip": "192.168.81.%d" % (10 + i)}})
            self.assertTrue(w.add(uid))
        self.assertFalse(w.add(UID))                           # max_bins = 2
        for i in range(2):
            w.remove("aa%014d" % i)

    def test_errors_are_counted_not_fatal(self):
        pico = FakePico(fail=True)
        w = Watch(cfg(), self.now, self.bus, fetch=pico)
        self.assertTrue(w.add(UID))
        time.sleep(0.25)
        st = w.status()[UID]
        self.assertGreaterEqual(st["errors"], 2)
        self.assertIsNone(st["last_ok"])
        self.assertEqual(self.drain(1, timeout=0.1), [])        # nothing published
        w.remove(UID)


if __name__ == "__main__":
    unittest.main()
