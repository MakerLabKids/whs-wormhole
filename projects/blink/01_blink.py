# Blink, level 1: the "hello world" of hardware.
#
# The Pico 2 W has an onboard LED wired to a pin named "LED".
# No wiring needed. Run it and watch the board.
#
# This IS the truth light at its most basic: if the LED is blinking,
# your code is running. If it is dark, it is not. No guessing.
#
# Project page (docs, all levels, install link): https://github.com/MakerLabKids/whs-wormhole/tree/main/projects/blink

import time
from machine import Pin

led = Pin("LED", Pin.OUT)

while True:
  led.on()
  time.sleep(0.5)
  led.off()
  time.sleep(0.5)

# Things to try:
#   1. Make it blink faster. How fast until it just looks "on"?
#   2. Blink SOS: three short, three long, three short.
#   3. Tired of digging in the loop to change timings? That is exactly
#      what 02_blink_config.py fixes.
#
# Press Ctrl+C in the terminal (or the Stop button) to stop the loop.
