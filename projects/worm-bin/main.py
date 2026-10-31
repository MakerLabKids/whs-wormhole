# WORM BIN COMMAND CENTER: every sensor in the toolbox, and the
# actuators, running off ONE Pico at the same time.
#
#   2x BME280 (0x76 inside the bin, 0x77 outside)
#   DS18B20 waterproof probes on GP22 (as many as you own, one wire)
#   ADS1115 analog bank at 0x48: A0 + A1 soil moisture
#   GL5528 photoresistor divider on GP28 (native ADC), BH1750 lux at 0x23
#   MAX9814 mic on GP27 (native ADC: it needs the fast sampling)
#   VL53L0X time-of-flight at 0x29 (SOIL COMPACTION: distance from the
#     lid down to the bedding surface. As worms process and the bedding
#     settles, that gap grows; a sudden change flags a disturbance)
#   Big servo GP16, small servo GP17, relay GP15
#   OLED 0x3C: ONE screen built from whatever is reporting (pages only
#     if that overflows)
#
# The Pico opens a Wi-Fi network named PicoLab<N>. Join it and browse
# to http://192.168.4.1 (JSON at /data, actuators at /set).
#
# Everything is optional and hot-pluggable. The truth light runs POST
# codes, one blink per part IN THE ORDER OF THE PARTS LIST BELOW, then
# one slot per DS18B20 probe (always last, so adding a probe grows the
# tail of the pattern without renumbering anything). Short blink = OK,
# long blink = trouble, dark = code not running. Comment out the line of
# any part your bin does not have and its slot disappears.
#
# On the board: main.py, index.html, and from lib/: picolab.py,
# ssd1306.py, bme280.py, ads1115.py, vl53l0x.py, bh1750.py.
#
# Project page (docs, wiring, install link): https://github.com/MakerLabKids/whs-wormhole/tree/main/projects/worm-bin

import gc
import time

from machine import ADC, PWM, Pin

import picolab

# ===== CONFIG: the knobs worth turning ================================
# Change a value, save, restart. Everything below the line is machinery.

# Soil moisture calibration, in VOLTS (the ADS1115 reads volts, not
# Pico counts). To calibrate YOURS: watch moist1_v on the dashboard
# with the probe dry in air (that is DRY), then in a cup of water up to
# the marked line (that is WET). Defaults suit the capacitive v1.2.
MOIST_DRY_V = 2.22   # default 2.22 V
MOIST_WET_V = 0.91   # default 0.91 V

# Where things plug in. These are GP numbers, NOT physical pin numbers
# (GP22 is physical pin 29; the wiring diagrams show both).
PROBE_PIN = 22        # DS18B20 one-wire bus + its 4.7k pullup (default GP22)
# The two parts on bare Pico ADC pins cannot tell "unplugged" from "quiet"
# or "dark", so they always report. If your bin does not have one, set its
# pin to None: it leaves the parts list, the truth light, and the screen.
MOIST_PIN = None      # capacitive probe AOUT straight into a Pico ADC pin (26, 27 or 28)
                      # instead of the ADS1115 bank; None = no direct probe
MIC_PIN = 27          # MAX9814 mic; native ADC pin (default GP27), None = not fitted
LIGHT_PIN = 28        # GL5528 photoresistor divider; native ADC pin (default GP28), None = not fitted
SERVO_BIG_PIN = 16    # MG995; own 5V supply, grounds joined (default GP16)
SERVO_SMALL_PIN = 17  # SG90; VBUS power is fine (default GP17)
RELAY_PIN = 15        # relay module IN (default GP15)

# How fast the servos slew to a commanded angle, in degrees per second.
# Motion is ramped and TIME-BASED (not an instant snap) so it looks smooth
# and does not yank current, and the number is the real speed regardless
# of loop load. Raise for snappier, lower for slow-motion. (Matches the
# standalone servo demo.)
SERVO_DPS = 400

