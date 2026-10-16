"""Logic tests for flash.py (no hardware): roster building, picking, re-flash."""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flash


class FlashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig = flash.ROSTER
        flash.ROSTER = os.path.join(self.tmp, "roster.csv")
        self.fleet = flash.load_fleet()

    def tearDown(self):
        flash.ROSTER = self.orig
        shutil.rmtree(self.tmp)

    def test_init_roster_counts_and_names(self):
        rows = flash.init_roster(self.fleet)
        self.assertEqual(len(rows), 50)
        self.assertEqual(rows[0]["team"], "Compost Cowboys")
        self.assertEqual(len(set(r["team"] for r in rows)), 50)      # no repeats
        by_room = {}
        for r in rows:
            by_room.setdefault(r["room"], []).append(r)
        self.assertEqual([len(by_room[k]) for k in sorted(by_room)], [17, 17, 16])
        # periods split within a room; bins numbered per period from 1
        p1 = [r for r in rows if r["room"] == 1 and r["period"] == 1]
        self.assertEqual([r["bin"] for r in p1], list(range(1, 10)))
        self.assertEqual(flash.read_roster()[0]["team"], "Compost Cowboys")

    def test_pick_new_then_reflash(self):
        rows = flash.init_roster(self.fleet)
        row, new = flash.pick_row(rows, "aaaa")
        self.assertTrue(new)
        self.assertEqual(row["team"], "Compost Cowboys")
        row["uid"] = "aaaa"
        row2, new2 = flash.pick_row(rows, "bbbb")
        self.assertTrue(new2)
        self.assertEqual(row2["team"], "Worm Rangers")
        again, new3 = flash.pick_row(rows, "aaaa")
        self.assertFalse(new3)
        self.assertEqual(again["team"], "Compost Cowboys")

    def test_project_files_resolve(self):
        pairs = flash.project_files(self.fleet)
        remotes = [r for _, r in pairs]
        self.assertIn("main.py", remotes)
        self.assertIn("lib/picolab.py", remotes)
        for local, _ in pairs:
            self.assertTrue(os.path.exists(local), local)

    def test_dry_run_flash_writes_roster(self):
        rows = flash.init_roster(self.fleet)
        rn = flash.FakeRunner()
        row = flash.flash_one(rn, "/dev/ttyFAKE0", self.fleet, rows, "pw", dry=True)
        self.assertEqual(row["uid"], rn.uid)
        self.assertEqual(row["version"], "0.1.2")
        saved = flash.read_roster()
        self.assertEqual(saved[0]["uid"], rn.uid)
        # the three identity files were pushed, after the wipe and the project files
        pushed = [c for c in rn.calls if len(c) > 3 and c[2] == "fs" and c[3] == "cp"]
        remotes = [c[5] for c in pushed]
        self.assertEqual(remotes[-3:], [":wifi.json", ":bin.json", ":name.txt"])
        self.assertIn(":lib/picolab.py", remotes)
        self.assertTrue(any("wipe.py" in " ".join(c) for c in rn.calls))


if __name__ == "__main__":
    unittest.main()
