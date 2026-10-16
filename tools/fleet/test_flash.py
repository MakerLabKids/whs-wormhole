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
        self.assertEqual(row["version"], "0.2.0")
        saved = flash.read_roster()
        self.assertEqual(saved[0]["uid"], rn.uid)
        # the three identity files were pushed, after the wipe and the project files
        pushed = [c for c in rn.calls if len(c) > 3 and c[2] == "fs" and c[3] == "cp"]
        remotes = [c[5] for c in pushed]
        self.assertEqual(remotes[-3:], [":wifi.json", ":bin.json", ":name.txt"])
        self.assertIn(":lib/picolab.py", remotes)
        self.assertTrue(any("wipe.py" in " ".join(c) for c in rn.calls))

    def test_bootsel_from_sysfs(self):
        sysfs = os.path.join(self.tmp, "usb")
        for name, vid, pid in (("3-10", "2e8a", "000f"), ("3-11", "30c9", "00f8"), ("1-2", "2e8a", "0003"),
                               ("3-12", "2e8a", "0005")):
            os.makedirs(os.path.join(sysfs, name))
            with open(os.path.join(sysfs, name, "idVendor"), "w") as f:
                f.write(vid + "\n")
            with open(os.path.join(sysfs, name, "idProduct"), "w") as f:
                f.write(pid + "\n")
        os.makedirs(os.path.join(sysfs, "usb1"))          # a hub dir with no ids
        self.assertEqual(flash.bootsel_usb_devices(sysfs), ["1-2", "3-10"])
        self.assertEqual(flash.bootsel_usb_devices(os.path.join(self.tmp, "nope")), [])

    def test_picotool_load(self):
        calls = []

        class P:
            returncode = 0
            stdout = stderr = ""

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return P()
        self.assertTrue(flash.picotool_load("/x/fw.uf2", picotool="/opt/picotool", run=fake_run))
        self.assertEqual(calls, [["/opt/picotool", "load", "-x", "/x/fw.uf2"]])
        # not installed -> False, nothing run
        path = os.environ.get("PATH")
        os.environ["PATH"] = self.tmp
        try:
            self.assertFalse(flash.picotool_load("/x/fw.uf2", run=fake_run))
        finally:
            os.environ["PATH"] = path
        self.assertEqual(len(calls), 1)
        P.returncode = 1
        P.stderr = "No accessible RP-series devices in BOOTSEL mode were found."
        with self.assertRaises(RuntimeError):
            flash.picotool_load("/x/fw.uf2", picotool="/opt/picotool", run=fake_run)

    def test_ports_include_serial_globs(self):
        dev = os.path.join(self.tmp, "ttyACM0")
        open(dev, "w").close()
        orig = flash.SERIAL_GLOBS
        flash.SERIAL_GLOBS = [os.path.join(self.tmp, "ttyACM*")]
        try:
            rn = flash.Runner("mpremote")
            rn.run = lambda *a, **k: "/dev/ttyACM1 2e8a:0005 MicroPython Board in FS mode\n"
            self.assertEqual(rn.ports(), ["/dev/ttyACM1", dev])
            os.chmod(dev, 0o444)                           # unreadable for writing -> skipped
            self.assertEqual(rn.ports(), ["/dev/ttyACM1"])
        finally:
            flash.SERIAL_GLOBS = orig


if __name__ == "__main__":
    unittest.main()
