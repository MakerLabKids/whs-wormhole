import unittest
import setup_tunnel as st

WANT = st.desired(1, "w", "b")


def complete():
    return {"fw": "4.8.3", "lan_ip": "192.168.81.1",
            "wifi": {"res": [{"device": "radio0", "channel": 1,
                              "ifaces": [{"iface_name": "default_radio0", "ssid": "WormHole", "encryption": "psk2", "enabled": True}]}]},
            "repeater_cfg": {"auto": False, "smart_reconnect": True},
            "repeater_status": {"state_s": "connected", "ssid": "WormHole-Core"},
            "forwards": [{"src_dport": "8080", "dest_ip": "192.168.81.10", "proto": "tcp"},
                         {"src_dport": "22", "dest_ip": "192.168.81.10", "proto": "tcp"}]}


class Plan(unittest.TestCase):
    def test_complete_tunnel_needs_nothing(self):
        self.assertEqual(st.plan(complete(), WANT), [])

    def test_old_firmware_blocks_everything(self):
        s = complete(); s["fw"] = "4.3.28"
        self.assertEqual(st.plan(s, WANT), [("upgrade", "4.3.28")])

    def test_factory_box_gets_every_step_in_order_lan_last(self):
        s = {"fw": "4.8.3", "lan_ip": "192.168.8.1", "wifi": {"res": []}, "repeater_cfg": {"auto": True},
             "repeater_status": {"state_s": "idle"}, "forwards": []}
        self.assertEqual([w for w, _ in st.plan(s, WANT)], ["wifi", "repeater_cfg", "backhaul", "forward", "forward", "lan"])

    def test_missing_ssh_forward_alone_is_added(self):
        s = complete(); s["forwards"] = s["forwards"][:1]
        self.assertEqual([(w, p["src_dport"]) for w, p in st.plan(s, WANT)], [("forward", "22")])

    def test_room_channel_and_addresses(self):
        w3 = st.desired(3, "w", "b")
        self.assertEqual(w3["radio0"]["channel"], 11)
        self.assertEqual([f["dest_ip"] for f in w3["forwards"]], ["192.168.83.10"] * 2)
        self.assertEqual(w3["lan_ip"], "192.168.83.1")
        self.assertEqual(w3["backhaul"]["encryption"], "sae")

    def test_wrong_channel_redoes_wifi_only(self):
        s = complete(); s["wifi"]["res"][0]["channel"] = 6
        self.assertEqual([w for w, _ in st.plan(s, WANT)], ["wifi"])

    def test_old_backhaul_key_shows_as_not_connected(self):
        s = complete(); s["repeater_status"] = {"state_s": "idle"}
        self.assertEqual([w for w, _ in st.plan(s, WANT)], ["backhaul"])

    def test_redact_hides_keys(self):
        self.assertEqual(st.redact({"ssid": "x", "key": "secret"}), {"ssid": "x", "key": "<key>"})


if __name__ == "__main__":
    unittest.main()
