"""The two-step rename: micropython tools/picotest/test_rename.py"""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
from picolab import RenameGate, RENAME_CONFIRM_S, pin_for

g = RenameGate()
assert g.confirm("Worm Town", "1234", 0).get("cancelled"), "nothing proposed: nothing to confirm"
newpin = pin_for("Worm Town", "192.168.4.38")
r = g.propose("Worm Town", newpin, 100)
assert r["pending"] and r["new_pin"] == newpin and not r.get("renamed"), r
r = g.confirm("Worm Town", "0000", 110)
assert r["error"] == "confirm" and r["tries_left"] == 2, r
r = g.confirm("Worm Town", " " + newpin + " ", 120)
assert r["ok"] and r["renamed"] and r["name"] == "Worm Town", r
assert g.confirm("Worm Town", newpin, 121).get("cancelled"), "a confirmed rename is used up"

g.propose("Worm Town", newpin, 0)
for i in range(2): g.confirm("Worm Town", "1", 1)
r = g.confirm("Worm Town", "1", 2)
assert r.get("cancelled"), "three wrong PINs cancel it"
assert g.confirm("Worm Town", newpin, 3).get("cancelled"), "and the right one is too late now"

g.propose("Worm Town", newpin, 0)
assert g.confirm("Other Name", newpin, 5).get("cancelled"), "a different name is not the proposed one"
g.propose("Worm Town", newpin, 0)
assert g.confirm("Worm Town", newpin, RENAME_CONFIRM_S + 1).get("cancelled"), "too late"
print("rename OK")