# Height of the bin above sea level, in metres. A BME280 measures the actual
# air pressure where it sits (station pressure), which is a few percent
# lower than the sea-level pressure weather reports quote. With the
# elevation known, press_hpa is corrected to sea level so it matches the
# weather app; press_raw_hpa stays the real reading. 0 = no correction.
# Woodstock High School is about 305 m (1000 ft); Roswell about 330 m.
ELEVATION_M = 305

# Timing.
READ_EVERY_MS = 500   # sensor sweep cadence (default 500 ms)
# The OLED shows one row per part that is reporting; parts that are absent
# take no space. Only if there are more rows than fit (6 under the title)
# does it page, and then the dwell adapts to what is ON the page, so you
# have time to shine a light on a sensor and watch it react.
PAGE_SEC_LIGHT = 10   # a page with a light sensor (shine a light, watch it move)
PAGE_SEC_SENSOR = 5   # any other page
# The title row: the team name holds for 5 s, then this line scrolls
# through, then the name holds again. "" turns the marquee off. A name too
# long for the screen scrolls instead of holding; it still gets its 5 s.
MARQUEE = "Woodstock High School and Maker Lab Kids - Vermiculture PBL by:"
# ===== end of config ==================================================


def sea_level(station_hpa):
  """Station pressure -> sea-level pressure for ELEVATION_M (standard
  atmosphere, the same formula weather stations use)."""
  if not ELEVATION_M:
    return station_hpa
  return station_hpa / (1.0 - 2.25577e-5 * ELEVATION_M) ** 5.25588


def bme(name, addr):
  def connect():
    from bme280 import BME280
    return BME280(picolab.i2c(), address=addr)

  def read(dev):
    temp_c, press_hpa, hum_pct = dev.read()
    return {
        name + "_temp_c": round(temp_c, 1),
        name + "_press_hpa": round(sea_level(press_hpa), 1),
        name + "_press_raw_hpa": round(press_hpa, 1),
        name + "_hum_pct": None if hum_pct is None else round(hum_pct, 1),
    }

  return picolab.Sensor("BME280 %s (0x%02x)" % (name, addr), connect, read)


# Calibration uses the SHARED engine (picolab.Calibration, the same one
# soil-temperature uses), saved in cal.json and driven by the shared
# /cal route + cal.js widget. Moisture probes calibrate two-point: dry
# probe in air = 0%, wet probe in water = 100%. Until a probe is
# calibrated, the default dry/wet volts from the CONFIG block are used.
cal = picolab.Calibration()


def _moist_pct(pid, v):
  if pid in cal.data:                      # calibrated: engine maps volts -> %
    return max(0.0, min(100.0, cal.apply(pid, v, digits=1)))
  if MOIST_DRY_V == MOIST_WET_V:           # default two-point mapping
    return 0.0
  return round(max(0.0, min(100.0, (MOIST_DRY_V - v) * 100.0 / (MOIST_DRY_V - MOIST_WET_V))), 1)


def analog_bank():
  """ADS1115: two soil-moisture probes, one part. (Light moved to the
  Pico's own GP28 ADC, see photoresistor(), so it works with no ADS1115.)"""

  def connect():
    from ads1115 import ADS1115
    return ADS1115(picolab.i2c())

  def read(dev):
    m1 = dev.read_volts(0)
    m2 = dev.read_volts(1)
    return {
        "moist1_pct": _moist_pct("moist1", m1), "moist1_v": round(m1, 2),
        "moist2_pct": _moist_pct("moist2", m2), "moist2_v": round(m2, 2),
    }

  return picolab.Sensor("ADS1115 bank (0x48)", connect, read)


