# Blink your NAME in morse code!
#
# Type your name below, hit run, and the LED spells it out. The
# terminal prints each letter's pattern as it blinks so you can follow
# along. And of course: if it is blinking your name, your code is
# DEFINITELY running.
#
# Project page (docs, all levels, install link): https://github.com/MakerLabKids/whs-wormhole/tree/main/projects/blink

NAME = "MAKER LAB"   # <-- your name here! letters, numbers, spaces
UNIT_MS = 150        # dit length. Bigger = slower, easier to read
REPEAT = True        # blink the name forever? False = once and stop

# ---- no configuration below this line ----

import time
from machine import Pin

# dit = 1 unit ON, dah = 3 units ON. Gaps: 1 unit between symbols,
# 3 between letters, 7 between words. (Real international morse!)
MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".",
    "F": "..-.", "G": "--.", "H": "....", "I": "..", "J": ".---",
    "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---",
    "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--",
    "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--",
    "4": "....-", "5": ".....", "6": "-....", "7": "--...",
    "8": "---..", "9": "----.",
}

led = Pin("LED", Pin.OUT)


def flash(units):
  led.on()
  time.sleep_ms(UNIT_MS * units)
  led.off()


def blink_name(name):
  for ch in name.upper():
    if ch == " ":
      print("   (word gap)")
      time.sleep_ms(UNIT_MS * 7)
      continue
    pattern = MORSE.get(ch)
    if pattern is None:
      print(ch, "?  (no morse for that one, skipping)")
      continue
    print(ch, pattern)
    for i, symbol in enumerate(pattern):
      flash(1 if symbol == "." else 3)
      if i < len(pattern) - 1:
        time.sleep_ms(UNIT_MS)        # gap between symbols
    time.sleep_ms(UNIT_MS * 3)        # gap between letters


print("Blinking:", NAME)
while True:
  blink_name(NAME)
  if not REPEAT:
    break
  print("--- again ---")
  time.sleep_ms(UNIT_MS * 14)

print("Done.")

# Things to try:
#   1. Your whole name. Then just your initials at UNIT_MS = 60. Speed
#      reading, literally.
#   2. Wire a piezo buzzer to a GPIO and beep it in sync with the LED.
#   3. Point a phone camera at the LED and decode a friend's name.
