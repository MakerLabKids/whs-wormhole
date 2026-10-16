# Hello World: the smallest possible MicroPython program.
#
# Brand-new board? Flash MicroPython first (one time): hold BOOTSEL
# while plugging into USB, then drop this .uf2 onto the drive:
# https://github.com/MakerLabKids/wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2
#
# Open viper-ide.org, connect your Pico, and run this file.
# Everything print() sends shows up in the terminal panel.

import time

print("Hello, world!")
print("Hello from a Raspberry Pi Pico 2 W!")

# The Pico can do math faster than you can blink
answer = 6 * 7
print("6 x 7 =", answer)

# ...and it never gets tired of saying hi
for i in range(5):
  print("Hello number", i + 1)
  time.sleep(0.5)

print("Done! Now try changing the message and run it again.")
