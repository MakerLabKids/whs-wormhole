import json
import unittest

from burrow.netstat import NetStat, default_targets


def iperf_json(bps_received, error=None):
    if error:
        return json.dumps({"error": error})
    return json.dumps({"end": {"sum_sent": {"bits_per_second": bps_received * 1.1}, "sum_received": {"bits_per_second": bps_received}}})


def fake_http(url, data=None, timeout=25):
    if url.endswith("bytes=0"):
        return 0, 0.03, 0.025
    if "__down" in url:
        n = int(url.split("bytes=")[1]); return n, n * 8 / 50e6, 0.03     # a 50 Mbit/s line
    return len(data), len(data) * 8 / 10e6, 0.03                        # 10 Mbit/s up


PING_OK = """PING 192.168.80.10 (192.168.80.10) 56(84) bytes of data.

--- 192.168.80.10 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 804ms
rtt min/avg/max/mdev = 2.113/3.418/6.902/1.733 ms
"""
PING_LOSSY = """--- 1.1.1.1 ping statistics ---
5 packets transmitted, 3 received, 40% packet loss, time 820ms
rtt min/avg/max/mdev = 11.0/12.5/15.0/1.2 ms
"""
PING_DEAD = """--- 10.9.9.9 ping statistics ---
5 packets transmitted, 0 received, 100% packet loss, time 4100ms
"""


def no_inet(extra=None):
    cfg = {"internet_bytes_down": 0, "internet_bytes_up": 0}
    cfg.update(extra or {})
    return cfg


class NetStatTest(unittest.TestCase):
    def test_parse_ping(self):
        self.assertEqual(NetStat.parse_ping(PING_OK), {"loss_pct": 0.0, "ms": 3.4, "ms_max": 6.9})
        self.assertEqual(NetStat.parse_ping(PING_LOSSY), {"loss_pct": 40.0, "ms": 12.5, "ms_max": 15.0})
        self.assertEqual(NetStat.parse_ping(PING_DEAD), {"loss_pct": 100.0, "ms": None, "ms_max": None})

    def test_every_row_carries_a_round_trip(self):
        pings, tcps = [], []
        def pinger(host, count=5): pings.append(host); return PING_LOSSY
        def tcp_pinger(host, port, count=5, timeout=1.0): tcps.append((host, port)); return {"ms": 3.4, "ms_max": 6.9, "loss_pct": 0.0}
        n = NetStat({"room": 1, "net": {"targets": {"burrow0": "192.168.80.10"}}}, runner=lambda h, r: iperf_json(80e6),
                    which=lambda x: "x", http=fake_http, pinger=pinger, tcp_pinger=tcp_pinger)
        b = n.run_all()
        self.assertEqual(pings, ["1.1.1.1"])                        # ICMP only for the internet row
        self.assertEqual(tcps, [("192.168.80.10", 5201)])           # peers: TCP handshake through the forwarded port
        self.assertEqual((b["burrow0"]["ms"], b["burrow0"]["loss_pct"]), (3.4, 0.0))
        self.assertEqual((b["internet"]["ms"], b["internet"]["loss_pct"], b["internet"]["ttfb_ms"]), (12.5, 40.0, 25))
        self.assertEqual(n.state["burrow0"]["history"][0][3:], [3.4, 0.0])

    def test_internet_leg_measures_down_up_and_latency(self):
        n = NetStat({"room": 1, "net": {"targets": {}}}, runner=lambda h, r: self.fail("no peers"), which=lambda x: "x", http=fake_http, pinger=lambda h, c=5: PING_OK, tcp_pinger=lambda h, p, c=5, t=1.0: {"ms": 1.0, "ms_max": 1.0, "loss_pct": 0.0})
        b = n.run_all()["internet"]
        self.assertEqual((b["down_mbps"], b["up_mbps"], b["ttfb_ms"]), (50.0, 10.0, 25))
        self.assertIsNone(b["error"])
        self.assertEqual(n.state["internet"]["host"], "speed.cloudflare.com")

    def test_internet_failure_is_an_error_row(self):
        def dead(url, data=None, timeout=25): raise OSError("Network is unreachable")
        n = NetStat({"room": 1, "net": {"targets": {}}}, which=lambda x: "x", http=dead, pinger=lambda h, c=5: PING_OK, tcp_pinger=lambda h, p, c=5, t=1.0: {"ms": 1.0, "ms_max": 1.0, "loss_pct": 0.0})
        self.assertIn("unreachable", n.run_all()["internet"]["error"])

    def test_default_targets_skip_self_and_use_tunnel_wan_addresses(self):
        self.assertEqual(default_targets(1), {"burrow0": "192.168.80.10", "burrow2": "192.168.80.22", "burrow3": "192.168.80.23"})
        self.assertEqual(sorted(default_targets(0)), ["burrow1", "burrow2", "burrow3"])

    def test_measures_up_and_down_from_what_the_receiver_got(self):
        calls = []
        def runner(host, reverse):
            calls.append((host, reverse))
            return iperf_json(195e6 if reverse else 92.4e6)
        n = NetStat({"room": 1, "net": no_inet({"targets": {"burrow0": "192.168.80.10"}})}, runner=runner, which=lambda x: "/usr/bin/iperf3", pinger=lambda h, c=5: PING_OK, tcp_pinger=lambda h, p, c=5, t=1.0: {"ms": 1.0, "ms_max": 1.0, "loss_pct": 0.0})
        b = n.run_all()
        self.assertEqual(calls, [("192.168.80.10", False), ("192.168.80.10", True)])
        self.assertEqual(b["burrow0"]["up_mbps"], 92.4)
        self.assertEqual(b["burrow0"]["down_mbps"], 195.0)
        self.assertIsNone(b["burrow0"]["error"])
        self.assertEqual(len(n.state["burrow0"]["history"]), 1)

    def test_busy_server_is_an_error_and_keeps_the_last_good_numbers(self):
        answers = [iperf_json(50e6), iperf_json(60e6), iperf_json(0, error="the server is busy running a test. try again later")]
        n = NetStat({"room": 2, "net": no_inet({"targets": {"burrow1": "192.168.80.21"}})}, runner=lambda h, r: answers.pop(0), which=lambda x: "x", pinger=lambda h, c=5: PING_OK, tcp_pinger=lambda h, p, c=5, t=1.0: {"ms": 1.0, "ms_max": 1.0, "loss_pct": 0.0})
        n.run_all()
        n.run_all()
        st = n.brief()["burrow1"]
        self.assertIn("busy", st["error"])
        self.assertEqual((st["up_mbps"], st["down_mbps"]), (50.0, 60.0))

    def test_missing_binary_is_reported_not_fatal(self):
        n = NetStat({"room": 3, "net": no_inet()}, runner=lambda h, r: self.fail("must not run"), which=lambda x: None, pinger=lambda h, c=5: PING_DEAD, tcp_pinger=lambda h, p, c=5, t=1.0: {"ms": None, "ms_max": None, "loss_pct": 100.0})
        b = n.run_all()
        self.assertTrue(all(v["error"] == "iperf3 not installed" for v in b.values()))
        self.assertEqual(sorted(b), ["burrow0", "burrow1", "burrow2"])


if __name__ == "__main__":
    unittest.main()
