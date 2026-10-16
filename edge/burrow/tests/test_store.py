import calendar
import gzip
import json
import os
import shutil
import tempfile
import time
import unittest

from burrow import config, rollups, store, util


W = calendar.timegm((2026, 10, 16, 14, 15, 0, 0, 0, 0))   # a 15-min window start
H = calendar.timegm((2026, 10, 16, 14, 0, 0, 0, 0, 0))    # an hour start


def mkcfg(tmp, **over):
    cfg = config.load("/nonexistent")
    cfg.update(data_dir=tmp, edge="burrowT", room=1, seal_grace_s=0)
    cfg.update(over)
    return cfg


def row(ts, uid="abc", **d):
    dd = {"id": uid, "name": "Dirt Vader", "in_temp_c": 21.5, "moist1_pct": 40, "relay": 0,
          "probe_temps_c": [20.1, None, 19.8], "ok": True, "parts": [{"name": "x", "ok": True}]}
    dd.update(d)
    return {"ts": ts, "clk": "free", "uid": uid, "name": "Dirt Vader", "room": 1, "edge": "burrowT",
            "src": "push", "d": dd}


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = mkcfg(self.tmp)
        self.s = store.Store(self.cfg)

    def tearDown(self):
        self.s.close()
        shutil.rmtree(self.tmp)

    def test_casting_id_roundtrip(self):
        cid = store.casting_id(2, W)
        self.assertEqual(cid, "r2-20261016T1415")
        self.assertEqual(store.parse_id(cid), (2, W))
        self.assertEqual(store.parse_id("r2-20261016T1415-2"), (2, W))
        self.assertIsNone(store.parse_id("junk"))

    def test_append_seal_and_open_rewrite(self):
        w = W                      # a window start
        for i in range(10):
            self.s.append(row(w + i * 60))
        self.s.append(row(w + 900 + 5))     # next window: must stay open
        self.s.fsync()
        made = self.s.seal(now=w + 900 + 30)
        self.assertEqual(len(made), 1)
        m = made[0]
        self.assertEqual(m["id"], "r1-20261016T1415")
        self.assertEqual(m["rows"], 10)
        self.assertEqual(m["t0"], w)
        self.assertEqual(m["t1"], w + 540)
        self.assertTrue(os.path.exists(self.s.gz_path(m["id"])))
        self.assertEqual(util.sha256_file(self.s.gz_path(m["id"])), m["sha256"])
        # the open log now holds only the newer row
        left = self.s.read_open()
        self.assertEqual(len(left), 1)
        self.assertEqual(left[0]["ts"], w + 905)
        # rows decode and are sorted
        rows = self.s.rows_of(m["id"])
        self.assertEqual([r["ts"] for r in rows], [w + i * 60 for i in range(10)])
        # appending after a seal still works (handle was reopened)
        self.s.append(row(w + 910))
        self.assertEqual(len(self.s.read_open()), 2)

    def test_torn_tail_is_dropped(self):
        w = W
        self.s.append(row(w + 1))
        self.s.fsync()
        with open(self.s._open_path, "ab") as f:
            f.write(b'{"ts": 1760624102, "uid": "abc", "d": {"id": "a')     # power cut mid-line
        rows = self.s.read_open()
        self.assertEqual(len(rows), 1)
        made = self.s.seal(now=w + 1000)
        self.assertEqual(made[0]["rows"], 1)

    def test_no_seal_before_grace(self):
        cfg = mkcfg(self.tmp, seal_grace_s=20)
        s = store.Store(cfg)
        w = W
        s.append(row(w + 10))
        self.assertEqual(s.seal(now=w + 900 + 5), [])        # inside grace
        self.assertEqual(len(s.seal(now=w + 900 + 25)), 1)   # after grace

    def test_duplicate_window_gets_suffix(self):
        w = W
        self.s.append(row(w + 1))
        self.s.seal(now=w + 1000)
        self.s.append(row(w + 2))           # clock went backwards; same window again
        made = self.s.seal(now=w + 1000)
        self.assertEqual(made[0]["id"], "r1-20261016T1415-2")
        self.assertEqual(len(self.s.metas), 2)

    def test_index_reload(self):
        w = W
        self.s.append(row(w + 1))
        self.s.seal(now=w + 1000)
        s2 = store.Store(self.cfg)
        self.assertIn("r1-20261016T1415", s2.metas)
        s2.close()

    def test_mirror_requires_matching_hash(self):
        w = W
        self.s.append(row(w + 1))
        m = self.s.seal(now=w + 1000)[0]
        gz = self.s.gz_bytes(m["id"])
        other = store.Store(mkcfg(tempfile.mkdtemp(), edge="burrowX", room=2))
        self.assertIsNone(other.store_mirror(m, gz + b"x", "burrowT"))
        stored = other.store_mirror(m, gz, "burrowT")
        self.assertEqual(stored["mirrored_from"], "burrowT")
        self.assertIn("burrowX", stored["replicas"])
        self.assertEqual(other.rows_of(m["id"])[0]["ts"], w + 1)
        # mirrored again: idempotent
        self.assertEqual(other.store_mirror(m, gz, "burrowT")["id"], m["id"])
        other.close()
        shutil.rmtree(other.data_dir)

    def test_retention_rules(self):
        w = W
        self.s.append(row(w + 1))
        m = self.s.seal(now=w + 1000)[0]
        old = w + 10 * 86400
        # young or unverified: never reclaimed
        self.assertEqual(self.s.reclaimable(now=w + 1000), [])
        self.assertEqual(self.s.reclaimable(now=old), [])            # old but unverified
        self.s.mark_cloud(m["id"], uploaded_at=w + 2000)
        self.assertEqual(self.s.reclaimable(now=old), [])            # uploaded is not verified
        self.s.mark_cloud(m["id"], verified_at=w + 3000, by="cloud")
        self.assertEqual(self.s.reclaimable(now=w + 6 * 86400), [])  # verified but < 7 days
        self.assertEqual(self.s.reclaimable(now=old), [m["id"]])
        self.assertEqual(self.s.reclaim(now=old), 1)
        self.assertFalse(os.path.exists(self.s.gz_path(m["id"])))
        self.assertFalse(os.path.exists(self.s.meta_path(m["id"])))
        with open(os.path.join(self.tmp, "reclaimed.log")) as f:
            self.assertEqual(json.loads(f.readline())["id"], m["id"])

    def test_stats(self):
        st = self.s.stats()
        self.assertEqual(st["castings"], 0)
        self.assertGreater(st["disk_total"], 0)


