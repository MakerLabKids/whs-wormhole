"""Display row layout, off-board: `micropython tools/picotest/test_display.py`
(uses the stubs; no Burrow, no network). The title sits at the top with an
underline; readings stack up from the bottom (or from above the bar) at
11 px, tightening only when the top one would hit the rule."""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
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
    assert ys[-1] + D.FONT == D.BAR_Y and ys[1] >= D.RULE_Y + 2, (n, ys)

# show() draws where layout() says, underlines just the title's width, clips with a bar.
class FakeOled:
    def __init__(self): self.calls = []; self.lines = []
    def fill(self, c): pass
    def show(self): pass
    def rect(self, *a): pass
    def fill_rect(self, *a): pass
    def text(self, s, x, y): self.calls.append((s, y))
    def hline(self, x, y, w, c): self.lines.append((x, y, w))

d = D(); d.oled = FakeOled()
d.show(["The Wrigglers", "AIR: 23.1C 46%", "PRESS: 1028 hPa", "MOIST: 84%", "DIST: 242 mm"])
assert [y for _, y in d.oled.calls] == [0, 23, 34, 45, 56], d.oled.calls
assert d.oled.lines == [(0, 9, 13 * 8)], d.oled.lines
d.oled = FakeOled()
d.show(list("abcdefg"), bar=0.5)
assert [y for _, y in d.oled.calls] == [0, 17, 28, 39, 50], d.oled.calls
d.oled = FakeOled()
d.show(list("abcdefg"))
assert [y for _, y in d.oled.calls] == [0, 11, 20, 29, 38, 47, 56], d.oled.calls
d.oled = FakeOled()
d.show(["WOODSTOCK", "HIGH SCHOOL"], title=False)
assert [y for _, y in d.oled.calls] == [0, 11] and d.oled.lines == [], d.oled.calls
d.oled = FakeOled()
d.show(["a title that is far too long to fit"])
assert d.oled.calls == [("a title that is ", 0)] and d.oled.lines == [], d.oled.calls
print("display layout OK")
