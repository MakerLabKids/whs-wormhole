"""The fast demo loop: micropython tools/picotest/test_demo_loop.py"""
import sys, os
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib"); sys.path.append("tools")   # last: tools/logos/ is a folder of PNGs
import faketime
sys.modules["time"] = faketime
import time
import ssd1306, wormshow

D = "/tmp/demo-loop-test"
try:
  os.mkdir(D)
except OSError:
  pass
for n in os.listdir(D):
  os.remove(D + "/" + n)
with open(D + "/cat.pbm", "wb") as f:
  f.write(b"P4\n# fps 5\n8 8\n" + bytes(8) + b"P4\n8 8\n" + bytes(8))


class FakeI2C:
  def writeto(self, *a): pass
  def writeto_mem(self, *a): pass


class Counting(ssd1306.SSD1306_I2C):
  def __init__(self):
    self.refreshes = 0
    super().__init__(128, 64, FakeI2C())
    self.refreshes = 0

  def show(self):
    self.refreshes += 1


sleeps = []
real_sleep = time.sleep_ms
time.sleep_ms = lambda ms: sleeps.append(ms)

import pbmshow
pbmshow.SHOW_DIR = D
import demo_loop
shows = demo_loop.demo_list()
names = [s.name for s in shows]
assert names[:2] == ["Woodstock High", "Maker Lab Kids"], names
assert names[2:12] == [c.name for c in wormshow.SHOWS], names
assert names[12:] == ["cat"], names

o = Counting()
wormshow.play(o, loop=False, fps=20, hold_ms=0, shows=shows)
want = sum(s.frames for s in shows)
assert o.refreshes == want, (o.refreshes, want)
# no hold between shows: every sleep is frame pacing (under one 20 fps frame, or the
# cat video's 5 fps = 200 ms), never the old 600 ms hold
assert all(ms <= 200 for ms in sleeps), max(sleeps)
assert 600 not in sleeps
time.sleep_ms = real_sleep

# the default call still holds 600 ms after each show
sleeps2 = []
time.sleep_ms = lambda ms: sleeps2.append(ms)
wormshow.play(o, loop=False, only="Big Worm")
time.sleep_ms = real_sleep
assert sleeps2[-1] == 600, sleeps2[-3:]
print("demo loop: %d shows, %d frames back to back: ok" % (len(shows), want))
