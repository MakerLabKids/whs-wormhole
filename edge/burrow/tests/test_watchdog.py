"""tunnel-watchdog: pure decisions, the reboot schedule, and whole runs against
a fake Opal / fake cloud / fake Wi-Fi (no network, no clock)."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "tools", "routers"))
TMP = tempfile.mkdtemp()
os.environ["TUNNEL_CONFIG"] = os.path.join(TMP, "tunnel.json")
os.environ["BURROW_CONFIG"] = os.path.join(TMP, "burrow.json")
os.environ["TUNNEL_STATE"] = os.path.join(TMP, "state.json")
spec = importlib.util.spec_from_file_location("tunnel_watchdog", os.path.join(HERE, "..", "tunnel-watchdog.py"))
wd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wd)

H = 3600


class Decide(unittest.TestCase):
    def test_connected_with_cloud_is_ok(self):
        self.assertEqual(wd.decide({"state_s": "connected"}, True, None, 1000), "ok")

    def test_connected_without_cloud_switches(self):
        self.assertEqual(wd.decide({"state_s": "connected"}, False, None, 1000), "switch")

    def test_idle_joins(self):
        self.assertEqual(wd.decide({"state_s": "idle"}, False, None, 1000), "join")

    def test_holdoff_waits(self):
        self.assertEqual(wd.decide({"state_s": "connecting"}, False, 1000 - 30, 1000), "wait")
        self.assertEqual(wd.decide({"state_s": "idle"}, False, 1000 - wd.HOLDOFF_S - 1, 1000), "join")

    def test_empty_status_joins(self):
        self.assertEqual(wd.decide({}, False, None, 1000), "join")

    def test_cloud_unknown_counts_as_ok_when_connected(self):
        # no cloud_url configured: the repeater state is all we have
        self.assertEqual(wd.decide({"state_s": "connected"}, None, None, 1000), "ok")


class Upstreams(unittest.TestCase):
    UPS = [{"ssid": "BYLD", "encryption": "none", "key": "x"}, {"ssid": "WormHole-Core", "key": "k"}]

    def test_old_flat_config_is_one_upstream(self):
        ups = wd.upstreams_of({"host": "h", "password": "p", "ssid": "WormHole-Core", "key": "k", "band": "5g"})
        self.assertEqual(ups, [{"ssid": "WormHole-Core", "key": "k", "band": "5g"}])

    def test_new_list_wins(self):
        self.assertEqual(wd.upstreams_of({"upstreams": self.UPS, "ssid": "old"}), self.UPS)

    def test_prefers_first_visible(self):
        self.assertEqual(wd.pick_upstream(self.UPS, {"WormHole-Core", "BYLD"})["ssid"], "BYLD")
        self.assertEqual(wd.pick_upstream(self.UPS, {"WormHole-Core"})["ssid"], "WormHole-Core")
        self.assertIsNone(wd.pick_upstream(self.UPS, {"Other"}))

    def test_blind_pick_when_scan_failed(self):
        self.assertEqual(wd.pick_upstream(self.UPS, None)["ssid"], "BYLD")

    def test_switch_skips_the_dead_current_upstream(self):
        up = wd.pick_upstream(self.UPS, {"BYLD", "WormHole-Core"}, current_ssid="BYLD", current_failed=True)
        self.assertEqual(up["ssid"], "WormHole-Core")

    def test_hidden_upstream_is_dialed_blind(self):
        ups = [{"ssid": "BYLD"}, {"ssid": "Loki", "hidden": True}, {"ssid": "Guess"}]
        self.assertEqual(wd.pick_upstream(ups, {"Guess"})["ssid"], "Loki")        # hidden beats visible Guess
        self.assertEqual(wd.pick_upstream(ups, {"BYLD", "Guess"})["ssid"], "BYLD")  # but not a visible better one

    def test_missed_blind_join_moves_down_the_list(self):
        ups = [{"ssid": "Loki", "hidden": True}, {"ssid": "Guess"}]
        self.assertEqual(wd.pick_upstream(ups, {"Guess"}, skip_ssid="Loki")["ssid"], "Guess")
        # nothing else visible: the caller falls back to the plain pick, which is Loki again
        self.assertIsNone(wd.pick_upstream(ups, {"Other"}, skip_ssid="Loki"))
        self.assertEqual(wd.pick_upstream(ups, {"Other"})["ssid"], "Loki")

    def test_hidden_flag_is_not_sent_to_the_router(self):
        self.assertNotIn("hidden", wd.connect_params({"ssid": "Loki", "key": "k", "hidden": True}))

    def test_open_network_sends_no_key(self):
        self.assertNotIn("key", wd.connect_params(self.UPS[0]))
        self.assertIn("key", wd.connect_params(self.UPS[1]))


class ChronyKick(unittest.TestCase):
    ACT = "200 OK\n2 sources online\n0 sources offline\n0 sources doing burst (return to online)\n0 sources doing burst (return to offline)\n%d sources with unknown address\n"

    def test_unresolved_names_need_a_kick(self):
        self.assertTrue(wd.chrony_needs_kick(self.ACT % 6))

    def test_all_resolved_leaves_chrony_alone(self):
        self.assertFalse(wd.chrony_needs_kick(self.ACT % 0))
        self.assertFalse(wd.chrony_needs_kick(""))
        self.assertFalse(wd.chrony_needs_kick(None))


class RebootSchedule(unittest.TestCase):
    def test_first_reboot_after_15_minutes(self):
        self.assertFalse(wd.should_reboot(1000, [], 1000 + 14 * 60))
        self.assertTrue(wd.should_reboot(1000, [], 1000 + 15 * 60))

    def test_no_outage_no_reboot(self):
        self.assertFalse(wd.should_reboot(None, [], 99999))

    def test_then_hourly_three_times_then_daily(self):
        t0 = 1000
        r1 = t0 + 15 * 60
        self.assertEqual(wd.reboot_due_at(t0, [r1]), r1 + H)
        r2 = r1 + H
        self.assertEqual(wd.reboot_due_at(t0, [r1, r2]), r2 + H)
        r3 = r2 + H
        self.assertEqual(wd.reboot_due_at(t0, [r1, r2, r3]), r3 + H)
        r4 = r3 + H
        self.assertEqual(wd.reboot_due_at(t0, [r1, r2, r3, r4]), r4 + 86400)
        r5 = r4 + 86400
        self.assertEqual(wd.reboot_due_at(t0, [r1, r2, r3, r4, r5]), r5 + 86400)   # forever, daily

    def test_never_two_within_an_hour(self):
        t0 = 1000
        late_first = t0 + 5 * H      # the Pi was off; first reboot happened late
        self.assertGreaterEqual(wd.reboot_due_at(t0, [late_first]), late_first + H)


class Fallback(unittest.TestCase):
    SCAN = "AA\\:BB\\:CC\\:00\\:00\\:01:WormHole:70\nAA\\:BB\\:CC\\:00\\:00\\:02:WormHole:55\n" \
           "AA\\:BB\\:CC\\:00\\:00\\:03:BYLD:80\n:--:0\n"

    def test_parse_nmcli(self):
        rows = wd.parse_nmcli_scan(self.SCAN)
        self.assertEqual(rows[0], ("AA:BB:CC:00:00:01", "WormHole", 70))
        self.assertEqual(len(rows), 4)

    def test_picks_strongest_that_is_not_ours(self):
        rows = wd.parse_nmcli_scan(self.SCAN)
        self.assertEqual(wd.choose_fallback_bssid(rows, "WormHole", []), "AA:BB:CC:00:00:01")
        self.assertEqual(wd.choose_fallback_bssid(rows, "WormHole", ["aa:bb:cc:00:00:01"]), "AA:BB:CC:00:00:02")
        self.assertIsNone(wd.choose_fallback_bssid(rows, "WormHole", ["aa:bb:cc:00:00:01", "AA:BB:CC:00:00:02"]))


# ---- whole runs -----------------------------------------------------------
class FakeRouter:
    """Scripted Opal. state: repeater state_s; calls are recorded."""
    def __init__(self, host, timeout=8):
        self.host, self.timeout = host, timeout
        self.calls = []
        self.state = FakeRouter.NEXT_STATE
        self.visible = FakeRouter.NEXT_VISIBLE
        self.unreachable = FakeRouter.NEXT_UNREACHABLE
    NEXT_STATE = "connected"
    NEXT_VISIBLE = ["BYLD", "WormHole-Core"]
    NEXT_UNREACHABLE = False
    LOG = []

    def login(self, pw):
        if self.unreachable:
            raise OSError("timed out")

    def call(self, obj, method, params=None):
        FakeRouter.LOG.append((obj, method, params))
        if (obj, method) == ("repeater", "get_status"):
            return {"state_s": self.state, "ssid": "BYLD" if self.state == "connected" else None,
                    "signal": -61, "ipv4": {"ip": "10.1.2.3"}}
        if (obj, method) == ("repeater", "scan"):
            return {"res": [{"ssid": s} for s in self.visible]}
        if (obj, method) == ("system", "get_status"):
            return {"system": {"uptime": 12345, "load": [0.1, 0.1, 0.1]}}
        if (obj, method) == ("clients", "get_list"):
            return {"clients": [{"online": True}, {"online": False}, {"online": True}]}
        if (obj, method) == ("wifi", "get_config"):
            return {"res": [{"ifaces": [{"bssid": "94:83:C4:00:00:01"}]}, {"ifaces": [{"bssid": "94:83:C4:00:00:02"}]}]}
        return {}


class FakeWifi:
    def __init__(self, cfg):
        self.cfg = cfg
        self._up = FakeWifi.UP
        self.actions = FakeWifi.ACTIONS
    UP = False
    ACTIONS = []
    AVAILABLE = True

    def available(self):
        return FakeWifi.AVAILABLE and bool(self.cfg and self.cfg.get("ssid"))

    def is_up(self):
        return self._up

    def up(self, exclude):
        self.actions.append(("up", list(exclude)))
        self._up = True
        FakeWifi.UP = True
        return "AA:BB:CC:00:00:01"

    def down(self):
        self.actions.append(("down",))
        self._up = False
        FakeWifi.UP = False


def write(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


class Runs(unittest.TestCase):
    def setUp(self):
        write(wd.CONFIG, {"host": "192.168.81.1", "password": "pw",
                          "upstreams": [{"ssid": "BYLD", "device": "radio0", "band": "2g", "encryption": "none"},
                                        {"ssid": "WormHole-Core", "key": "k", "device": "radio1", "band": "5g",
                                         "encryption": "psk2"}],
                          "wifi_fallback": {"ssid": "WormHole", "key": "w"}})
        write(wd.BURROW_CONFIG, {"cloud": {"url": "https://surface.example"}})
        try:
            os.remove(wd.STATE)
        except OSError:
            pass
        FakeRouter.LOG = []
        FakeRouter.NEXT_STATE, FakeRouter.NEXT_UNREACHABLE = "connected", False
        FakeRouter.NEXT_VISIBLE = ["BYLD", "WormHole-Core"]
        FakeWifi.UP, FakeWifi.ACTIONS, FakeWifi.AVAILABLE = False, [], True
        self.cloud = True

    def run_at(self, t):
        return wd.main(now=t, router_factory=FakeRouter, cloud_check=lambda url: self.cloud, wifi_factory=FakeWifi)

    def state(self):
        return json.load(open(wd.STATE))

    def calls(self, obj, method):
        return [p for o, m, p in FakeRouter.LOG if (o, m) == (obj, method)]

    def test_healthy_run_records_diagnostics(self):
        self.run_at(1000)
        st = self.state()
        self.assertEqual(st["state"], "ok")
        self.assertTrue(st["cloud_ok"])
        self.assertEqual(st["repeater"]["ssid"], "BYLD")
        self.assertEqual(st["repeater"]["ip"], "10.1.2.3")
        self.assertEqual(st["clients"], 2)
        self.assertEqual(st["uptime_s"], 12345)
        self.assertEqual(st["own_bssids"], ["94:83:C4:00:00:01", "94:83:C4:00:00:02"])
        self.assertEqual(st["wifi_fallback"], "off")
        self.assertFalse(self.calls("repeater", "connect"))
        self.assertFalse(self.calls("system", "reboot"))

    def test_idle_repeater_joins_preferred_visible_upstream(self):
        FakeRouter.NEXT_STATE = "idle"
        self.cloud = False
        self.run_at(1000)
        c = self.calls("repeater", "connect")
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]["ssid"], "BYLD")
        self.assertNotIn("key", c[0])
        st = self.state()
        self.assertEqual(st["state"], "upstream-down")
        self.assertEqual(st["down_since"], 1000)
        # second run 60 s later: holdoff, no second join
        self.run_at(1060)
        self.assertEqual(len(self.calls("repeater", "connect")), 1)

    def test_falls_back_to_second_upstream_when_first_not_visible(self):
        FakeRouter.NEXT_STATE = "idle"
        FakeRouter.NEXT_VISIBLE = ["WormHole-Core", "Neighbour"]
        self.cloud = False
        self.run_at(1000)
        c = self.calls("repeater", "connect")
        self.assertEqual(c[0]["ssid"], "WormHole-Core")
        self.assertEqual(c[0]["key"], "k")

    def test_connected_without_internet_switches_upstream(self):
        self.cloud = False      # repeater says connected to BYLD but nothing gets out
        self.run_at(1000)
        c = self.calls("repeater", "connect")
        self.assertEqual(c[0]["ssid"], "WormHole-Core")
        self.assertEqual(self.state()["state"], "no-internet")

    def test_reboot_after_15_minutes_then_hourly_then_daily(self):
        FakeRouter.NEXT_STATE = "idle"
        self.cloud = False
        t = 1000
        for dt in range(0, 14 * 60, 120):
            self.run_at(t + dt)
        self.assertFalse(self.calls("system", "reboot"))
        self.run_at(t + 15 * 60 + 5)
        self.assertEqual(len(self.calls("system", "reboot")), 1)
        st = self.state()
        self.assertEqual(len(st["reboots"]), 1)
        self.assertGreaterEqual(st["next_reboot_at"], st["reboots"][0] + H)
        # keeps failing: runs every 2 min for 5 hours -> reboots at +1h, +2h, +3h only
        for dt in range(15 * 60 + 120, 5 * H, 120):
            self.run_at(t + dt)
        self.assertEqual(len(self.calls("system", "reboot")), 4)
        # ...and then one more per day, not one per hour
        for dt in range(5 * H, 3 * 86400, 600):
            self.run_at(t + dt)
        self.assertEqual(len(self.calls("system", "reboot")), 4 + 2)
        events = self.state()["events"]
        self.assertTrue(any("rebooted the Opal" in e[1] for e in events))
        self.assertTrue(any(len(e) > 2 and e[2] > 1 for e in events))   # repeated joins folded, not flooding

    def test_outage_after_a_healthy_run_starts_the_clock(self):
        # healthy first (leaves down_since = None in the state file), then the uplink dies
        self.cloud = True
        self.run_at(1000)
        self.assertIsNone(self.state()["down_since"])
        self.cloud = False
        self.run_at(1120)                     # used to crash: None + REBOOT_AFTER_S
        self.assertEqual(self.state()["down_since"], 1120)
        self.assertTrue(self.calls("repeater", "connect"))

    def test_recovery_clears_outage_and_drops_wifi(self):
        FakeRouter.NEXT_STATE = "idle"
        self.cloud = False
        self.run_at(1000)
        self.run_at(1000 + 6 * 60)                  # 5 min down: Wi-Fi fallback comes up
        self.assertEqual(self.state()["wifi_fallback"], "up")
        self.assertEqual(FakeWifi.ACTIONS[0][0], "up")
        self.assertEqual(FakeWifi.ACTIONS[0][1], ["94:83:C4:00:00:01", "94:83:C4:00:00:02"])  # never our own Opal
        FakeRouter.NEXT_STATE = "connected"
        self.cloud = True
        self.run_at(1000 + 8 * 60)
        st = self.state()
        self.assertEqual(st["state"], "ok")
        self.assertIsNone(st["down_since"])
        self.assertEqual(st["reboots"], [])
        self.assertEqual(FakeWifi.ACTIONS[-1], ("down",))
        self.assertTrue(any("recovered after" in e[1] for e in st["events"]))

    def test_wifi_not_used_while_cloud_still_reachable(self):
        FakeRouter.NEXT_STATE = "idle"
        self.cloud = True        # e.g. the Pi already has another path
        self.run_at(1000)
        self.run_at(1000 + 10 * 60)
        self.assertEqual(self.state()["wifi_fallback"], "off")

    def test_opal_unreachable_is_reported_and_wifi_comes_up(self):
        FakeRouter.NEXT_UNREACHABLE = True
        self.cloud = False
        self.run_at(1000)
        st = self.state()
        self.assertEqual(st["state"], "opal-unreachable")
        self.assertFalse(st["opal_reachable"])
        self.run_at(1000 + 6 * 60)
        self.assertEqual(self.state()["wifi_fallback"], "up")
        self.assertFalse(self.calls("system", "reboot"))

    def test_no_radio_is_reported_not_fatal(self):
        FakeWifi.AVAILABLE = False
        FakeRouter.NEXT_STATE = "idle"
        self.cloud = False
        self.run_at(1000)
        self.run_at(1000 + 10 * 60)
        self.assertEqual(self.state()["wifi_fallback"], "unavailable")

    def test_old_flat_config_still_works(self):
        write(wd.CONFIG, {"host": "192.168.81.1", "password": "pw", "ssid": "WormHole-Core", "key": "k",
                          "bssid": "94:83:c4:84:d2:0c", "device": "radio1", "band": "5g", "encryption": "psk2"})
        FakeRouter.NEXT_STATE = "idle"
        self.cloud = False
        self.run_at(1000)
        c = self.calls("repeater", "connect")
        self.assertEqual(c[0]["ssid"], "WormHole-Core")
        self.assertEqual(c[0]["bssid"], "94:83:c4:84:d2:0c")
        self.assertEqual(self.state()["wifi_fallback"], "unavailable")   # no fallback block = none


if __name__ == "__main__":
    unittest.main()
