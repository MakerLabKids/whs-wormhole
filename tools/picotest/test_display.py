"""Display layout + title marquee, off-board:
    micropython tools/picotest/test_display.py
(uses the stubs and the fake clock; no Burrow, no network)."""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import faketime
sys.modules["time"] = faketime
import picolab

D = picolab.Display
layout = D.layout
assert layout(5) == [0, 23, 34, 45, 56], layout(5)             # title + 4 readings, 11 px
assert layout(6) == [0, 12, 23, 34, 45, 56], layout(6)         # + 5 still 11 px
assert layout(7) == [0, 11, 20, 29, 38, 47, 56], layout(7)     # + 6 tightens to 9 px
assert layout(5, bar=True) == [0, 17, 28, 39, 50], layout(5, bar=True)
assert layout(4, bar=True) == [0, 28, 39, 50], layout(4, bar=True)
assert layout(1) == [0] and layout(2) == [0, 56], (layout(1), layout(2))
assert layout(5, title=False) == [0, 11, 22, 33, 44], layout(5, title=False)
assert layout(7, title=False) == [0, 9, 18, 27, 36, 45, 54], layout(7, title=False)

for n in range(1, 8):
    ys = layout(n)
    assert ys[-1] + D.FONT <= D.PANEL, (n, ys)                         # on the panel
    assert n < 2 or ys[1] >= D.RULE_Y + 2, (n, ys)                      # clear of the rule
    assert all(b - a >= D.FONT + 1 for a, b in zip(ys[1:], ys[2:])), (n, ys)
    assert n < 2 or ys[-1] + D.FONT == D.PANEL, (n, ys)                 # bottom-justified
for n in range(2, 6):
    ys = layout(n, bar=True)
    assert ys[-1] + D.BAR_Y == D.BAR_Y + ys[-1] and ys[-1] + D.FONT == D.BAR_Y and ys[1] >= D.RULE_Y + 2, (n, ys)


class FakeOled:
    def __init__(self): self.calls = []; self.lines = []; self.shows = 0
    def fill(self, c): pass
    def show(self): self.shows += 1
    def rect(self, *a): pass
    def fill_rect(self, *a): pass
    def text(self, s, x, y): self.calls.append((s, x, y))
    def hline(self, x, y, w, c): self.lines.append((x, y, w))
    def title(self): return [c for c in self.calls if c[2] == 0][0]


def fresh(lines, **kw):
    d = D(); d.oled = FakeOled(); d.show(lines, **kw); return d

# a short title is centered, underlined to its own width; readings at the left
d = fresh(["The Wrigglers", "AIR: 23.1C 46%", "PRESS: 1028 hPa", "MOIST: 84%", "DIST: 242 mm"])
assert d.oled.title() == ("The Wrigglers", 12, 0), d.oled.title()          # (128 - 13*8) // 2
assert [(x, y) for _, x, y in d.oled.calls if y] == [(0, 23), (0, 34), (0, 45), (0, 56)], d.oled.calls
assert d.oled.lines == [(12, 9, 13 * 8)], d.oled.lines
d = fresh(["Sixteen chars!!!", "x"])
assert d.oled.title() == ("Sixteen chars!!!", 0, 0) and d.oled.lines == [(0, 9, 128)]
# with a bar, 5 rows max; 7 without; the splash is plain rows
d = fresh(list("abcdefg"), bar=0.5)
assert sorted(y for _, _, y in d.oled.calls) == [0, 17, 28, 39, 50], d.oled.calls
d = fresh(list("abcdefg"))
assert sorted(y for _, _, y in d.oled.calls) == [0, 11, 20, 29, 38, 47, 56], d.oled.calls
d = fresh(["WOODSTOCK", "HIGH SCHOOL"], title=False)
assert [(x, y) for _, x, y in d.oled.calls] == [(0, 0), (0, 11)] and d.oled.lines == [], d.oled.calls
# a lone row is just a row
d = fresh(["a title that is far too long to fit"])
assert d.oled.calls == [("a title that is ", 0, 0)] and d.oled.lines == [], d.oled.calls

