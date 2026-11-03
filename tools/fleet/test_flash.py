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
        # periods split within a room; bins numbered once across the fleet from bin_first
        p1 = [r for r in rows if r["room"] == 1 and r["period"] == 1]
        self.assertEqual([r["bin"] for r in p1], list(range(30, 39)))
        self.assertEqual([r["bin"] for r in rows], list(range(30, 80)))
        self.assertTrue(all(flash.valid_octet(r["bin"]) for r in rows))
        self.assertEqual(flash.read_roster()[0]["team"], "Compost Cowboys")

    def test_bin_numbers_skip_the_reserved_addresses(self):
        self.assertEqual(flash.bin_numbers(12, 8), [8, 9, 11, 12, 13, 14, 15, 24, 25, 26, 27, 28])
        for bad in (0, 1, 10, 16, 23, 100, "x", None):
            self.assertFalse(flash.valid_octet(bad), bad)
        for good in (2, 9, 11, 15, 24, 99):
            self.assertTrue(flash.valid_octet(good), good)

    def test_renumber_keeps_rows_and_reports_changes(self):
        rows = flash.init_roster(self.fleet)
        rows[0]["uid"] = "aaaa"
        for r in rows:
            r["bin"] = 1                                   # the old per-period numbering
        changed = flash.renumber(rows, 30)
        self.assertEqual([r["bin"] for r in rows], list(range(30, 80)))
        self.assertEqual(len(changed), 50)
        self.assertEqual(changed[0], ("Compost Cowboys", 1, 30))
        self.assertEqual(rows[0]["uid"], "aaaa")
        self.assertEqual(flash.renumber(rows, 30), [])     # already right: nothing changes

    def test_flash_refuses_an_unusable_bin_number(self):
        rows = flash.init_roster(self.fleet)
        rows[0]["bin"] = 16
        with self.assertRaises(RuntimeError):
            flash.flash_one(flash.FakeRunner(), "/dev/ttyFAKE0", self.fleet, rows, "pw", dry=True)

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

    def test_dry_run_flash_leaves_roster_untouched(self):
        rows = flash.init_roster(self.fleet)
        rn = flash.FakeRunner()
        row = flash.flash_one(rn, "/dev/ttyFAKE0", self.fleet, rows, "pw", dry=True)
        self.assertEqual(row["uid"], rn.uid)
        self.assertEqual(row["version"], "0.2.0")
        saved = flash.read_roster()
        self.assertEqual(saved[0]["uid"], "")      # --dry-run never writes roster.csv
        # the identity files (and the code version) were pushed, after the wipe and the project files
        pushed = [c for c in rn.calls if len(c) > 3 and c[2] == "fs" and c[3] == "cp"]
        remotes = [c[5] for c in pushed]
        self.assertEqual(remotes[-4:], [":wifi.json", ":bin.json", ":name.txt", ":ota.json"])
        self.assertIn(":lib/picolab.py", remotes)
        self.assertTrue(any("wipe.py" in " ".join(c) for c in rn.calls))

    def test_firmware_version_from_the_file_name(self):
        self.assertEqual(flash.firmware_version({"firmware": "firmware/RPI_PICO2_W-20260824-v1.29.0.uf2"}), "1.29.0")
        self.assertIsNone(flash.firmware_version({"firmware": "x.uf2"}))

    def _mp(self, have):
        class R(flash.FakeRunner):
            def run(s, *args, timeout=60, check=True):
                if "sys.implementation" in " ".join(args):
                    s.calls.append(args)
                    return have + "\n"
                return super().run(*args, timeout=timeout, check=check)
        return R()

    def test_upgrade_firmware_only_when_the_version_differs(self):
        fleet = {"firmware": "firmware/RPI_PICO2_W-20260824-v1.29.0.uf2"}
        loads = []
        rn = self._mp("1.29.0")
        self.assertEqual(flash.upgrade_firmware(rn, "/dev/ttyFAKE0", fleet, load=loads.append), "/dev/ttyFAKE0")
        self.assertEqual(loads, [])
        self.assertFalse(any("bootloader" in " ".join(c) for c in rn.calls))
        # an older MicroPython: bootloader, picotool, back on its port
        rn = self._mp("1.28.0")
        states = iter([False, True])
        port = flash.upgrade_firmware(rn, "/dev/ttyFAKE0", fleet, wait=lambda s: None,
                                      bootsel=lambda: next(states), load=lambda f: loads.append(f) or True)
        self.assertEqual(port, "/dev/ttyFAKE0")
        self.assertTrue(any("machine.bootloader()" in " ".join(c) for c in rn.calls))
        self.assertTrue(loads and loads[0].endswith("v1.29.0.uf2"), loads)
        # dry run: says so, touches nothing
        rn, loads = self._mp("1.28.0"), []
        flash.upgrade_firmware(rn, "/dev/ttyFAKE0", fleet, dry=True, load=loads.append)
        self.assertEqual(loads, [])
        # a board that never reaches its bootloader: a clear error, not a hang
        t = iter(range(0, 1000, 5))
        with self.assertRaises(RuntimeError):
            flash.upgrade_firmware(self._mp("1.28.0"), "/dev/ttyFAKE0", fleet, wait=lambda s: None,
                                   bootsel=lambda: False, load=loads.append, clock=lambda: next(t))

    def test_a_kept_board_is_never_touched(self):
        rows = flash.init_roster(self.fleet)
        rn = flash.FakeRunner()
        fleet = dict(self.fleet, keep={rn.uid: "the bench board"})
        with self.assertRaises(RuntimeError) as e:
            flash.flash_one(rn, "/dev/ttyFAKE0", fleet, rows, "pw", dry=True)
        self.assertIn("keep list", str(e.exception))
        self.assertFalse(any("wipe.py" in " ".join(c) for c in rn.calls), "never wiped")
        self.assertIn("99e3b028541489d4", self.fleet["keep"], "the bench board is protected")

    def test_flash_writes_the_code_version(self):
        rows = flash.init_roster(self.fleet)
        rn = flash.FakeRunner()
        flash.flash_one(rn, "/dev/ttyFAKE0", self.fleet, rows, "pw", dry=True)
        self.assertTrue(any(":ota.json" in c for call in rn.calls for c in call), "ota.json written")
        self.assertRegex(flash.code_version(), r"^([0-9a-f]{7}\+?|unknown)$")

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
