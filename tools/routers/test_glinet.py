"""Tests for the GL.iNet client: the login hash (from a captured 4.x handshake)
and the RPC plumbing, both without a router."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glinet


class LoginHashTest(unittest.TestCase):
    # a real challenge/response captured from a GL-SFT1200 on firmware 4.8.3
    CH = {"nonce": "v6uYIqzUhmEY63p2SzQqqBaDjYKeeL1G", "alg": 5,
          "salt": "YxNEl28A/yVt5SCj", "hash-method": "sha256"}
    EXPECT = "967f15aff9b71c0ade0d37189e254764802e57f21c827d0ca2a1ad8401838490"

    def test_matches_browser(self):
        self.assertEqual(glinet.login_hash("goodlife", self.CH), self.EXPECT)

    def test_wrong_password_differs(self):
        self.assertNotEqual(glinet.login_hash("nope", self.CH), self.EXPECT)

    def test_md5_hash_method(self):
        ch = dict(self.CH, **{"hash-method": "md5"})
        self.assertEqual(len(glinet.login_hash("goodlife", ch)), 32)


class RpcTest(unittest.TestCase):
    def test_login_then_call(self):
        seen = []

        def fake(payload):
            seen.append(payload)
            m = payload["method"]
            if m == "challenge":
                return {"result": LoginHashTest.CH}
            if m == "login":
                return {"result": {"sid": "SID123"}}
            # a "call": echo the object/method so we can assert the sid is passed
            p = payload["params"]
            return {"result": {"sid_used": p[0], "obj": p[1], "method": p[2]}}

        r = glinet.Router(opener=fake)
        r.login("goodlife")
        self.assertEqual(r.sid, "SID123")
        # the login hash the client sent matches the captured one
        login_call = [p for p in seen if p["method"] == "login"][0]
        self.assertEqual(login_call["params"]["hash"], LoginHashTest.EXPECT)
        out = r.call("system", "get_status")
        self.assertEqual(out, {"sid_used": "SID123", "obj": "system", "method": "get_status"})

    def test_init_payload(self):
        seen = []
        def fake(payload):
            seen.append(payload)
            if payload["params"][2] == "check_initialized":
                return {"result": {"initialized": False}}
            return {"result": {}}
        r = glinet.Router(opener=fake)
        self.assertFalse(r.is_initialized())
        r.init("SuperDuperSecret!")
        init = [p for p in seen if p["params"][2] == "init"][0]
        self.assertEqual(init["params"][1], "ui")
        self.assertEqual(init["params"][3], {"lang": "en", "username": "root", "password": "SuperDuperSecret!"})
        self.assertEqual(init["params"][0], "")   # unauth: empty sid

    def test_error_raises(self):
        r = glinet.Router(opener=lambda p: {"error": {"message": "Access denied", "code": -32000}})
        with self.assertRaises(glinet.RpcError):
            r.rpc("challenge", {"username": "root"})

    def test_password_from_env_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("gh=xxx\nrouter_admin='s3cret'\n")
            path = f.name
        try:
            self.assertEqual(glinet.password_from_env(env_file=path, key="router_admin"), "s3cret")
            self.assertIsNone(glinet.password_from_env(env_file=path, key="absent"))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
