# Capacitive soil moisture web demo: moisture percent on the OLED, the
# terminal, and a live web dashboard.
#
# The Pico opens a Wi-Fi network named PicoLab<N>. Join it and browse
# to http://192.168.4.1 (JSON at /data).
#
# NOTE: an analog pin cannot tell if the sensor is unplugged. With
# nothing on GP26 the pin floats and the numbers are noise. The I2C
# demos can detect a missing part; analog demos cannot. So here the
# truth light (the onboard LED, short blink every cycle) mostly proves
# the CODE is running; no blinking at all means it is not.
#
# Wiring: VCC=3V3, GND=GND, AOUT=GP26 (ADC0).
# On the board: main.py, index.html, lib/picolab.py, lib/ssd1306.py.
#
# Project page (docs, wiring, install link): https://github.com/MakerLabKids/whs-wormhole/tree/main/projects/soil-moisture

import gc

from machine import ADC

import picolab

# Calibration (typical values at 3V3). To calibrate YOUR sensor:
# watch the raw value with the probe dry in air (that is DRY_RAW),
# then in a cup of water up to the marked line (that is WET_RAW),
# and edit these two numbers.
DRY_RAW = 44000
WET_RAW = 18000

# The analog pin the sensor AOUT uses (default GP26 = ADC0, physical
# pin 31). Native ADC pins only: GP26, GP27, GP28.
SENSOR_PIN = 26

sensor = None


def connect():
  return ADC(SENSOR_PIN)


def read(dev):
  total = 0
  for _ in range(16):
    total += dev.read_u16()
  raw = total // 16
  pct = (DRY_RAW - raw) * 100.0 / (DRY_RAW - WET_RAW)
  pct = max(0.0, min(100.0, pct))
  return {"moisture_pct": round(pct, 1), "raw": raw}


def data_fn():
  d = {"ok": sensor.ok, "ssid": app.ssid}
  if sensor.data:
    d.update(sensor.data)
  return d


sensor = picolab.Sensor("Soil moisture", connect, read)
display = picolab.Display()
light = picolab.StatusLight()
app = picolab.WebApp()
app.index = "soil-moisture/index.html"  # dashboard path under the everything layout
tick = picolab.Throttle(250)
heartbeat = picolab.Throttle(5000)

app.announce("Soil Moisture Station Active!")

while True:
  light.poll()
  app.poll(data_fn)
  if not tick.ready():
    continue

  data = sensor.poll()
  picolab.status(light, [sensor.ok], display, app)

  if data:
    display.show([
        app.ssid,
        "Soil: %5.1f %%" % data["moisture_pct"],
        "raw: %5d" % data["raw"],
    ], bar=data["moisture_pct"] / 100.0)
  else:
    display.show([
        app.ssid,
        app.ip,
        "starting...",
    ])

  if heartbeat.ready():
    picolab.log("Soil", data)

  gc.collect()
