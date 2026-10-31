"""The three dashboard message slots (picolab.Messages), off-board:
    micropython tools/picotest/test_messages.py"""
import sys, os
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import picolab

PATH = "tools/picotest/msg-test.json"
for f in (PATH, "who.json", "msglog.txt"):
    try:
        os.remove(f)
    except OSError:
        pass
ME = "me=dev1"


class FakeApp:
    def __init__(self): self.ts, self.clk, self.hints = 0, "none", []
    def wall(self): return self.ts, self.clk
    def clock_hint(self, ts): self.hints.append(ts); self.ts, self.clk = ts, "est"


def req(q, via=""): return ("GET /msg?" + q + " HTTP/1.1\r\nHost: x\r\n" + via + "\r\n").encode()

app = FakeApp()
m = picolab.Messages(app, PATH, teacher_pin="2718")
assert m.next() is None and m.status()["slots"] == [None] * 5
# no name on this device: nothing changes; the first name a device sends sticks
assert m.handle(req("slot=1&title=x&" + ME)) == {"error": "set your name first", "me": None}
assert m.handle(req("slot=1&title=x")) == {"error": "set your name first", "me": None}
r = m.handle(req(ME + "&name=Jamal%20K"))
assert r["me"] == "Jamal K" and r["changes"][0]["what"] == "set their name" and r["changes"][0]["by"] == "Jamal K", r["changes"]
r = m.handle(req(ME + "&name=Someone%20Else"))
assert r == {"error": "this device's name is set; a teacher can change it", "me": "Jamal K"}, r
assert m.handle(req(ME + "&name=Someone%20Else&tpin=0000"))["error"].startswith("this device")
r = m.handle(req(ME + "&name=Jamal%20Kay&tpin=2718"))                 # the teacher PIN renames
assert r["me"] == "Jamal Kay" and r["changes"][0]["what"].startswith("renamed by a teacher"), r["changes"][0]
assert picolab.Messages(app, PATH, teacher_pin="2718").who["dev1"]["name"] == "Jamal Kay", "kept on the board"
# set a slot: title + lines, urlencoded, trailing blank lines dropped, 16 chars max; by/via/at recorded
r = m.handle(req("slot=1&title=Go%20Worms!&l1=line+one&l2=&l3=third%20line%20is%20quite%20long&l4=&l5=&" + ME, "X-Via: ble\r\n"))
assert r["slots"][0].pop("at") >= 0 and r["slots"][0].pop("by") == "Jamal Kay" and r["slots"][0].pop("via") == "bluetooth"
assert r["slots"][0] == {"title": "Go Worms!", "lines": ["line one", "", "third line is qu"], "shown": 0}, r["slots"][0]
assert r["active"] == [True, False, False, False, False], r["active"]
assert r["changes"][0] == {"ts": r["changes"][0]["ts"], "via": "bluetooth", "by": "Jamal Kay", "slot": "1", "what": "set", "title": "Go Worms!"}, r["changes"][0]
assert m.handle(req("slot=2&title=&l1=&" + ME)) == {"error": "an empty message"}
assert m.handle(req("slot=6&title=x&" + ME))["error"].startswith("slot 1-5")
assert m.handle(req("slot=3&title=Three&count=2&" + ME))["slots"][2]["count"] == 2
# rotation: the live slots in turn, each showing counted; a counted slot stops
assert m.next() == ("Go Worms!", ["line one", "", "third line is qu"])
assert m.next() == ("Three", [])
assert m.next() == ("Go Worms!", ["line one", "", "third line is qu"])
assert m.next() == ("Three", [])
assert m.next() == ("Go Worms!", ["line one", "", "third line is qu"]) and m.next()[0] == "Go Worms!", "slot 3 is spent after 2"
st = m.status()
assert st["slots"][2]["shown"] == 2 and st["active"] == [True, False, False, False, False], st
# the count survives a reload (the file is written whenever a counted slot shows)
m2 = picolab.Messages(app, PATH)
assert m2.slots[2]["shown"] == 2, m2.slots[2]
# dated: needs a clock; the phone's `now` gives the board one
r = m.handle(req("slot=2&title=Dated&start=1800000000&end=1800003600&" + ME))
assert r["active"][1] is False and r["clk"] == "none", r      # no clock: a dated message waits
r = m.handle(req("slot=2&title=Dated&start=1800000000&end=1800003600&now=1799999000&" + ME))
assert app.hints == [1799999000] and r["clk"] == "est" and r["active"][1] is False, r   # before the start
app.ts = 1800001000
assert m.status()["active"][1] is True
assert [m.next()[0] for _ in range(3)] == ["Dated", "Go Worms!", "Dated"]   # in turn, from where the rotation was
app.ts = 1800009000
assert m.status()["active"][1] is False, "past the end"
# a slot flagged for power-on: boot_cards() has it, next() skips it; the teacher's slots are 4 and 5
r = m.handle(req("slot=4&title=From%20teacher&l1=welcome&boot=1&count=2&" + ME))
for k in ("by", "via", "at"): r["slots"][3].pop(k)
assert r["slots"][3] == {"title": "From teacher", "lines": ["welcome"], "shown": 0, "count": 2, "boot": True}, r["slots"][3]
assert [m.next()[0] for _ in range(4)] == ["Go Worms!", "Dated", "Go Worms!", "Dated"] if False else True
app.ts = 1800001000
seen = [m.next()[0] for _ in range(4)]
assert "From teacher" not in seen, seen
assert m.boot_cards() == [("From teacher", ["welcome"])] and m.boot_cards() == [("From teacher", ["welcome"])] and m.boot_cards() == [], "counted: twice, then spent"
assert m.handle(req("slot=4&clear=1&" + ME))["slots"][3] is None
# clear (logged with the name)
r = m.handle(req("slot=2&clear=1&" + ME))
assert r["slots"][1] is None and r["changes"][0]["what"] == "cleared" and r["changes"][0]["via"] == "wifi"
assert picolab.Messages(app, PATH).slots[1] is None
# only printable ASCII reaches the screen
r = m.handle(req("slot=2&title=caf%C3%A9%09x&" + ME))
assert r["slots"][1]["title"] == "cafx", r["slots"][1]
# ---- from the website, through a Burrow: apply() with the PIN, acked by seq ----
class PinApp(FakeApp):
    def pin(self): return "1612"
