"""The three dashboard message slots (picolab.Messages), off-board:
    micropython tools/picotest/test_messages.py"""
import sys, os
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import picolab

PATH = "tools/picotest/msg-test.json"
try:
    os.remove(PATH)
except OSError:
    pass


class FakeApp:
    def __init__(self): self.ts, self.clk, self.hints = 0, "none", []
    def wall(self): return self.ts, self.clk
    def clock_hint(self, ts): self.hints.append(ts); self.ts, self.clk = ts, "est"


def req(q): return ("GET /msg?" + q + " HTTP/1.1\r\nHost: x\r\n\r\n").encode()

app = FakeApp()
m = picolab.Messages(app, PATH)
assert m.next() is None and m.status()["slots"] == [None, None, None]
# set a slot: title + lines, urlencoded, trailing blank lines dropped, 16 chars max
r = m.handle(req("slot=1&title=Go%20Worms!&l1=line+one&l2=&l3=third%20line%20is%20quite%20long&l4=&l5="))
assert r["slots"][0] == {"title": "Go Worms!", "lines": ["line one", "", "third line is qu"], "shown": 0}, r["slots"][0]
assert r["active"] == [True, False, False], r["active"]
assert m.handle(req("slot=2&title=&l1=")) == {"error": "an empty message"}
assert m.handle(req("slot=4&title=x"))["error"].startswith("slot 1-3")
assert m.handle(req("slot=3&title=Three&count=2"))["slots"][2]["count"] == 2
# rotation: the live slots in turn, each showing counted; a counted slot stops
assert m.next() == ("Go Worms!", ["line one", "", "third line is qu"])
assert m.next() == ("Three", [])
assert m.next() == ("Go Worms!", ["line one", "", "third line is qu"])
assert m.next() == ("Three", [])
assert m.next() == ("Go Worms!", ["line one", "", "third line is qu"]) and m.next()[0] == "Go Worms!", "slot 3 is spent after 2"
st = m.status()
assert st["slots"][2]["shown"] == 2 and st["active"] == [True, False, False], st
# the count survives a reload (the file is written whenever a counted slot shows)
m2 = picolab.Messages(app, PATH)
assert m2.slots[2]["shown"] == 2, m2.slots[2]
# dated: needs a clock; the phone's `now` gives the board one
r = m.handle(req("slot=2&title=Dated&start=1800000000&end=1800003600"))
assert r["active"][1] is False and r["clk"] == "none", r      # no clock: a dated message waits
r = m.handle(req("slot=2&title=Dated&start=1800000000&end=1800003600&now=1799999000"))
assert app.hints == [1799999000] and r["clk"] == "est" and r["active"][1] is False, r   # before the start
app.ts = 1800001000
assert m.status()["active"][1] is True
assert [m.next()[0] for _ in range(3)] == ["Dated", "Go Worms!", "Dated"]   # in turn, from where the rotation was
app.ts = 1800009000
assert m.status()["active"][1] is False, "past the end"
# clear
assert m.handle(req("slot=2&clear=1"))["slots"][1] is None
assert picolab.Messages(app, PATH).slots[1] is None
# only printable ASCII reaches the screen
r = m.handle(req("slot=2&title=caf%C3%A9%09x"))
assert r["slots"][1]["title"] == "cafx", r["slots"][1]
os.remove(PATH)
print("messages OK")