def soil_probe():
  """One capacitive moisture probe on a bare Pico ADC pin (MOIST_PIN), for a
  bin without the ADS1115 bank. Reports as moist1, same keys and same
  calibration as bank channel A0, so the screen, the dashboard and /cal do
  not care which way it is wired. An ADC pin cannot tell 'unplugged' from
  'dry', so this slot mostly proves it is sampling."""
  if MOIST_PIN is None:
    return None

  def connect():
    return ADC(MOIST_PIN)

  def read(dev):
    total = 0
    for _ in range(16):
      total += dev.read_u16()
    v = total / 16 / 65535 * 3.3
    return {"moist1_pct": _moist_pct("moist1", v), "moist1_v": round(v, 2)}

  return picolab.Sensor("moisture probe (GP%d)" % MOIST_PIN, connect, read)


def photoresistor():
  """GL5528 photoresistor divider on GP28 (Pico ADC): 3V3 - LDR - GP28 -
  10k - GND, the GP28 node rises with light. Same pin the light-basic
  project uses, and no ADS1115 needed. Like the mic, an ADC pin cannot
  tell 'unplugged' from 'dark', so this slot mostly proves it is sampling.
  LIGHT_PIN = None means the bin has no light sensor: no part at all."""
  if LIGHT_PIN is None:
    return None

  def connect():
    return ADC(LIGHT_PIN)

  def read(dev):
    return {"light_pct": round(dev.read_u16() / 65535 * 100, 1)}

  return picolab.Sensor("GL5528 light (GP28)", connect, read)


def microphone():
  """MAX9814 on GP27. An ADC pin cannot detect an unplugged mic, so
  this slot mostly proves the code is sampling. MIC_PIN = None: no mic."""
  if MIC_PIN is None:
    return None

  def connect():
    return ADC(MIC_PIN)

  def read(dev):
    lo, hi = 65535, 0
    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < 25:
      v = dev.read_u16()
      if v < lo:
        lo = v
      if v > hi:
        hi = v
    return {"sound_pct": round((hi - lo) / 65535 * 100, 1)}

  return picolab.Sensor("MAX9814 mic (GP27)", connect, read)


def compaction():
  # Time-of-flight aimed down from the lid at the bedding surface. The
  # reading is the gap to the surface in mm; watch it grow as bedding
  # settles and compacts, or jump when someone digs in the bin.
  def connect():
    from vl53l0x import VL53L0X
    tof = VL53L0X(picolab.i2c())
    tof.init_sensor()
    tof.ping()   # the first shot after init reads 0; throw it away
    return tof

  def read(dev):
    raw = dev.ping()
    # 0 mm is not a distance: the chip never finished a measurement (a
    # module whose power sags when the laser fires does exactly this).
    # Fault the part so the truth light and the screen say so, and the
    # Sensor wrapper re-initialises it on the next retry. 8190+ is the
    # chip's own "no target in range" code.
    if raw == 0 or raw >= 8190:
      raise OSError("VL53L0X no measurement (%d)" % raw)
    # Calibrated two-point (put a target at a measured distance, enter
    # it, capture near + far) via the shared engine; else the raw mm.
    surf = round(cal.apply("distance", raw, digits=0)) if "distance" in cal.data else raw
    return {"surface_mm": surf, "surface_raw_mm": raw}

  return picolab.Sensor("VL53L0X compaction (0x29)", connect, read)


def lux_meter():
  """BH1750 (GY-302) on the shared I2C bus at 0x23: light in real lux, the
  precise reading next to the photoresistor's rough percent. Both are
  optional and hot-pluggable like everything else."""

  def connect():
    from bh1750 import BH1750
    return BH1750(picolab.i2c())

  def read(dev):
    return {"lux": round(dev.read(), 1)}

  return picolab.Sensor("BH1750 lux (0x23)", connect, read)


