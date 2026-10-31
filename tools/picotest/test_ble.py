"""The Bluetooth door (lib/blelink.py) against the fake bluetooth stub:
    micropython tools/picotest/test_ble.py"""
import sys, os, json
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import faketime
sys.modules["time"] = faketime
import bluetooth, picolab, blelink

PATH = "tools/picotest/msg-ble-test.json"
try:
    os.remove(PATH)
except OSError:
    pass


class FakeApp:
    """What blelink needs of a WebApp: name, identity(), routes, dispatch() via a real WebApp's logic."""
    def __init__(self):
        self.name, self.ip = "Dirt Vader", "192.168.4.7"
        self.routes = None
        self._pin_fails, self._pin_locked_until = 0, 0
    def identity(self): return {"id": "abc", "name": self.name, "ip": self.ip}
    def pin(self): return picolab.pin_for(self.name, self.ip)
    _pin_ok = picolab.WebApp._pin_ok
    dispatch = picolab.WebApp.dispatch
    def _rename(self, req): return {"ok": True, "name": picolab.query_str(req, "name")}
    def wall(self): return (0, "none")


app = FakeApp()
msgs = picolab.Messages(app, PATH)
app.routes = [("/msg", msgs.handle)]
link = blelink.BleLink(app, lambda: {"in_temp_c": 21.5})
ble = bluetooth.BLE._last
assert ble.active() and ble.adv and ble.adv[2] == b"\x0b\x09Dirt Vader", ble.adv    # advertising, name in the scan response
assert ble.adv[1][:3] == b"\x02\x01\x06" and ble.adv[1][3:5] == b"\x11\x07" and len(ble.adv[1]) == 21, ble.adv[1]
rx, tx = link._rx, link._tx


def ask(line, chunks=None):
    ble.notified = []
    ble.central_writes(rx, line.encode() + b"\n")
    for _ in range(chunks or 40):
        link.poll()
    out = ble.received().decode()
    assert out.endswith("\n"), out
    return json.loads(out)


ble.connect()
assert link.connected
# readings, with the identity merged in, like /data on the page
r = ask("/data")
assert r["in_temp_c"] == 21.5 and r["name"] == "Dirt Vader" and r["id"] == "abc", r
# the reply came in notification-sized pieces (MTU 23 -> 20 bytes), nothing lost
assert all(len(c) <= 20 for c in ble.notified) and len(ble.notified) > 1, [len(c) for c in ble.notified]
# a message without the PIN is refused the way the page refuses it
r = ask("/msg?slot=1&title=Hi&l1=there")
assert r == {"error": "pin", "locked": False}, r
# with the PIN (pin_for("Dirt Vader", .7) = 1612) it lands, url-decoded
r = ask("/msg?slot=1&title=Hi%20there&l1=line+one&pin=" + app.pin())
assert r["slots"][0]["title"] == "Hi there" and r["slots"][0]["lines"] == ["line one"], r
assert msgs.slots[0]["title"] == "Hi there"
# reading the slots needs the PIN too
assert ask("/msg")["error"] == "pin"
# unknown lines are answered, not ignored
r = ask("/wat")
assert r["error"] == "unknown request" and "/msg" in r["try"], r
# a line can arrive in pieces (a phone writes 20 bytes at a time)
ble.notified = []
line = ("/msg?slot=2&title=Pieces&pin=" + app.pin() + "\n").encode()
for i in range(0, len(line), 7):
    ble.central_writes(rx, line[i:i + 7]); link.poll()
for _ in range(40): link.poll()
assert json.loads(ble.received().decode())["slots"][1]["title"] == "Pieces"
# a full notify queue just waits for the next pass
ble.notify_fail = 3
r = ask("/data", chunks=60)
assert r["name"] == "Dirt Vader"
# the lockout is shared with the page: five wrong PINs lock both doors
for _ in range(5): ask("/msg?slot=1&title=x&pin=0000")
assert ask("/msg?slot=1&title=x&pin=" + app.pin()) == {"error": "pin", "locked": True}
# disconnect: queue dropped, advertising again
ble.adv = None; ble.disconnect()
assert not link.connected and ble.adv is not None
os.remove(PATH)
print("bluetooth OK")
