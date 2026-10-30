# VL53L1X long-range distance bench demo: up to ~4 meters on the OLED
# and terminal. No Wi-Fi. This is the big sibling of the VL53L0X; same
# idea, four times the reach.
#
# Fault tolerant: runs with the sensor missing, the display missing, or
# both, and picks either up the moment it is plugged in. No restarts.
#
# The onboard LED is the truth light: a short blink every cycle means the
# sensor is happy, a long blink means it is missing or misbehaving, and
# no blinking at all means the code is not running.
#
# Wiring (shared I2C bus): VIN=3V3, GND=GND, SDA=GP0, SCL=GP1.
# NOTE: the VL53L1X uses I2C address 0x29, the SAME address as the
# VL53L0X. Only one of the two can be on the bus at a time.
#
# On the board: this file, lib/picolab.py, lib/vl53l1x.py,
# lib/ssd1306.py.

import gc
import time

import picolab

picolab.banner("VL53L1X Bench Demo", [
    "Wiring: I2C0 SDA=GP0 SCL=GP1",
    "VL53L1X at 0x29 (not with a VL53L0X!)",
    "OLED at 0x3C, both optional",
])


# Field of view: 16 = the full ~27 degree cone (longest reach, ~4 m),
# 8 = ~20 degrees, 4 = ~15 degrees (ignores the desk, a lamp beside the
# target, or the person watching, but reaches ~1.5 m). See lib/vl53l1x.py.
ROI = 8
# Per-module calibration, both 0 = factory. See README "Calibration".
# OFFSET first (mm, wall at 100 mm), then XTALK (kcps, wall at ~1 m, same ROI).
# Uncalibrated, one module read 83 mm at 100 mm and 900 mm at 1120 mm.
OFFSET = 0
XTALK = 0


def connect():
  from vl53l1x import VL53L1X
  return VL53L1X(picolab.i2c(), roi=ROI, xtalk=XTALK, offset=OFFSET)


def read(dev):
  mm, valid = dev.read()
  return {
      "dist_mm": mm if valid else None,
      "valid": valid,
  }


sensor = picolab.Sensor("VL53L1X", connect, read)
display = picolab.Display()
light = picolab.StatusLight()
tick = picolab.Throttle(250)
heartbeat = picolab.Throttle(5000)

while True:
  if not tick.ready():
    light.poll()
    time.sleep_ms(20)
    continue

  data = sensor.poll()
  light.set_slots([sensor.ok])

  if data and data["valid"]:
    display.show([
        "VL53L1X  live",
        "%4d mm" % data["dist_mm"],
        "%5.2f m" % (data["dist_mm"] / 1000.0),
    ], bar=min(1.0, data["dist_mm"] / 4000.0))
  elif data:
    display.show([
        "VL53L1X  live",
        "no target...",
        "(0.04 - 4 m)",
    ])
  else:
    display.show([
        "VL53L1X",
        "no sensor...",
        "check SDA=GP0",
        "      SCL=GP1",
    ])

  if heartbeat.ready():
    picolab.log("VL53L1X" if sensor.ok else "VL53L1X (unplugged)", data)

  light.poll()
  gc.collect()
