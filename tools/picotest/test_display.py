"""Display row layout, off-board: `micropython tools/picotest/test_display.py`
(uses the stubs; no Burrow, no network). Checks that the title gap keeps
every row count on the 64 px panel and clear of the bottom bar."""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import picolab

FONT = 8
PANEL = 64
BAR_Y = 58

layout = picolab.Display.layout
assert layout(5) == [0, 13, 24, 35, 46], layout(5)
assert layout(6) == [0, 12, 22, 32, 42, 52], layout(6)
assert layout(7) == [0, 11, 20, 29, 38, 47, 56], layout(7)
assert layout(5, gap=0) == [0, 11, 22, 33, 44], layout(5, gap=0)

for n in range(1, 8):
    ys = layout(n)
    assert ys[-1] + FONT <= PANEL, (n, ys)                  # on the panel
    if n > 1:
        assert ys[1] - ys[0] - FONT >= 2 + 1, (n, ys)        # title gap on top of the pitch's own
        assert all(b - a >= FONT + 1 for a, b in zip(ys[1:], ys[2:])), (n, ys)
for n in range(1, 6):                                       # bar screens: 5 rows max
    assert layout(n)[-1] + FONT <= BAR_Y, (n, layout(n))

# show() draws where layout() says, and clips with a bar.
class FakeOled:
    def __init__(self): self.calls = []
    def fill(self, c): pass
    def show(self): pass
    def rect(self, *a): pass
    def fill_rect(self, *a): pass
    def text(self, s, x, y): self.calls.append((s, y))

d = picolab.Display(); d.oled = FakeOled()
d.show(["WormHole-07", "In 21.5C 60%", "Out 19.0C 55%", "dT +2.5C"])
assert [y for _, y in d.oled.calls] == [0, 13, 24, 35], d.oled.calls
d.oled.calls = []
d.show(list("abcdefg"), bar=0.5)
assert [y for _, y in d.oled.calls] == [0, 13, 24, 35, 46], d.oled.calls
d.oled.calls = []
d.show(list("abcdefg"))
assert [y for _, y in d.oled.calls] == [0, 11, 20, 29, 38, 47, 56], d.oled.calls
d.oled.calls = []
d.show(["WOODSTOCK", "HIGH SCHOOL"], gap=0)
assert [y for _, y in d.oled.calls] == [0, 11], d.oled.calls
print("display layout OK")
