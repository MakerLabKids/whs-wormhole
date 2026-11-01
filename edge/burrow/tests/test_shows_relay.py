"""Website shows ride down to a Bin: Surface snapshot reply -> Burrow (fetches + caches the files)
-> /ingest reply, and the Bin fetches each file from the Burrow at /shows/<sha>.pbm."""
import hashlib
import os
import shutil
import tempfile
import unittest
import urllib.request

from tests.fake_surface import FakeSurface
from tests.test_service import make_service, http, bin_payload

UID = "e66118604b7c2b2a"


def pbm(fill=0xFF, frames=1):
    return (b"P4\n128 64\n" + bytes([fill]) * 1024) * frames


class ShowRelayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fs = FakeSurface(token="tok1")
        tf = os.path.join(self.tmp, "cloud.token")
        with open(tf, "w") as f:
            f.write("tok1")
        self.svc = make_service(self.tmp, "burrow1", 1, cloud_url=self.fs.url, token_file=tf)

    def tearDown(self):
        self.svc.stop()
        self.fs.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def get(self, path):
        try:
            with urllib.request.urlopen(self.svc.url + path, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_shows_are_fetched_once_and_handed_to_the_bin_until_it_reports_the_rev(self):
        a, b = pbm(0xFF), pbm(0x0F, 3)
        sa, sb = hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest()
        self.fs.show_files = {sa: a, sb: b}
        self.fs.shows = [{"uid": UID, "rev": 4, "list": ["wiggle", "Worm Party"],
                          "files": [{"name": "sun", "sha256": sa, "size": len(a)}, {"name": "wiggle", "sha256": sb, "size": len(b)}]},
                         {"uid": "other", "rev": 1, "list": None, "files": []}]
        st, r = http("POST", self.svc.url + "/ingest", bin_payload())
        self.assertNotIn("shows", r)                                  # nothing until the cloud pass brings it
        self.assertTrue(self.svc.cloud.pass_once())
        fetched = [c for c in self.fs.calls if c[1].startswith("/v1/edge/shows/")]
        self.assertEqual(len(fetched), 2)
        st, r = http("POST", self.svc.url + "/ingest", bin_payload(shows_rev=3))
        self.assertEqual(r["shows"]["rev"], 4)
        self.assertEqual(r["shows"]["list"], ["wiggle", "Worm Party"])
        self.assertEqual([f["name"] for f in r["shows"]["files"]], ["sun", "wiggle"])
        # the Bin fetches from us, on the LAN, by sha256
        self.assertEqual(self.get("/shows/%s.pbm" % sb), (200, b))
        self.assertEqual(self.get("/shows/%s.pbm" % ("0" * 64))[0], 404)
        self.assertEqual(self.get("/shows/../../etc/passwd.pbm")[0], 400)
        # a second pass does not fetch again
        self.assertTrue(self.svc.cloud.pass_once())
        self.assertEqual(len([c for c in self.fs.calls if c[1].startswith("/v1/edge/shows/")]), 2)
        # once the board says rev 4, nothing more rides down, and shows_rev goes up in the snapshot
        st, r = http("POST", self.svc.url + "/ingest", bin_payload(shows_rev=4))
        self.assertNotIn("shows", r)
        self.assertTrue(self.svc.cloud.pass_once())
        self.assertEqual(self.fs.snapshots[-1]["bins"][UID]["d"]["shows_rev"], 4)
        # an empty bin list (the website removed everything) is handed over too
        st, r = http("POST", self.svc.url + "/ingest", bin_payload(uid="other", name="Other"))
        self.assertEqual(r["shows"], {"rev": 1, "list": None, "files": []})

    def test_a_file_that_does_not_match_its_sha256_is_not_kept_or_offered(self):
        good = pbm()
        sha = hashlib.sha256(good).hexdigest()
        self.fs.show_files = {sha: good + b"tampered"}
        self.fs.shows = [{"uid": UID, "rev": 1, "list": None, "files": [{"name": "sun", "sha256": sha, "size": len(good)}]}]
        self.assertTrue(self.svc.cloud.pass_once())
        self.assertIn("sha256", self.svc.cloud.state.get("shows_error", ""))
        st, r = http("POST", self.svc.url + "/ingest", bin_payload())
        self.assertNotIn("shows", r)                                  # not every file is here: wait
        self.assertEqual(self.get("/shows/%s.pbm" % sha)[0], 404)
        # bad names from the Surface are dropped, never used as paths
        self.fs.shows = [{"uid": UID, "rev": 2, "list": None, "files": [{"name": "../x", "sha256": sha}, {"name": "ok", "sha256": "nothex"}]}]
        self.fs.show_files = {}
        self.assertTrue(self.svc.cloud.pass_once())
        st, r = http("POST", self.svc.url + "/ingest", bin_payload())
        self.assertEqual(r["shows"]["files"], [])


if __name__ == "__main__":
    unittest.main()
