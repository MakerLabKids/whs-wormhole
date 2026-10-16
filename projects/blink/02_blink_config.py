# Blink, level 2: the knobs live AT THE TOP.
#
# House rule for every program in this repo: tunable numbers go at the
# top of the file, named in CAPS, so changing behavior never means
# digging through loop code. Change a number, hit run, see the change.
#
# Project page (docs, all levels, install link): https://github.com/MakerLabKids/wormhole/tree/main/projects/blink

ON_TIME_S = 0.2     # how long the LED stays on each blink
OFF_TIME_S = 0.8    # how long it stays off
BLINK_LIMIT = 0     # stop after this many blinks. 0 = forever

# ---- no configuration below this line ----

import time
from machine import Pin

led = Pin("LED", Pin.OUT)
count = 0

while BLINK_LIMIT == 0 or count < BLINK_LIMIT:
  led.on()
  time.sleep(ON_TIME_S)
  led.off()
  time.sleep(OFF_TIME_S)
  count += 1

print("Done:", count, "blinks.")

# Things to try:
#   1. A quick double-flash "heartbeat": ON 0.1, OFF 0.1... but wait,
#      that needs two different off-times. Add a PAUSE_S config and a
#      second flash to the loop. Congratulations, you are programming.
#   2. Set BLINK_LIMIT to 10 and time it. Does the math check out?