def probe_bus():
  """DS18B20 array on GP22, same live-rescan engine as soil-temperature:
  one bad probe faults alone, added probes appear by themselves."""

  def connect():
    import onewire
    import ds18x20

    ds = ds18x20.DS18X20(onewire.OneWire(Pin(PROBE_PIN)))
    roms = ds.scan()
    if not roms:
      raise OSError("no DS18B20 found on GP22")
    ds.convert_temp()
    time.sleep_ms(750)
    return {"ds": ds, "roms": roms, "due": time.ticks_ms(), "temps": None}

  def read(dev):
    now = time.ticks_ms()
    if time.ticks_diff(now, dev["due"]) >= 0:
      temps = []
      for rom in dev["roms"]:
        try:
          temps.append(round(dev["ds"].read_temp(rom), 1))
        except Exception:
          temps.append(None)
      if dev["roms"] and all(t is None for t in temps):
        raise OSError("all probes lost")
      try:
        roms = dev["ds"].scan()
        if roms:
          dev["roms"] = roms
      except Exception:
        pass
      dev["ds"].convert_temp()
      dev["due"] = time.ticks_add(now, 750)
      dev["temps"] = temps
    temps = dev["temps"] or []
    good = [t for t in temps if t is not None]
    return {
        "probes": len(temps),
        "probe_count": len(good),
        "probe_ok": [t is not None for t in temps],
        "probe_temps_c": temps,
    }

  return picolab.Sensor("DS18B20 bus (GP22)", connect, read)


# ---------------------------------------------------------------------
# THE PARTS LIST. Slot order on the truth light = this order, then one
# slot per DS18B20 probe. Comment out what your bin does not have.
# ---------------------------------------------------------------------
PARTS = [p for p in (
    bme("in", 0x76),
    bme("out", 0x77),
    analog_bank(),
    soil_probe(),       # None (no slot) when MOIST_PIN is None
    microphone(),       # None (no slot) when MIC_PIN is None
    photoresistor(),    # None (no slot) when LIGHT_PIN is None
    compaction(),
    lux_meter(),
) if p is not None]
DS = probe_bus()   # dynamic slots, always last


# ---- actuators ------------------------------------------------------
class Servo:
  def __init__(self, pin_num, min_us=600, max_us=2400):
    self.pwm = PWM(Pin(pin_num))
    self.pwm.freq(50)
    self.angle = 90.0     # where it is now
    self.target = 90.0    # where it is headed
    self.min_us = min_us
    self.max_us = max_us
    self._last = time.ticks_ms()
    self._write(self.angle)

  def _write(self, angle):
    us = self.min_us + (angle / 180.0) * (self.max_us - self.min_us)
    self.pwm.duty_u16(int(us * 65535 / 20000))

  def set(self, angle):
    # Aim for a new angle; step() ramps toward it (no instant snap).
    self.target = max(0.0, min(180.0, float(angle)))

  def step(self):
    # Move toward the target at SERVO_DPS. Time-based, so it is smooth
    # no matter how often the loop calls it. Call this every loop pass.
    now = time.ticks_ms()
    dt = time.ticks_diff(now, self._last) / 1000.0
    self._last = now
    if self.angle == self.target:
      return
    move = SERVO_DPS * dt
    if self.angle < self.target:
      self.angle = min(self.target, self.angle + move)
    else:
      self.angle = max(self.target, self.angle - move)
    self._write(self.angle)


servo_big = Servo(SERVO_BIG_PIN)     # MG995: its own 5V supply, grounds joined!
servo_small = Servo(SERVO_SMALL_PIN)   # SG90: VBUS is fine
relay = Pin(RELAY_PIN, Pin.OUT)
relay.value(0)


def set_handler(req):
  a = picolab.query_int(req, "big")
  if a is not None:
    servo_big.set(a)
    picolab.log("Web: big servo ->", int(servo_big.target))
  a = picolab.query_int(req, "small")
  if a is not None:
    servo_small.set(a)
    picolab.log("Web: small servo ->", int(servo_small.target))
  a = picolab.query_int(req, "relay")
  if a is not None:
    relay.value(1 if a else 0)
    picolab.log("Web: relay ->", relay.value())
  return {"big": int(servo_big.angle), "small": int(servo_small.angle),
          "relay": relay.value()}


