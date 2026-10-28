import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import render_tunnel_json as rtj  # noqa: E402

ENV = {"router_admin": "A", "backhaul_key": "B", "qtastic_psk": "Q", "loki_psk": "L", "guess_psk": "G", "wormhole_psk": "W"}


def template():
    with open(os.path.join(HERE, "..", "etc", "tunnel.json.example")) as f:
        return json.load(f)


class RenderTest(unittest.TestCase):
    def test_room3_fills_every_placeholder(self):
        cfg = rtj.render(template(), ENV, 3)
        self.assertEqual(cfg["host"], "192.168.83.1")
        self.assertEqual(cfg["password"], "A")
        keys = {u["ssid"]: u.get("key") for u in cfg["upstreams"]}
        self.assertEqual(keys, {"WormHole-Core": "B", "Q-tastic": "Q", "BYLD": None, "Loki": "L", "Guess": "G"})
        self.assertEqual(cfg["wifi_fallback"]["key"], "W")
        self.assertNotIn("<", json.dumps(cfg))

    def test_room0_has_no_backhaul(self):
        cfg = rtj.render(template(), ENV, 0)
        self.assertEqual(cfg["host"], "192.168.80.1")
        self.assertEqual([u["ssid"] for u in cfg["upstreams"]], ["Q-tastic", "BYLD", "Loki", "Guess"])

    def test_missing_secret_is_an_error(self):
        env = dict(ENV)
        del env["loki_psk"]
        with self.assertRaises(KeyError):
            rtj.render(template(), env, 1)


if __name__ == "__main__":
    unittest.main()
