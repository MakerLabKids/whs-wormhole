"""Website messages ride down to a Bin: Surface snapshot reply -> Burrow -> /ingest reply."""
import os
import shutil
import tempfile
import unittest

from tests.fake_surface import FakeSurface
from tests.test_service import make_service, http, bin_payload


class MessageRelayTest(unittest.TestCase):
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

    def test_messages_from_the_snapshot_reply_ride_on_the_ingest_reply(self):
        # nothing queued: the reply is as before
        st, r = http("POST", self.svc.url + "/ingest", bin_payload())
        self.assertEqual(st, 200)
        self.assertNotIn("messages", r)
        # the website queued two for this Bin and one for another
        self.fs.messages = [
            {"uid": "e66118604b7c2b2a", "slot": 1, "seq": 3, "pin": "1612", "title": "Go Worms!", "lines": ["feed us"]},
            {"uid": "e66118604b7c2b2a", "slot": 4, "seq": 1, "pin": "1612", "clear": True},
            {"uid": "other", "slot": 1, "seq": 9, "pin": "0000", "title": "not yours"},
        ]
        self.assertTrue(self.svc.cloud.pass_once())
        self.assertEqual(self.svc.cloud.state["messages"], 3)
        st, r = http("POST", self.svc.url + "/ingest", bin_payload())
        self.assertEqual(st, 200)
        self.assertEqual([m["slot"] for m in r["messages"]], [1, 4])
        self.assertEqual(r["messages"][0]["title"], "Go Worms!")
        st, r = http("POST", self.svc.url + "/ingest", bin_payload(uid="other", name="Other"))
        self.assertEqual([m["seq"] for m in r["messages"]], [9])
        st, r = http("POST", self.svc.url + "/ingest", bin_payload(uid="nobody", name="Nobody"))
        self.assertNotIn("messages", r)
        # the Bin's acks ride up in its push and reach the Surface in the snapshot
        st, r = http("POST", self.svc.url + "/ingest", bin_payload(msg_seq={"1": 3, "4": 1}))
        self.assertTrue(self.svc.cloud.pass_once())
        snap = self.fs.snapshots[-1]
        self.assertEqual(snap["bins"]["e66118604b7c2b2a"]["d"]["msg_seq"], {"1": 3, "4": 1})
        # the website took them off the list: the next reply carries none
        self.fs.messages = []
        self.assertTrue(self.svc.cloud.pass_once())
        st, r = http("POST", self.svc.url + "/ingest", bin_payload())
        self.assertNotIn("messages", r)


class MessageStateTest(unittest.TestCase):
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

    def test_the_bins_slots_ride_to_the_surface_but_not_into_the_archive(self):
        slots = [{"title": "Go Worms!", "lines": ["feed us"], "by": "Jamal K", "via": "bluetooth"}, None, None, None, None]
        st, r = http("POST", self.svc.url + "/ingest", bin_payload(msg_rev=7, msgs=slots))
        self.assertEqual(st, 200)
        row = self.svc.store.read_open()[-1]
        self.assertNotIn("msgs", row["d"])
        self.assertEqual(row["d"]["msg_rev"], 7)
        self.assertEqual(self.svc.msg_state["e66118604b7c2b2a"]["slots"], slots)
        self.assertTrue(self.svc.cloud.pass_once())
        snap = self.fs.snapshots[-1]
        self.assertEqual(snap["messages_state"]["e66118604b7c2b2a"]["rev"], 7)
        self.assertEqual(snap["messages_state"]["e66118604b7c2b2a"]["slots"][0]["title"], "Go Worms!")
        # a push without the slots (nothing changed) keeps the last report
        http("POST", self.svc.url + "/ingest", bin_payload(msg_rev=7))
        self.assertEqual(self.svc.msg_state["e66118604b7c2b2a"]["rev"], 7)


if __name__ == "__main__":
    unittest.main()


class UpdateRequestTest(unittest.TestCase):
    """The admin's Update click: the snapshot reply names a build, the service leaves a request for the root updater."""
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

    def test_request_file_is_written_once_per_build(self):
        import json
        self.fs.update_to = {"build": "abcdef1", "sha256": "00" * 32, "url": "https://codeload.github.com/x/tar.gz/abcdef1"}
        self.assertTrue(self.svc.cloud.pass_once())
        path = os.path.join(self.svc.cfg["data_dir"], "update-request.json")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(json.load(open(path))["build"], "abcdef1")
        os.remove(path)
        self.assertTrue(self.svc.cloud.pass_once())
        self.assertFalse(os.path.exists(path), "the same build is not requested twice")