def data_fn():
  d = {"ok": True, "ssid": app.ssid}
  status = []
  for s in PARTS:
    status.append({"name": s.name, "ok": s.ok})
    if s.data:
      d.update(s.data)
  status.append({"name": DS.name, "ok": DS.ok})
  if DS.data:
    d.update(DS.data)
  d["parts"] = status
  d["big"] = int(servo_big.angle)
  d["small"] = int(servo_small.angle)
  d["relay"] = relay.value()
  d["cal_ids"] = list(cal.data)
  return d


# ---- OLED: one screen built from what is REPORTING --------------------
# Every part with data contributes a row (16 characters, LABEL: value); an
# absent part contributes nothing. Up to 6 rows fit under the title on one
# screen (the display stacks them up from the bottom edge, under the
# underlined title, and tightens the pitch past 5), so a lean bin just sits
# there, readable, and a crowded bin pages, through rows that exist. Rows are in
# priority order; the actuator row only appears once something has been
# commanded, because an idle servo is not data.
ROWS_PER_SCREEN = 6


def fmt(val, pattern="%s"):
  return "--" if val is None else pattern % val


def screen_rows(d):
  """[(text, kind)] for everything that is reporting right now. kind is
  'light' for rows worth lingering on when paging, else 'sensor'."""
  rows = []
  ti, to = d.get("in_temp_c"), d.get("out_temp_c")
  hi, ho = d.get("in_hum_pct"), d.get("out_hum_pct")
  if ti is not None and to is not None:
    rows.append(("IN: %s %s" % (fmt(ti, "%.1fC"), fmt(hi, "%.0f%%")), "sensor"))
    rows.append(("OUT: %s %s" % (fmt(to, "%.1fC"), fmt(ho, "%.0f%%")), "sensor"))
    rows.append(("DT: %+.1fC" % (ti - to), "sensor"))
  elif ti is not None or to is not None:
    which = "in" if ti is not None else "out"
    rows.append(("AIR: %s %s" % (fmt(d.get(which + "_temp_c"), "%.1fC"),
                                fmt(d.get(which + "_hum_pct"), "%.0f%%")), "sensor"))
    rows.append(("PRESS: %s" % fmt(d.get(which + "_press_hpa"), "%.0f hPa"), "sensor"))
  temps = d.get("probe_temps_c") or []
  if len(temps) == 1:
    rows.append(("SOIL: %s" % ("fault!" if temps[0] is None else "%.1fC" % temps[0]), "sensor"))
  elif temps:
    rows.append(("SOIL: " + " ".join("--" if t is None else "%.1f" % t for t in temps[:2])
                 + ("+" if len(temps) > 2 else ""), "sensor"))   # trailing + = more probes
  if d.get("moist1_pct") is not None:
    if d.get("moist2_pct") is None:
      rows.append(("MOIST: %s" % fmt(d["moist1_pct"], "%.0f%%"), "sensor"))
    else:
      rows.append(("MOIST: %s %s" % (fmt(d["moist1_pct"], "%.0f%%"),
                                    fmt(d["moist2_pct"], "%.0f%%")), "sensor"))
  if d.get("light_pct") is not None or d.get("lux") is not None:
    lux = d.get("lux")
    lux_s = None if lux is None else ("%.0fk" % (lux / 1000) if lux >= 10000 else
                                      "%.1fk" % (lux / 1000) if lux >= 1000 else "%.0flx" % lux)
    if lux_s is not None and d.get("light_pct") is not None:
      row = "LIGHT: %s %s" % (fmt(d["light_pct"], "%.0f%%"), lux_s)
      rows.append((row if len(row) <= 16 else row.replace("lx", ""), "light"))   # 100% 999lx
    elif lux_s is not None:
      rows.append(("LIGHT: %s" % lux_s, "light"))
    else:
      rows.append(("LIGHT: %s" % fmt(d["light_pct"], "%.0f%%"), "light"))
  if d.get("sound_pct") is not None:
    rows.append(("SOUND: %s" % fmt(d["sound_pct"], "%.0f%%"), "sensor"))
  if d.get("surface_mm") is not None:
    rows.append(("DIST: %s" % fmt(d["surface_mm"], "%d mm"), "sensor"))
  big, small, rly = d.get("big", 90), d.get("small", 90), d.get("relay", 0)
  if rly or big != 90 or small != 90:
    rows.append(("SRV: %d/%d%s" % (big, small, " RLY" if rly else ""), "sensor"))   # RLY = relay on
  if not rows:
    rows.append(("no parts found", "sensor"))
    rows.append(("check wiring", "sensor"))
  return rows