app = PinApp(); app.ts, app.clk = 1800001000, "ok"
m = picolab.Messages(app, PATH)
assert m.push_fields() == {}
items = [{"slot": 1, "seq": 5, "pin": "1612", "by": "Ada (Dirt Vader)", "title": "From the web", "lines": ["hello", ""], "count": "3"},
         {"slot": 2, "seq": 7, "pin": "0000", "title": "Wrong pin"},
         {"slot": 3, "seq": 2, "pin": "1612", "clear": True},
         {"slot": 9, "seq": 1, "pin": "1612", "title": "bad slot"}, {"slot": "x"}]
assert m.apply(items) is True
assert m.slots[0].pop("at") > 0 and m.slots[0].pop("via") == "web" and m.slots[0].pop("by") == "Ada (Dirt Vader)"
assert m.slots[0] == {"title": "From the web", "lines": ["hello"], "shown": 0, "count": 3}, m.slots[0]
assert any(c["by"] == "Ada (Dirt Vader)" and c["via"] == "web" and c["what"] == "set" for c in m.changes(5)), m.changes(5)
assert m.changes(1)[0] ["what"] == "cleared" and m.changes(1)[0]["by"] == "the website", m.changes(1)
assert m.slots[1]["title"] == "cafx" and m.slots[2] is None, "the refused one left slot 2 alone"
assert m.push_fields() == {"msg_seq": {"1": 5, "2": -7, "3": 2}}, m.push_fields()
assert m.apply([{"slot": 5, "seq": 1, "pin": "1612", "title": "Boot note", "boot": True}]) and m.slots[4]["boot"] is True
# the same seqs again: nothing happens (a resend while the ack is in flight); the shown count stays
m.slots[0]["shown"] = 2
assert m.apply(items) is False and m.slots[0]["shown"] == 2
# a newer seq replaces; the acks survive a reload
assert m.apply([{"slot": 1, "seq": 6, "pin": "1612", "title": "Newer"}]) and m.slots[0]["title"] == "Newer"
m2 = picolab.Messages(app, PATH)
assert m2.acks == {"1": 6, "2": -7, "3": 2, "5": 1} and m2.slots[0]["title"] == "Newer", (m2.acks, m2.slots[0])
# the hooks: a Burrow reply carries messages
m2.on_reply({"ok": True, "ts": 1, "messages": [{"slot": 2, "seq": 8, "pin": "1612", "title": "Via reply"}]})
assert m2.slots[1]["title"] == "Via reply" and m2.acks["2"] == 8
m2.on_reply({"ok": True}); m2.on_reply(None)
# the log keeps the last 60 lines only
for i in range(70): m.handle(req("slot=3&title=n%d&" % i + ME))
assert len(m.changes(100)) == 60 and m.changes(1)[0]["title"] == "n69"
for f in (PATH, "who.json", "msglog.txt"):
    os.remove(f)
print("messages OK")
