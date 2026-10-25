# Servo web demo: move something in the real world from a web page.
#
# The Pico opens a Wi-Fi network named PicoLab<N>. Join it and browse
# to http://192.168.4.1: a dial, a slider, and three modes:
#   manual = the slider commands the servo
#   sweep  = slow automatic 0 to 180 sweep
#   auto   = "follow light": an optional photoresistor on GP28 steers
#            the servo (sensor moves the real world!)
#
# A servo gives no feedback, so this demo cannot tell if the servo is
# actually plugged in; it keeps commanding angles and the servo starts
# moving the moment it is connected. Display optional as always.
# The truth light (the onboard LED, short blink every cycle) proves the
# CODE is running; if the servo still does not move, check its wiring.
#
# Wiring, the 3 servo wires (a servo with no power CANNOT move, no matter
# what the code does -- this is the #1 reason a servo "does nothing"):
#   RED (power)   -> VBUS = physical PIN 40 (5V). NOT 3V3! Wrong pin = no
#                    movement. (VBUS is the top-RIGHT pin, USB at the top.)
#   BROWN/black   -> any GND (e.g. physical pin 38).
#   ORANGE/yellow -> the signal, GP16 = physical PIN 21.
# On boot the servo does a small self-test wiggle: if it does NOT wiggle,
# it is power/wiring (check the RED wire on pin 40), not the code.
#
# BROWN-OUTS: a servo gulps a big spike of current the instant it starts
# moving (and a lot more if it stalls). Off USB that spike can dip the 5V
# rail enough to RESET the Pico -- the screen blanks and it reboots every
# time the servo moves. Best fix: power the servo from its OWN 5V supply
# (a phone charger or battery pack), sharing ONLY the ground with the Pico
# (signal still goes to GP16). If you must run it off USB/VBUS, solder a
# fat capacitor (470-1000uF electrolytic, mind the polarity) across the
# servo's 5V and GND right at the servo to soak up the spikes.
#
# Auto mode (optional): GL5528 photoresistor from 3V3 to GP28, plus a
# 10k resistor from GP28 to GND.
# On the board: main.py, index.html, lib/picolab.py, lib/ssd1306.py.
#
# Project page (docs, wiring, install link): https://github.com/MakerLabKids/whs-wormhole/tree/main/projects/servo

import gc
import time
from machine import ADC, PWM, Pin

import picolab

MIN_US = 600
MAX_US = 2400
# How fast the servo slews to a new angle, in DEGREES PER SECOND. Motion
# is ramped and TIME-BASED, so the number here is the ACTUAL speed no
# matter how busy the web loop gets (a fixed step-per-tick would crawl
# when the loop is busy -- that was the old bug). An SG90 tops out near
# 500 deg/s; 400 is fast and snappy. Lower for slow-motion; set very high
# (e.g. 2000) for a near-instant snap. (Old default was a poky 60.)
SPEED_DPS = 400
SERVO_PIN = 16  # servo signal (orange lead); default GP16, physical pin 21
LDR_PIN = 28    # optional photoresistor for follow-light mode; default GP28

pwm = PWM(Pin(SERVO_PIN))
pwm.freq(50)

ldr = ADC(Pin(LDR_PIN))


def write_angle(angle):
  angle = max(0.0, min(180.0, angle))
  us = MIN_US + (angle / 180.0) * (MAX_US - MIN_US)
  pwm.duty_u16(int(us * 65535 / 20000))
  return angle


mode = "manual"
current = 90.0
target = 90.0
light_pct = 0.0
write_angle(current)

# Power-on self-test: a visible wiggle so you can tell RIGHT AWAY whether
# the servo is wired and powered, WITHOUT needing the web page (which can
# be held up by a busy port 80 after a soft re-run). No wiggle = power or
# wiring: check the RED wire is on VBUS (physical PIN 40), signal on GP16
# (pin 21), ground on GND. This runs before any Wi-Fi, so it always fires.
for _a in (75, 105, 90):
  write_angle(_a)
  time.sleep_ms(350)


def set_handler(req):
  global mode, target, SPEED_DPS
  angle = picolab.query_int(req, "angle")
  if angle is not None:
    mode = "manual"
    target = float(max(0, min(180, angle)))
  speed = picolab.query_int(req, "speed")
  if speed is not None:
    SPEED_DPS = max(10, min(2000, speed))
    picolab.log("Web set speed:", SPEED_DPS, "deg/s")
  if b"mode=manual" in req:
    mode = "manual"
    picolab.log("Mode: manual")
  elif b"mode=sweep" in req:
    mode = "sweep"
    picolab.log("Mode: sweep")
  elif b"mode=auto" in req:
    mode = "auto"
    picolab.log("Mode: auto (follow light on GP28)")
  return {"angle": int(target), "mode": mode, "speed": int(SPEED_DPS)}


def data_fn():
  d = {
      "ok": True,
      "ssid": app.ssid,
      "angle": int(current),
      "target": int(target),
      "mode": mode,
      "speed": int(SPEED_DPS),
  }
  if mode == "auto":
    d["light_pct"] = round(light_pct, 1)
  return d


display = picolab.Display()
light = picolab.StatusLight()
light.set_slots([True])
app = picolab.WebApp()
app.index = "servo/index.html"  # dashboard path under the everything layout
heartbeat = picolab.Throttle(5000)

app.announce("Servo Station Active!")
picolab.log("Servo ready at 90 degrees, mode:", mode)
last_motion = time.ticks_ms()

while True:
  light.poll()
  light_pct = ldr.read_u16() / 65535 * 100

  if mode == "auto":
    target = max(0.0, min(180.0, light_pct * 1.8))
  elif mode == "sweep" and current == target:
    target = 0.0 if target >= 180.0 else 180.0

  # Time-based ramp: move by SPEED_DPS * (seconds since last pass), so the
  # real speed matches SPEED_DPS even when the web loop is busy.
  now = time.ticks_ms()
  dt = time.ticks_diff(now, last_motion) / 1000.0
  last_motion = now
  if current < target:
    current = min(target, current + SPEED_DPS * dt)
  elif current > target:
    current = max(target, current - SPEED_DPS * dt)
  write_angle(current)

  # If port 80 never bound (busy after a soft re-run), say so plainly so
  # you know to power-cycle rather than wondering why the page won't load.
  webline = app.ip if app.server else "web off: replug"
  display.show([
      app.ssid,
      webline,
      "mode: " + mode,
      "angle: %3d deg" % int(current),
  ], bar=current / 180.0)

  if heartbeat.ready():
    picolab.log("Servo mode:", mode, "angle:", int(current),
                "target:", int(target))

  app.poll(data_fn, routes=[("/set", set_handler)])
  gc.collect()