def screen_pages(rows):
  """Split rows into screens of ROWS_PER_SCREEN. One screen = no paging."""
  return [rows[i:i + ROWS_PER_SCREEN] for i in range(0, len(rows), ROWS_PER_SCREEN)] or [[]]


def screen_dwell(page_rows):
  return PAGE_SEC_LIGHT if any(k == "light" for _, k in page_rows) else PAGE_SEC_SENSOR


picolab.banner("WORM BIN COMMAND CENTER  v" + picolab.VERSION, [
    "Parts: " + ", ".join(s.name for s in PARTS),
    "Plus: " + DS.name + " (slots at the end)",
    "LED POST: short=OK long=trouble",
])

display = picolab.Display()
display.marquee = MARQUEE
# The capstone gets a proper opening card (the little demos stay fast).
display.show([
    "   WOODSTOCK",
    "  HIGH SCHOOL",
    " Maker Lab Kids",
    "",
    " Wormhole v" + picolab.VERSION,
], title=False)
time.sleep_ms(3000)

light = picolab.StatusLight()
app = picolab.WebApp()
tick = picolab.Throttle(READ_EVERY_MS)
heartbeat = picolab.Throttle(5000)
page = 0                         # OLED page (only moves when rows overflow a screen)
page_deadline = time.ticks_ms()

app.announce("Worm Bin Command Center Active!")

# The main loop is wrapped so that however it ends -- a clean stop, an
# unhandled error, or the KeyboardInterrupt a Viper/Thonny "Stop" raises --
# the web socket is closed on the way out and port 80 is free for the next
# run. (A hard reset or brownout skips the finally, but that frees the port
# by itself.) This is what stops the "address already in use" headache.
try:
  while True:
    light.poll()
    app.poll(data_fn, routes=[("/set", set_handler), ("/cal", cal.handle)])
    servo_big.step()      # ramp the servos toward their targets every pass
    servo_small.step()
    display.tick()        # the title marquee, between sensor sweeps
    if not tick.ready():
      continue

    for s in PARTS:
      s.poll()
    DS.poll()

    slots = [s.ok for s in PARTS]
    dsd = DS.data
    if dsd and dsd.get("probes"):
      slots.extend(dsd["probe_ok"])
    else:
      slots.append(DS.ok)
    picolab.status(light, slots, display, app)

    d = data_fn()
    # One screen if everything reporting fits; otherwise page through what
    # exists, advancing only when the current page's dwell has elapsed.
    pages = screen_pages(screen_rows(d))
    now = time.ticks_ms()
    if page >= len(pages):
      page = 0
    if len(pages) > 1 and time.ticks_diff(now, page_deadline) >= 0:
      page = (page + 1) % len(pages)
      page_deadline = time.ticks_add(now, screen_dwell(pages[page]) * 1000)
    title = app.ssid if len(pages) == 1 else app.ssid + " %d/%d" % (page + 1, len(pages))
    lines = [title] + [text for text, _ in pages[page]]
    display.show(lines)

    if heartbeat.ready():
      bad = [s.name for s in PARTS if not s.ok] + ([] if DS.ok else [DS.name])
      picolab.log("all parts OK" if not bad else "TROUBLE: " + ", ".join(bad))
      picolab.log("screen %d/%d:" % (page + 1, len(pages)), " | ".join(lines))

    gc.collect()
finally:
  app.close()      # release port 80 on ANY exit (clean, error, or Stop)