# ---- the marquee: hold 5 s, scroll the text through, hold again ------------
def run(d, ms):
    """advance the fake clock ms, ticking every 10 ms; return the titles drawn"""
    seen = []
    for _ in range(ms // 10):
        faketime.advance(0.01); d.oled.calls = []; d.tick()
        if d.oled.calls: seen.append(d.oled.title())
    return seen

d = fresh(["Dirt Nerds", "IN: 24.1C 71%"]); d.marquee = "Woodstock High School and Maker Lab Kids - Vermiculture PBL by:"
assert run(d, 4990) == [], "nothing moves during the hold"
seen = run(d, 20)
assert seen and seen[0][0] == d.marquee and seen[0][1] == 128, seen[:2]    # enters from the right
seen = run(d, 13000)                   # one full crossing (632 px at 50 px/s = 12.6 s)
xs = [x for t, x, _ in seen if t == d.marquee]
assert xs[0] == 127 and all(b - a == -1 for a, b in zip(xs, xs[1:])), xs[:5]  # a pixel at a time, every 20 ms
assert xs[-1] + len(d.marquee) * 8 == 1, xs[-1]                               # last frame: a sliver left, then gone
assert len(xs) == 632 - 1 - 1 + 1, len(xs)
back = [c for c in seen if c[0] == "Dirt Nerds"]
assert back and back[0][1] == (128 - 10 * 8) // 2 and d._mq is False, (back[:1], d._mq)   # home, centered
# the rule travelled with the text: never wider than the screen, never past the glyphs
d.oled.lines = []; d._mq, d._x = True, -200; d._draw()
assert d.oled.lines == [(0, 9, 128)], d.oled.lines
d._x = 100; d._draw()
assert d.oled.lines[-1] == (100, 9, 28), d.oled.lines[-1]
d._x = -8 * (len(d.marquee) - 4); d._draw()
assert d.oled.lines[-1] == (0, 9, 32), d.oled.lines[-1]
# a new reading during the scroll keeps the marquee where it was
d._mq, d._x = True, 40; d.oled.calls = []; d.show(["Dirt Nerds", "IN: 25.0C 70%"])
assert d.oled.title() == (d.marquee, 40, 0), d.oled.title()
# after the marquee the name holds another 5 s before it runs again
d = fresh(["Dirt Nerds", "x"]); d.marquee = "short marquee"
run(d, 5010)
assert d._mq is True
while d._mq:
    run(d, 10)
assert run(d, 4900) == [] and run(d, 200), "the second hold is 5 s too"

# the hold starts with the first titled screen, not when the Display was made (the splash comes first)
d = D(); d.oled = FakeOled(); d.marquee = "m"
d.show(["WOODSTOCK", "HIGH SCHOOL"], title=False); faketime.advance(3)
d.show(["Dirt Nerds", "x"])
assert run(d, 4990) == [] and run(d, 20), "5 s from the first titled screen"

# ---- a long name scrolls on its own, and still gets its 5 s ----------------
long = "The Magnificent Decomposers"            # 27 chars: wider than the screen
d = fresh([long, "x"])
assert d.oled.title() == (long, 0, 0) and d.oled.lines == [(0, 9, 128)], (d.oled.title(), d.oled.lines)
seen = run(d, 10000)                             # no marquee: it just keeps scrolling
xs = [x for t, x, _ in seen]
assert xs[0] == 128 and 128 in xs[1:] and all(t == long for t, _, _ in seen), xs[:3]
d = fresh([long, "x"]); d.marquee = "and the marquee"
seen = run(d, 4000)                              # inside the hold: only the name passes
assert seen and all(t == long for t, _, _ in seen), seen[:2]
seen = run(d, 30000)
order = []
for t, _, _ in seen:
    if not order or order[-1] != t: order.append(t)
assert order[:3] == [long, "and the marquee", long], order                  # name, marquee, name
first_mq = [c for c in seen if c[0] == "and the marquee"][0]
assert first_mq[1] == 128, first_mq                                           # it waited for the name's pass to end
print("display layout + marquee OK")

# ---- the shows: name, marquee, name, a show, name, marquee, name, the next show...
class Show:
    frames = 10
    def __init__(self): self.drawn = []
    def draw(self, o, t): self.drawn.append(t); o.text("frame", 0, 0)
class ShowA(Show): name = "A"
class ShowB(Show): name = "B"

def phases(d, ms):
    """what was on the title row, as it changed, over ms"""
    out = []
    for _ in range(ms // 10):
        faketime.advance(0.01); d.oled.calls = []; d.tick()
        if d.oled.calls:
            t = d.oled.title()[0]
            t = "show" if t == "frame" else ("mq" if t == d.marquee else "name")
            if not out or out[-1] != t: out.append(t)
    return out

d = fresh(["Dirt Nerds", "x"]); d.marquee = "short marquee"; d.shows = [ShowA, ShowB]
assert run(d, 4990) == [], "the first hold is untouched"
seen = phases(d, 40000)
assert seen[:6] == ["mq", "name", "show", "name", "mq", "name"], seen
assert seen[6:8] == ["show", "name"], seen
assert d._show_idx >= 2 and d._show is None, (d._show_idx, d._show)
# the shows ran in order, every frame once, at SHOW_FPS, then held the last frame
d = fresh(["Dirt Nerds", "x"]); d.marquee = "m"; d.shows = [ShowA, ShowB]
run(d, 5010); 
while d._mq: run(d, 10)
run(d, 5010)                                     # the second hold ends with a show
assert d._show and d._show.name == "A", d._show
show, t0, frames = d._show, faketime.ticks_ms(), []
while d._show:
    faketime.advance(0.01); d.oled.calls = []; d.tick()
    if d.oled.calls and d.oled.title()[0] == "frame": frames.append(faketime.ticks_diff(faketime.ticks_ms(), t0))
assert show.drawn == list(range(10)), show.drawn                             # every frame once, in order (0 came with the start)
assert all(b - a == 1000 // D.SHOW_FPS for a, b in zip(frames, frames[1:])), frames
assert faketime.ticks_diff(faketime.ticks_ms(), t0) - frames[-1] == D.SHOW_HOLD_MS, (frames[-1], faketime.ticks_ms() - t0)
assert d.oled.title() == ("Dirt Nerds", 24, 0), d.oled.title()             # straight back to the centered name
assert run(d, 4990) == [] and run(d, 20), "and a fresh 5 s hold"
while d._mq: run(d, 10)
run(d, 5010)
assert d._show and d._show.name == "B", d._show                              # the next one, in order
# new readings during a show wait: the show keeps the screen, the rows land after it
d.oled.calls = []; d.show(["Dirt Nerds", "MOIST: 50%"])
assert d.oled.calls == [], d.oled.calls
while d._show: run(d, 10)
assert ("MOIST: 50%", 0, 56) in d.oled.calls, d.oled.calls
# a stalled loop (a slow sensor sweep) skips frames; the show keeps its tempo and its length
d = fresh(["Dirt Nerds", "x"]); d.shows = [ShowA]
run(d, 5010); show = d._show; assert show and show.drawn == [0], show
run(d, 100)                                      # frames 1, 2
faketime.advance(0.3); d.tick()                  # 300 ms gone in one pass: straight to frame 8
assert show.drawn == [0, 1, 2, 8], show.drawn
while d._show: run(d, 10)
assert show.drawn == [0, 1, 2, 8, 9] and d._show_drawn == 5, show.drawn
assert faketime.ticks_diff(faketime.ticks_ms(), d._hold_at) < 20 and d.oled.title()[0] == "Dirt Nerds"
# shows without a marquee: name, show, name, show
d = fresh(["Dirt Nerds", "x"]); d.shows = [ShowA]
assert phases(d, 20000)[:4] == ["show", "name", "show", "name"]
# a long name: its passes, then a show, then its passes again
d = fresh([long, "x"]); d.marquee = ""; d.shows = [ShowA]
seen = phases(d, 15000)
assert seen[:3] == ["name", "show", "name"], seen
print("worm show cycle OK")
