"""picolab.Smoother, off-board: micropython tools/picotest/test_smoother.py"""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import picolab

s = picolab.Smoother(alpha=0.5, n=4)
assert s.avg is None and s.now is None
assert s.feed(100) == (100, 100.0)
assert s.feed(110) == (105.0, 105.0)             # now leans to the latest, avg is the plain mean
assert s.feed(110) == (107.5, 320 / 3)
assert s.feed(110) == (108.75, 107.5)
assert s.feed(110) == (109.375, 110.0)           # the 100 fell out of the 4-sample window
assert s.count == 4
s.reset()
assert s.avg is None and s.feed(5) == (5, 5.0)
# a step settles in a few samples for `now`, a whole window for `avg`
s = picolab.Smoother(alpha=0.5, n=120)
for _ in range(120): s.feed(257)
s.feed(40); s.feed(40); s.feed(40); s.feed(40)
assert abs(s.now - 40) < 14 and s.avg > 240, (s.now, s.avg)
print("smoother OK")
