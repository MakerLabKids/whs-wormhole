"""The worm-bin fan (projects/worm-bin/main.py, class Fan), off-board:
    micropython tools/picotest/test_fan.py
Runs the class's own source against the fake clock and a fake pin."""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import faketime
sys.modules["time"] = faketime
src = open("projects/worm-bin/main.py").read()
a = src.index("class Fan:"); b = src.index("fan = Fan(")
logs = []
class FakeLab:
  def log(*a): logs.append(" ".join(str(x) for x in a))
class Pin:
  v = 0
  def value(self, x=None):
    if x is None: return self.v
    self.v = x
g = {"time": faketime, "picolab": FakeLab, "FAN_HUMID_PCT": 80, "FAN_EVERY_MIN": 15, "FAN_RUN_S": 60}
exec(src[a:b], g)
p = Pin(); f = g["Fan"](p)
def run(s, hum):
  for _ in range(int(s * 2)):
    faketime.advance(0.5); f.poll(hum)
run(59, 95); assert p.v == 0, "no check in the first minute"
run(1, 95); assert p.v == 1, "a minute in: damp, the fan runs"
run(59, 95); assert p.v == 1
run(1.5, 95); assert p.v == 0, "off after 60 s"
run(14 * 60 - 2, 95); assert p.v == 0, "nothing until the next check"
run(3, 95); assert p.v == 1, "15 minutes later, still damp: again"
run(61, 95); assert p.v == 0
run(15 * 60, 70); assert p.v == 0, "dry: stays off"
run(15 * 60, None); assert p.v == 0, "no reading: stays off"
run(15 * 60, 80); assert p.v == 0, "80 is not above 80"
f.run(3000, "power-on check"); assert p.v == 1
run(3.5, 50); assert p.v == 0, "the 3 s power-on run ends"
f.toggle(); assert p.v == 1; f.toggle(); assert p.v == 0
print("fan OK")
