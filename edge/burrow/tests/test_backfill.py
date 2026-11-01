"""Backfill: a Bin hands over rows it buffered while every Burrow was dark."""
import os
import shutil
import tempfile
import unittest

from burrow import util
from tests.test_service import make_service, http, bin_payload


class BackfillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.svc = make_service(self.tmp, "burrow1", 1)

    def tearDown(self):
        self.svc.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rows(self, t0, n, clk="ok", boot=7, step=60):
        return [{"ts": t0 + i * step, "clk": clk, "boot": boot,
                 "d": {"in_temp_c": 20 + i / 10, "moist1_pct": 40, "probe_temps_c_0": 19.5}}
                for i in range(n)]

    def test_rows_land_with_their_own_timestamps(self):
        now = util.now()
        t0 = now - 3 * 3600
        body = {"id": "e66118604b7c2b2a", "name": "Dirt Vader", "boot": 7, "now": now, "clk": "ok",
                "bin": {"team": "Dirt Vader", "period": 3, "bin": 7, "room": 1}, "rows": self.rows(t0, 5)}
        st, r = http("POST", self.svc.url + "/ingest/batch", body)
        self.assertEqual(st, 200)
        self.assertEqual((r["ok"], r["n"], r["dup"], r["dropped"]), (True, 5, 0, 0))
        kept = [x for x in self.svc.store.read_open() if x["src"] == "backfill"]
        self.assertEqual([x["ts"] for x in kept], [t0 + i * 60 for i in range(5)])
        self.assertEqual(kept[0]["clk"], "bin-ok")
        self.assertEqual(kept[0]["d"]["bin"]["team"], "Dirt Vader")
        self.assertEqual(kept[0]["d"]["id"], "e66118604b7c2b2a")
        self.assertEqual(kept[3]["d"]["in_temp_c"], 20.3)
        # never the now-table
        self.assertNotIn("e66118604b7c2b2a", self.svc.now.snapshot())

    def test_estimated_clock_is_rebased_for_the_same_boot_only(self):
        now = util.now()
        # the Bin's clock is 1000 s slow (it resumed from a saved time after a power cut)
        pico_now = now - 1000
        rows = self.rows(pico_now - 600, 3, clk="est", boot=9) + self.rows(pico_now - 7200, 2, clk="est", boot=8)
        body = {"id": "abc", "name": "x", "boot": 9, "now": pico_now, "clk": "est", "rows": rows}
        st, r = http("POST", self.svc.url + "/ingest/batch", body)
        self.assertEqual((st, r["n"]), (200, 5))
        kept = sorted(x["ts"] for x in self.svc.store.read_open() if x["src"] == "backfill")
        same_boot = [pico_now - 600 + i * 60 + 1000 for i in range(3)]       # shifted by +1000
        old_boot = [pico_now - 7200 + i * 60 for i in range(2)]              # left alone
        self.assertEqual(kept, sorted(same_boot + old_boot))
        self.assertTrue(all(x["clk"] == "bin-est" for x in self.svc.store.read_open() if x["src"] == "backfill"))

    def test_duplicates_and_undated_rows(self):
        now = util.now()
        rows = self.rows(now - 300, 3) + self.rows(now - 300, 3)            # the same batch twice (a resend)
        rows += [{"ts": 12345, "clk": "none", "boot": 1, "d": {"in_temp_c": 1}}]   # seconds since boot, old boot: undated
        rows += [{"ts": now + 7200, "clk": "ok", "boot": 7, "d": {"in_temp_c": 1}}]   # the future: undated
        rows += [{"d": {"in_temp_c": 1}}]                                    # no ts at all: undated
        rows += ["junk"]                                                     # not a row: the only thing ever dropped
        body = {"id": "abc", "name": "x", "boot": 7, "now": now, "clk": "ok", "rows": rows}
        st, r = http("POST", self.svc.url + "/ingest/batch", body)
        self.assertEqual((st, r["n"], r["dup"], r["undated"], r["dropped"]), (200, 6, 3, 3, 1))
        kept = [x for x in self.svc.store.read_open() if x["src"] == "backfill"]
        self.assertEqual(len(kept), 6)
        und = [x for x in kept if x["clk"] == "bin-undated"]
        self.assertEqual(len(und), 3)
        self.assertEqual(und[0]["boot"], 1)
        self.assertEqual(und[0]["up"], 12345)                                # seconds since that boot, kept
        self.assertTrue(all(abs(x["ts"] - now) < 5 for x in und), "filed under the arrival time")
        # a resend of the undated rows is a duplicate, not a second copy
        st, r = http("POST", self.svc.url + "/ingest/batch", body)
        self.assertEqual((r["n"], r["dup"]), (0, 9))          # all nine real rows again: dups, the junk dropped again

    def test_undated_rows_are_served_in_buffer_order_and_stay_off_the_timeline(self):
        now = util.now()
        rows = [{"ts": 900, "clk": "none", "boot": 3, "d": {"in_temp_c": 21.5, "moist1_pct": 40}},
                {"ts": 30, "clk": "none", "boot": 3, "d": {"in_temp_c": 21.0}},
                {"ts": 500, "clk": "none", "boot": 2, "d": {"in_temp_c": 20.0}}]
        body = {"id": "abc", "name": "x", "boot": 9, "now": now, "clk": "ok", "rows": rows}
        st, r = http("POST", self.svc.url + "/ingest/batch", body)
        self.assertEqual((st, r["undated"]), (200, 3))
        st, j = http("GET", self.svc.url + "/api/undated?uid=abc")
        self.assertEqual(st, 200)
        self.assertEqual([(x["boot"], x["up"]) for x in j["rows"]], [(2, 500), (3, 30), (3, 900)])
        self.assertEqual(j["rows"][2]["d"]["in_temp_c"], 21.5)
        # the rollups skip them: nothing lands on the timeline at the arrival time
        from burrow import rollups
        self.assertEqual(rollups.bucketize([x for x in self.svc.store.read_open() if x["src"] == "backfill"]), [])
        # and the CSV
        import urllib.request
        req = urllib.request.Request(self.svc.url + "/api/undated?uid=abc&csv=1")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.headers.get("Content-Type", "").split(";")[0], "text/csv")
            text = resp.read().decode()
        lines = text.strip().split("\n")
        self.assertEqual(lines[0], "boot,seconds_since_boot,received_ts,in_temp_c,moist1_pct")
        self.assertTrue(lines[1].startswith("2,500,"))
        self.assertTrue(lines[3].endswith(",21.5,40"))

    def test_backfill_seals_into_the_windows_it_belongs_to(self):
        now = util.now()
        w = self.svc.store.window
        t0 = now - 10 * w
        body = {"id": "abc", "name": "x", "boot": 7, "now": now, "clk": "ok", "rows": self.rows(t0, 4, step=w)}
        st, r = http("POST", self.svc.url + "/ingest/batch", body)
        self.assertEqual((st, r["n"]), (200, 4))
        metas = self.svc.store.seal(now=now + w)
        self.assertEqual(len(metas), 4)
        self.assertEqual(sorted(m["window"] for m in metas), [self.svc.store.window_of(t0 + i * w) for i in range(4)])
        self.assertEqual(sum(m["rows"] for m in metas), 4)
        # and the rollups know about the hours they fell in
        pts = self.svc.rollups.query("abc", t0 - w, now, "5m")
        self.assertEqual(len(pts), 4)

    def test_bad_batches(self):
        st, r = http("POST", self.svc.url + "/ingest/batch", {"rows": []})
        self.assertEqual(st, 400)
        st, r = http("POST", self.svc.url + "/ingest/batch", {"id": "abc", "rows": "nope"})
        self.assertEqual(st, 400)
        st, r = http("POST", self.svc.url + "/ingest/batch", {"id": "abc", "rows": []})
        self.assertEqual((st, r["n"]), (200, 0))


if __name__ == "__main__":
    unittest.main()
