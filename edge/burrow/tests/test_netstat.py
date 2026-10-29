import json
import unittest

from burrow.netstat import NetStat, default_targets


def iperf_json(bps_received, error=None):
    if error:
        return json.dumps({"error": error})
    return json.dumps({"end": {"sum_sent": {"bits_per_second": bps_received * 1.1}, "sum_received": {"bits_per_second": bps_received}}})


class NetStatTest(unittest.TestCase):
    def test_default_targets_skip_self_and_use_tunnel_wan_addresses(self):
        self.assertEqual(default_targets(1), {"burrow0": "192.168.80.10", "burrow2": "192.168.80.22", "burrow3": "192.168.80.23"})
        self.assertEqual(sorted(default_targets(0)), ["burrow1", "burrow2", "burrow3"])

    def test_measures_up_and_down_from_what_the_receiver_got(self):
        calls = []
        def runner(host, reverse):
            calls.append((host, reverse))
            return iperf_json(195e6 if reverse else 92.4e6)
        n = NetStat({"room": 1, "net": {"targets": {"burrow0": "192.168.80.10"}}}, runner=runner, which=lambda x: "/usr/bin/iperf3")
        b = n.run_all()
        self.assertEqual(calls, [("192.168.80.10", False), ("192.168.80.10", True)])
        self.assertEqual(b["burrow0"]["up_mbps"], 92.4)
        self.assertEqual(b["burrow0"]["down_mbps"], 195.0)
        self.assertIsNone(b["burrow0"]["error"])
        self.assertEqual(len(n.state["burrow0"]["history"]), 1)

    def test_busy_server_is_an_error_and_keeps_the_last_good_numbers(self):
        answers = [iperf_json(50e6), iperf_json(60e6), iperf_json(0, error="the server is busy running a test. try again later")]
        n = NetStat({"room": 2, "net": {"targets": {"burrow1": "192.168.80.21"}}}, runner=lambda h, r: answers.pop(0), which=lambda x: "x")
        n.run_all()
        n.run_all()
        st = n.brief()["burrow1"]
        self.assertIn("busy", st["error"])
        self.assertEqual((st["up_mbps"], st["down_mbps"]), (50.0, 60.0))

    def test_missing_binary_is_reported_not_fatal(self):
        n = NetStat({"room": 3}, runner=lambda h, r: self.fail("must not run"), which=lambda x: None)
        b = n.run_all()
        self.assertTrue(all(v["error"] == "iperf3 not installed" for v in b.values()))
        self.assertEqual(sorted(b), ["burrow0", "burrow1", "burrow2"])


if __name__ == "__main__":
    unittest.main()
