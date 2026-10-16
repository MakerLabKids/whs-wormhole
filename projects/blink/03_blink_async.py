# Blink, level 3: blink WHILE doing other things (asyncio).
#
# The problem with time.sleep(): it freezes the whole program. A blink
# loop that sleeps cannot also read sensors, serve a webpage, or count.
# asyncio fixes that: every task takes turns during the awaits, so the
# LED never misses a beat while real work happens.
#
# This is the same trick every fault-tolerant web demo in this repo
# uses (they do it with poll() calls; asyncio is the cleaner way you
# will grow into).
#
# Project page (docs, all levels, install link): https://github.com/MakerLabKids/wormhole/tree/main/projects/blink

BLINK_ON_MS = 100      # short flash...
BLINK_OFF_MS = 900     # ...once a second: the classic heartbeat
REPORT_EVERY_S = 2     # how often the "work" task reports in

# ---- no configuration below this line ----

import asyncio
from machine import Pin

led = Pin("LED", Pin.OUT)


async def heartbeat():
  """The truth light: blinks forever, no matter what else runs."""
  while True:
    led.on()
    await asyncio.sleep_ms(BLINK_ON_MS)
    led.off()
    await asyncio.sleep_ms(BLINK_OFF_MS)


async def work():
  """Pretend work. Swap in a sensor read and this is a real station."""
  report = 0
  while True:
    report += 1
    total = 0
    for n in range(50000):   # keep the CPU honestly busy for a moment
      total += n
    print("report", report, "- work done (sum =", total,
          ") and the heartbeat never skipped")
    await asyncio.sleep(REPORT_EVERY_S)


async def main():
  await asyncio.gather(heartbeat(), work())

asyncio.run(main())

# Things to try:
#   1. Add a third task that prints "tick" every 5 seconds. Three
#      things at once, zero extra difficulty. That is the point.
#   2. Make the heartbeat double-flash (two quick blinks per second).
#   3. Change work() to read the chip temperature like 04-webserver.
