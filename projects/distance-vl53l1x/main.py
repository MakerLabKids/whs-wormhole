# VL53L1X long-range distance web demo: up to ~4 meters on the OLED,
# the terminal, and a live web dashboard.
#
# The Pico opens a Wi-Fi network named PicoLab<N>. Join it and browse
# to http://192.168.4.1 (JSON at /data).
#
# Fault tolerant: runs with the sensor missing, the display missing, or
# both, and picks either up the moment it is plugged in. No restarts.
#
# The onboard LED is the truth light: a short blink every cycle means the
# sensor is happy, a long blink means it is missing or misbehaving, and
# no blinking at all means the code is not running.
#
# NOTE: the VL53L1X uses I2C address 0x29, the SAME address as the
# VL53L0X. Only one of the two can be on the bus at a time.
#
# On the board: main.py, index.html, lib/picolab.py, lib/vl53l1x.py,
# lib/ssd1306.py.
#
# Project page (docs, wiring, install link): https://github.com/MakerLabKids/whs-wormhole/tree/main/projects/distance-vl53l1x

import gc

import picolab

sensor = None


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


def data_fn():
  d = {"ok": sensor.ok, "ssid": app.ssid}
  if sensor.data:
    d.update(sensor.data)
  return d


sensor = picolab.Sensor("VL53L1X", connect, read)
display = picolab.Display()
light = picolab.StatusLight()
app = picolab.WebApp()
app.index = "distance-vl53l1x/index.html"  # dashboard path under the everything layout
tick = picolab.Throttle(250)
heartbeat = picolab.Throttle(5000)

app.announce("VL53L1X Long-Range Station Active!")

while True:
  light.poll()
  app.poll(data_fn)
  if not tick.ready():
    continue

  data = sensor.poll()
  picolab.status(light, [sensor.ok], display, app)

  if data and data["valid"]:
    display.show([
        app.ssid,
        "%4d mm" % data["dist_mm"],
        "%5.2f m" % (data["dist_mm"] / 1000.0),
    ], bar=min(1.0, data["dist_mm"] / 4000.0))
  elif data:
    display.show([
        app.ssid,
        app.ip,
        "no target...",
        "(0.04 - 4 m)",
    ])
  else:
    display.show([
        app.ssid,
        app.ip,
        "no sensor...",
        "hot-plug ready",
    ])

  if heartbeat.ready():
    picolab.log("VL53L1X" if sensor.ok else "VL53L1X (unplugged)", data)

  gc.collect()
