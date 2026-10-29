import unittest
import site_check as sc


def status(**over):
    st = {"version": "0.1.0", "up_s": 5000, "clk": "ntp", "disk_pct": 5.2, "bins": 14, "live_clients": 1,
          "cloud": {"reachable": True, "captive": False},
          "tunnel": {"state": "ok", "upstream": "WormHole-Core", "signal": -44, "down_since": None},
          "net": {"burrow0": {"up_mbps": 170.0, "down_mbps": 190.0, "ms": 2.9, "loss_pct": 0.0, "at": 1000, "error": None},
                  "internet": {"up_mbps": 60.0, "down_mbps": 75.0, "ms": 9.0, "loss_pct": 0.0, "at": 1000, "error": None}},
          "events": {"queued": 0}, "quiet": []}
    st.update(over)
    return st


def levels(rep):
    return {c: l for l, w, c, d in rep.rows}


class Judge(unittest.TestCase):
    def test_healthy_tunnel_is_all_pass(self):
        rep = sc.Report(); sc.judge_status(rep, 1, status(), "school", now=1100)
        self.assertEqual(set(levels(rep).values()), {"PASS"})

    def test_portal_on_home_wifi_at_school_warns(self):
        rep = sc.Report()
        sc.judge_status(rep, 0, status(tunnel={"state": "ok", "upstream": "Loki", "signal": -40}), "school", now=1100)
        self.assertEqual(levels(rep)["Portal upstream"], "WARN")
        rep = sc.Report()
        sc.judge_status(rep, 0, status(tunnel={"state": "ok", "upstream": "BYLD", "signal": -40}), "school", now=1100)
        self.assertEqual(levels(rep)["Portal upstream"], "PASS")

    def test_bad_things_fail(self):
        rep = sc.Report()
        sc.judge_status(rep, 2, status(cloud={"reachable": False, "error": "HTTP 503", "captive": True},
                                        tunnel={"state": "upstream-down", "upstream": None, "signal": -80, "down_since": 900},
                                        net={"internet": {"up_mbps": None, "down_mbps": None, "ms": None, "loss_pct": 100.0, "at": 1000, "error": "unreachable"}},
                                        events={"queued": 7, "last_error": "no route"}, quiet=["u1"]), "school", now=1100)
        lv = levels(rep)
        self.assertEqual(lv["cloud"], "FAIL"); self.assertEqual(lv["captive portal"], "FAIL")
        self.assertEqual(lv["Opal"], "FAIL"); self.assertEqual(lv["signal"], "FAIL"); self.assertEqual(lv["Opal down"], "FAIL")
        self.assertEqual(lv["net internet"], "FAIL"); self.assertEqual(lv["events"], "WARN"); self.assertEqual(lv["quiet bins"], "WARN")

    def test_stale_or_slow_measurement_warns(self):
        rep = sc.Report()
        sc.judge_status(rep, 3, status(net={"internet": {"up_mbps": 1.0, "down_mbps": 2.0, "ms": 300, "loss_pct": 0, "at": 100, "error": None}}), "school", now=5000)
        self.assertEqual(levels(rep)["net internet"], "WARN")

    def test_tunnel_on_byld_warns_about_open_forwards(self):
        rep = sc.Report()
        sc.judge_status(rep, 1, status(tunnel={"state": "ok", "upstream": "BYLD", "signal": -50}), "school", now=1100)
        self.assertEqual(levels(rep)["Tunnel upstream"], "WARN")


if __name__ == "__main__":
    unittest.main()
