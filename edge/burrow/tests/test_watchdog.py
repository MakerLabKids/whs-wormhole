import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tunnel_watchdog", os.path.join(HERE, "..", "tunnel-watchdog.py"))
wd = importlib.util.module_from_spec(spec)
import sys
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "tools", "routers"))
spec.loader.exec_module(wd)


class Decide(unittest.TestCase):
    def test_connected_is_ok(self):
        self.assertEqual(wd.decide({"state_s": "connected"}, None, 1000), "ok")

    def test_idle_joins(self):
        self.assertEqual(wd.decide({"state_s": "idle", "running": False}, None, 1000), "join")

    def test_idle_waits_during_holdoff(self):
        self.assertEqual(wd.decide({"state_s": "connecting"}, 1000 - 30, 1000), "wait")

    def test_idle_joins_again_after_holdoff(self):
        self.assertEqual(wd.decide({"state_s": "idle"}, 1000 - wd.HOLDOFF_S - 1, 1000), "join")

    def test_empty_status_joins(self):
        self.assertEqual(wd.decide({}, None, 1000), "join")


if __name__ == "__main__":
    unittest.main()
