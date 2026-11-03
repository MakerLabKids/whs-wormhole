"""roles.py: an extra Pi never breaks a room (standby, takeover, guest on another Opal, step-down)."""
import json
import os
import shutil
import tempfile
import unittest

import roles


class FakeSys:
    def __init__(self):
        self.cmds = []
        self.primary_up = True        # does the room's .10 answer?
        self.gw_up = True             # does our gateway answer?
        self.ip = "192.168.82.10"
        self.has_carrier = True
        self.err = None               # the cloud error the local API reports
        self.enrol_reply = None
        self.enrols = []
        self.rebooted = False

    def run(self, *cmd, timeout=30):
        self.cmds.append(list(cmd))
        return 0, ""

    def http_ok(self, url, timeout=3):
        return self.gw_up if url.startswith("http://192.168.8") and url.rstrip("/").endswith(".1") else self.primary_up

    def ping(self, ip):
        return self.gw_up if ip.endswith(".1") else self.primary_up

    def eth_ipv4(self):
        return self.ip

    def carrier(self):
        return self.has_carrier

    def eth_con(self):
        return "Wired connection 1"

    def cloud_error(self):
        return self.err

    def enrol(self, url, body):
        self.enrols.append(body)
        return self.enrol_reply

    def serial(self):
        return "bbbb0000000000b2"

    def mac(self, dev):
        return "88:a2:9e:00:00:01"

    def reboot(self):
        self.rebooted = True

    def nm(self):
        return [c for c in self.cmds if c[:1] == ["nmcli"]]


class RolesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        j = lambda n: os.path.join(self.tmp, n)
        for name, val in (("CFG", j("burrow.json")), ("TUNNEL", j("tunnel.json")), ("STATE", j("data/role-state.json")),
                          ("CLOUD_TOKEN", j("cloud.token")), ("TUNNEL_TOKEN", j("cf/token")), ("SECRET", j("enrol.secret")),
                          ("EVENTS", j("role-events.log")), ("HOSTS", j("hosts"))):
            setattr(self, "_old_" + name, getattr(roles, name))
            setattr(roles, name, val)
        with open(roles.SECRET, "w") as f:
            f.write("s3cret")
        with open(roles.HOSTS, "w") as f:
            f.write("127.0.0.1\tlocalhost\n127.0.1.1\tburrow3\n")
        roles.save(roles.TUNNEL, {"host": "192.168.83.1", "upstreams": [{"ssid": "WormHole-Core"}, {"ssid": "BYLD"}]})
        os.makedirs(os.path.dirname(roles.TUNNEL_TOKEN))
        with open(roles.TUNNEL_TOKEN, "w") as f:
            f.write("donor-tunnel-token")
        self.sys = FakeSys()

    def tearDown(self):
        for name in ("CFG", "TUNNEL", "STATE", "CLOUD_TOKEN", "TUNNEL_TOKEN", "SECRET", "EVENTS", "HOSTS"):
            setattr(roles, name, getattr(self, "_old_" + name))
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cfg(self):
        return roles.load(roles.CFG, {})

    # ---- apply ----
    def test_a_standby_identity_has_no_tunnel_and_takes_dhcp(self):
        roles.apply_identity({"edge": "burrow2-sb-00b2", "room": 2, "role": "standby", "cloud_token": "tok"}, self.sys)
        c = self.cfg()
        self.assertEqual((c["edge"], c["room"], c["role"]), ("burrow2-sb-00b2", 2, "standby"))
        self.assertFalse(os.path.exists(roles.TUNNEL_TOKEN))                  # the donor's tunnel token is gone
        self.assertIn(["systemctl", "disable", "--now", "cloudflared"], self.sys.cmds)
        self.assertEqual(open(roles.CLOUD_TOKEN).read(), "tok")
        # the burrow service (group burrow) must be able to read it: 0640, never 0600
        self.assertEqual(os.stat(roles.CLOUD_TOKEN).st_mode & 0o777, 0o640)
        self.assertIn("auto", self.sys.nm()[-1])
        self.assertEqual(roles.load(roles.TUNNEL, {})["host"], "192.168.82.1")
        self.assertIn("127.0.1.1\tburrow2-sb-00b2", open(roles.HOSTS).read())
        self.assertNotIn("burrow3", open(roles.HOSTS).read())

    def test_a_primary_identity_gets_its_tunnel_and_static_10(self):
        roles.apply_identity({"edge": "burrow2", "room": 2, "role": "primary", "cloud_token": "t", "tunnel_token": "tt2"}, self.sys)
        self.assertEqual(open(roles.TUNNEL_TOKEN).read(), "tt2")
        self.assertIn(["systemctl", "enable", "cloudflared"], self.sys.cmds)
        self.assertIn("192.168.82.10/24", self.sys.nm()[-1])
        self.assertEqual(sorted(self.cfg()["peers"]), ["burrow0", "burrow1", "burrow3"])

    # ---- standby ----
    def standby(self):
        roles.save(roles.CFG, {"edge": "burrow2-sb-00b2", "room": 2, "role": "standby", "cloud": {"url": "https://s.example"}})

    def test_a_standby_waits_while_the_rooms_pi_answers(self):
        self.standby()
        for t in range(0, 3600, 120):
            self.assertEqual(roles.tick(1000 + t, self.sys), "ok")
        self.assertEqual(self.sys.enrols, [])

    def test_a_standby_takes_over_after_6_min_of_silence_if_the_surface_agrees(self):
        self.standby()
        self.sys.primary_up = False
        self.assertEqual(roles.tick(1000, self.sys), "waiting")
        self.assertEqual(roles.tick(1000 + 300, self.sys), "waiting")
        self.assertEqual(self.sys.enrols, [])
        self.sys.enrol_reply = {"edge": "burrow2", "room": 2, "role": "standby", "token": "x"}   # the Surface still hears it
        self.assertEqual(roles.tick(1000 + 361, self.sys), "waiting")
        self.assertTrue(self.sys.enrols[-1]["promote"])
        self.assertTrue(self.sys.enrols[-1]["standby_ok"])
        self.assertFalse(self.sys.rebooted)
        self.sys.enrol_reply = {"edge": "burrow2", "room": 2, "role": "primary", "token": "new", "tunnel_token": "tt2"}
        self.assertEqual(roles.tick(1000 + 481, self.sys), "promoted")
        self.assertTrue(self.sys.rebooted)
        self.assertEqual((self.cfg()["edge"], self.cfg()["role"]), ("burrow2", "primary"))
        self.assertEqual(open(roles.TUNNEL_TOKEN).read(), "tt2")

    def test_a_blip_resets_the_standby_clock(self):
        self.standby()
        self.sys.primary_up = False
        roles.tick(1000, self.sys)
        self.sys.primary_up = True
        roles.tick(1200, self.sys)
        self.sys.primary_up = False
        self.assertEqual(roles.tick(1400, self.sys), "waiting")                  # 200 s, not 400
        self.assertEqual(self.sys.enrols, [])

    # ---- primary: guest on another Opal ----
    def primary(self):
        roles.save(roles.CFG, {"edge": "burrow2", "room": 2, "role": "primary", "cloud": {"url": "https://s.example"}})

    def test_on_another_rooms_opal_it_takes_dhcp_keeps_its_name_and_comes_home(self):
        self.primary()
        self.sys.gw_up = False
        self.assertEqual(roles.tick(1000, self.sys), "ok")
        self.assertEqual(roles.tick(1000 + 120, self.sys), "ok")                  # an Opal reboot is shorter than this
        self.assertEqual(roles.tick(1000 + 300, self.sys), "guest")
        self.assertIn("auto", self.sys.nm()[-2])
        self.assertEqual(self.cfg()["edge"], "burrow2")                            # still itself
        self.sys.ip = "192.168.81.142"                                            # room 1's Opal gave it an address
        self.assertEqual(roles.tick(1000 + 420, self.sys), "guest")
        self.sys.ip = "192.168.82.150"                                            # plugged back into its own Opal
        self.assertEqual(roles.tick(1000 + 540, self.sys), "home")
        self.assertIn("192.168.82.10/24", self.sys.nm()[-2])

    def test_no_cable_is_not_a_reason_to_go_guest(self):
        self.primary()
        self.sys.gw_up, self.sys.has_carrier = False, False
        for t in range(0, 1800, 120):
            self.assertEqual(roles.tick(1000 + t, self.sys), "ok")
        self.assertEqual(self.sys.nm(), [])

    # ---- primary: replaced ----
    def test_a_replaced_pi_steps_down_after_10_min_of_refusals(self):
        self.primary()
        self.sys.err = "HTTP 401"
        self.assertEqual(roles.tick(1000, self.sys), "ok")
        self.assertEqual(roles.tick(1000 + 540, self.sys), "ok")
        self.sys.enrol_reply = {"edge": "burrow2-sb-00b2", "room": 2, "role": "standby", "token": "sbt"}
        self.assertEqual(roles.tick(1000 + 600, self.sys), "demoted")
        self.assertNotIn("promote", self.sys.enrols[-1])
        self.assertEqual((self.cfg()["edge"], self.cfg()["role"]), ("burrow2-sb-00b2", "standby"))
        self.assertTrue(self.sys.rebooted)

    def test_other_cloud_errors_are_not_a_takeover(self):
        self.primary()
        self.sys.err = "HTTP 503"
        for t in range(0, 3600, 120):
            roles.tick(1000 + t, self.sys)
        self.assertEqual(self.sys.enrols, [])


if __name__ == "__main__":
    unittest.main()