class RollupTest(unittest.TestCase):
    def test_metrics_flatten(self):
        m = util.metrics({"a": 1, "b": 2.5, "ok": True, "flag": False, "s": "x",
                          "l": [1, None, 3], "parts": [{"ok": True}]})
        self.assertEqual(m, {"a": 1, "b": 2.5, "l_0": 1, "l_2": 3})

    def test_bucketize_and_hourly(self):
        w = H       # 14:00 UTC
        rows = [row(w + i * 60, in_temp_c=20 + i) for i in range(60)]
        fm = rollups.bucketize(rows, "5m")
        self.assertEqual(len(fm), 12)
        first = fm[0]
        self.assertEqual(first["ts"], w)
        self.assertEqual(first["data"]["in_temp_c"], [20, 22.0, 24, 5])
        self.assertEqual(first["data"]["probe_temps_c_0"], [20.1, 20.1, 20.1, 5])
        hr = rollups.merge_hourly(fm)
        self.assertEqual(len(hr), 1)
        self.assertEqual(hr[0]["data"]["in_temp_c"], [20, 49.5, 79, 60])

    def test_sqlite_roundtrip(self):
        tmp = tempfile.mkdtemp()
        r = rollups.Rollups(os.path.join(tmp, "r.sqlite"))
        w = H
        rows = [row(w + i * 60, in_temp_c=20 + i) for i in range(60)]
        n5, n1 = r.ingest_casting(rows[:15])
        self.assertEqual((n5, n1), (3, 1))
        r.ingest_casting(rows[15:])
        pts = r.query("abc", w, w + 3600, "5m")
        self.assertEqual(len(pts), 12)
        hr = r.query("abc", w, w + 3600, "1h")
        self.assertEqual(hr[0][1]["in_temp_c"][3], 60)      # all 60 samples counted once
        self.assertEqual(r.uids(), ["abc"])
        shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
