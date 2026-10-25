# Vibration demo: buzz and TAP the worm bin on command, and watch how the
# worms respond (tap-and-flee, startle, drift away from a buzz). The
# stimulus half of the Worm Behavior Lab; pair it with a sensor to log the
# response.
#
# The Pico opens a Wi-Fi network named PicoLab<N>. Join it and browse to
# http://192.168.4.1: set the buzz strength, buzz on/off, or fire a burst
# of N sharp taps.
#
# Wiring: a tiny DC vibrating motor can't run straight off a GPIO pin (a
# pin gives a few mA; the motor wants ~100 mA), so it goes through a
# transistor switch:
#   motor + lead   -> 3V3 (a 3 V pager motor is happy here)
#   motor - lead   -> NPN transistor COLLECTOR (2N2222)
#   transistor EMITTER -> GND
#   transistor BASE -> 1k resistor -> GP19 (physical PIN 25)
#   flyback diode (1N4001) ACROSS the motor, band toward 3V3.
# The diode is not optional: without it the motor's collapse spike can
# hurt the transistor and reset the Pico. The 37-in-1 kit's vibration
# module has this driver built in, wire its S pin to GP19 and skip the
# transistor.
#
# Boot self-test: two quick taps, so you know it is wired before you touch
# the web page. Nothing on boot = power/wiring (check the transistor).
#
# On the board: main.py, index.html, lib/picolab.py, lib/ssd1306.py.
#
# Project page: https://github.com/MakerLabKids/whs-wormhole/tree/main/projects/vibration

import gc
import time
from machine import Pin, PWM

import picolab

# ===== CONFIG =====
VIB_PIN = 19       # PWM to the transistor base (via 1k); default GP19, physical pin 25
TAP_LEVEL = 100    # strength of a tap, percent
TAP_ON_MS = 70     # how long each tap drives the motor
TAP_GAP_MS = 130   # quiet gap between taps
# ==================

motor = PWM(Pin(VIB_PIN))
motor.freq(500)


def drive(level):
  # level is 0..100 percent
  level = max(0, min(100, level))
  motor.duty_u16(int(level / 100 * 65535))


class Tapper:
  """Plays a non-blocking sequence of (level, ms) segments."""
  def __init__(self):
    self.segs, self.until, self.active = [], 0, False

  def load(self, segs):
    self.segs = list(segs)
    self.active = bool(self.segs)
    self.until = time.ticks_ms()

  def cancel(self):
    self.segs, self.active = [], False
    drive(0)

  def tick(self):
    if not self.active:
      return
    now = time.ticks_ms()
    if time.ticks_diff(now, self.until) < 0:
      return
    if not self.segs:
      self.active = False
      drive(0)
      return
    level, ms = self.segs.pop(0)
    drive(level)
    self.until = time.ticks_add(now, ms)


def taps(n, level=TAP_LEVEL):
  seq = []
  for _ in range(max(1, min(50, n))):
    seq.append((level, TAP_ON_MS))
    seq.append((0, TAP_GAP_MS))
  return seq


mode = "off"        # off | buzz | tap
buzz_level = 60
tapper = Tapper()

# boot self-test: two taps (before any Wi-Fi)
tapper.load(taps(2))
_t0 = time.ticks_ms()
while tapper.active and time.ticks_diff(time.ticks_ms(), _t0) < 1500:
  tapper.tick()
  time.sleep_ms(5)
drive(0)


def set_handler(req):
  global mode, buzz_level
  lvl = picolab.query_int(req, "level")
  if lvl is not None:
    buzz_level = max(0, min(100, lvl))
    if mode == "buzz":
      drive(buzz_level)
  if b"buzz=1" in req:
    mode = "buzz"
    tapper.cancel()
    drive(buzz_level)
  n = picolab.query_int(req, "tap")
  if n is not None:
    mode = "tap"
    tapper.load(taps(n, buzz_level if buzz_level else TAP_LEVEL))
  if b"stop=1" in req:
    mode = "off"
    tapper.cancel()
    drive(0)
  return data_fn()


def data_fn():
  return {
      "ok": True,
      "ssid": app.ssid,
      "mode": mode,
      "level": int(buzz_level),
      "tapping": tapper.active,
  }


display = picolab.Display()
light = picolab.StatusLight()
light.set_slots([True])
app = picolab.WebApp()
app.index = "vibration/index.html"
heartbeat = picolab.Throttle(5000)

app.announce("Vibration Station Active!")
picolab.log("Vibration ready on GP%d. Boot taps done." % VIB_PIN)

while True:
  light.poll()
  tapper.tick()

  webline = app.ip if app.server else "web off: replug"
  if mode == "buzz":
    line3 = "buzz %d%%" % buzz_level
  elif mode == "tap":
    line3 = "tapping..." if tapper.active else "tap done"
  else:
    line3 = "still"
  display.show([app.ssid, webline, line3, "GP%d -> motor" % VIB_PIN])

  if heartbeat.ready():
    picolab.log("Vibration mode:", mode, "level:", buzz_level)

  app.poll(data_fn, routes=[("/set", set_handler)])
  gc.collect()
