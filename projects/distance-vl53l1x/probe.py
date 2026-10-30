# probe.py - bench probe for the VL53L1X with a signal light, so the person
# holding the target (or staying OUT of the beam) can watch the Pico LED
# instead of a terminal:
#
#   5 slow flashes  = get ready (about 10 s)
#   fast flicker    = measuring, hold still
#   one long ON     = done, relax
#
# Prints one line per measurement with the chip's own diagnostics (range
# status, return signal, ambient light, sigma) and a summary. Edit the three
# constants below, or use tools/laser-probe.sh which fills them in:
#
#     tools/laser-probe.sh 8 full wall-112cm      # seconds, roi, label
#
# Wiring: VIN=3V3, GND=GND, SDA=GP0, SCL=GP1. On six-pin boards leave GPIO1
# and XSHUT unconnected (XSHUT pulled low = chip asleep, nothing on the bus).
# Needs lib/vl53l1x.py:  mpremote mount lib run projects/distance-vl53l1x/probe.py

import os, sys, time
from machine import Pin, I2C

SECONDS = 8          # how long to measure
ROI = 16             # 16 = full ~27 deg cone, 8 = ~20 deg, 4 = ~15 deg
LABEL = "probe"

STATUS = {9: "OK", 8: "minrange", 6: "sigma-fail", 4: "signal-fail",
          5: "wraparound", 7: "wrap-fail", 3: "hw-fail", 19: "nowrapchk", 12: "xtalk"}

led = Pin("LED", Pin.OUT)


def flash(n, on_ms, off_ms):
  for _ in range(n):
    led.on(); time.sleep_ms(on_ms); led.off(); time.sleep_ms(off_ms)


Pin(2, Pin.IN); Pin(3, Pin.IN)       # GPIO1 / XSHUT released if wired
bus = I2C(0, sda=Pin(0), scl=Pin(1), freq=400000)
from vl53l1x import VL53L1X
dev = VL53L1X(bus, roi=ROI)

print("== %s | roi %d | %d s ==" % (LABEL, ROI, SECONDS))
print("GET READY: 5 slow flashes")
flash(5, 1000, 1000)
print("MEASURING")
print("    t  status        range   signal  ambient  sigma")
t0 = time.ticks_ms(); prev = None; rows = []; tick = 0
while time.ticks_diff(time.ticks_ms(), t0) < SECONDS * 1000:
  d = bus.readfrom_mem(0x29, 0x0089, 17, addrsize=16)
  k = bytes(d)
  if k != prev:                      # a new measurement, not a re-read
    prev = k
    st = d[0] & 0x1F
    mm = (d[13] << 8) | d[14]
    sig = ((d[15] << 8) | d[16]) / 128      # MCPS
    amb = ((d[7] << 8) | d[8]) / 128        # MCPS
    sigma = ((d[9] << 8) | d[10]) / 4       # mm
    rows.append((st, mm, sig, amb))
    print("%5.1f  %2d %-11s %5d  %7.2f  %7.2f  %5.1f" % (
        time.ticks_diff(time.ticks_ms(), t0) / 1000, st, STATUS.get(st, "?"), mm, sig, amb, sigma))
  tick ^= 1; led.value(tick)
  time.sleep_ms(60)
led.on(); time.sleep_ms(2000); led.off()

ok = sorted(r[1] for r in rows if r[0] == 9)
bad = {}
for r in rows:
  if r[0] != 9:
    bad[STATUS.get(r[0], r[0])] = bad.get(STATUS.get(r[0], r[0]), 0) + 1
print("DONE: n=%d ok=%d median %s min %s max %s mm  signal %.2f ambient %.2f MCPS  bad=%s" % (
    len(rows), len(ok), ok[len(ok) // 2] if ok else "-", ok[0] if ok else "-", ok[-1] if ok else "-",
    sum(r[2] for r in rows) / max(1, len(rows)), sum(r[3] for r in rows) / max(1, len(rows)), bad))
