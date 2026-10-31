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
assert xs[0] == 126 and all(b - a == -2 for a, b in zip(xs, xs[1:])), xs[:5]   # 2 px every step
assert 0 < xs[-1] + len(d.marquee) * 8 <= D.SCROLL_PX, xs[-1]                 # last frame: a sliver left, then gone
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
