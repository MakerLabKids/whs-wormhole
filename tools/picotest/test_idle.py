"""picolab.idle_ms: the Wi-Fi join's waits keep the screen's power-on sequence playing, off-board:
    micropython tools/picotest/test_idle.py"""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import faketime
sys.modules["time"] = faketime
import picolab

calls = []
picolab.IDLE = lambda: calls.append(faketime.ticks_ms())
t0 = faketime.ticks_ms()
picolab.idle_ms(500)
assert faketime.ticks_diff(faketime.ticks_ms(), t0) >= 500, "waits the whole time"
assert len(calls) >= 20, "runs the idle hook every ~20 ms: %d calls" % len(calls)

# a hook that fails is logged and the wait goes on
logged = []
picolab.log = lambda *a: logged.append(" ".join(str(x) for x in a))
def boom():
  raise ValueError("no screen")
picolab.IDLE = boom
picolab.idle_ms(60)
assert logged and "no screen" in logged[0], logged

# no hook: a plain wait
picolab.IDLE = None
t0 = faketime.ticks_ms()
picolab.idle_ms(100)
assert faketime.ticks_diff(faketime.ticks_ms(), t0) >= 100
picolab.idle_ms(0)
print("idle OK")
