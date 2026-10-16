# DS18B20 soil temperature web demo: waterproof probe temps on the OLED,
# the terminal, and a live web dashboard.
#
# The Pico opens a Wi-Fi network named PicoLab<N>. Join it and browse
# to http://192.168.4.1 (JSON at /data).
#
# Fault tolerant: runs with the probes missing, the display missing, or
# both, and picks either up the moment it is plugged in. No restarts.
# The wire is rescanned every cycle, so newly added probes just appear.
#
# The onboard LED runs POST codes: one blink per probe, in wire order,
# then a pause. Short blink = that probe is OK, long blink = that probe
# is in trouble. With five probes, ". . . _ ." means probe 4 has a
# problem. Plug in a sixth probe mid-run and the pattern grows to six
# blinks. No blinking at all means the code is not running.
#
# Wiring: red=3V3, black=GND, green (data)=GP22, and a REQUIRED 4.7k
# ohm resistor from GP22 to 3V3 (the pullup). Several probes can share
# the same three wires; the demo reads them all. Bus capacity: 10-15
# probes are easy on 4.7k; a 27-probe 3x3x3 bin wants a 2.2k-3.3k
# pullup and daisy-chain wiring; past ~50, split onto a second GPIO.
#
# Probes can be LABELED and POSITIONED (x,y,z in the bin; linear works
# too, just use x). The mapping is keyed by each probe's factory-burned
# ROM serial, so it survives rewiring: put a sticky label on the wire,
# pinch the probe, and the dashboard shows which serial warms up. Saved
# in placements.json on the board (dashboard edits it, or edit it by
# hand in Viper to match the tape).
#
# On the board: main.py, index.html, lib/picolab.py, lib/ssd1306.py.
# (onewire and ds18x20 are built into MicroPython.)
#
# Project page (docs, wiring, install link): https://github.com/MakerLabKids/wormhole/tree/main/projects/soil-temperature

import gc
import time

from machine import Pin

import picolab

# ===== CONFIG =====
# The one-wire data pin every DS18B20 probe shares (default GP22,
# physical pin 29). Remember the 4.7k pullup from this pin to 3V3.
PROBE_PIN = 22
# ==================

sensor = None


def connect():
  import onewire
  import ds18x20

  ow = onewire.OneWire(Pin(PROBE_PIN))
  ds = ds18x20.DS18X20(ow)
  roms = ds.scan()
  if not roms:
    raise OSError("no DS18B20 found on GP22")
  # First conversion is blocking once, so the first reading is real.
  ds.convert_temp()
  time.sleep_ms(750)
  return {"ds": ds, "roms": roms, "due": time.ticks_ms(), "temps": None}


def read(dev):
  # DS18B20 needs 750ms between convert and read. Instead of blocking
  # the loop, read the finished conversion and start the next one.
  # Each probe is read separately so ONE bad probe cannot take down the
  # rest: its temp goes None and its truth-light slot goes long-blink.
  now = time.ticks_ms()
  if time.ticks_diff(now, dev["due"]) >= 0:
    roms_read = dev["roms"]
    ids_read = [bytes(r).hex() for r in roms_read]
    raws = []
    for rom in roms_read:
      try:
        raws.append(round(dev["ds"].read_temp(rom), 2))
      except Exception:
        raws.append(None)
    if roms_read and all(t is None for t in raws):
      raise OSError("all probes lost")
    # calibration applied at the source: OLED, JSON, dashboard agree
    temps = [cal.apply(pid, t) for pid, t in zip(ids_read, raws)]
    # Rescan the wire so probes added mid-run join in (the blink
    # pattern grows by one) and unplugged ones drop off.
    try:
      roms = dev["ds"].scan()
      if roms:
        dev["roms"] = roms
    except Exception:
      pass
    dev["ds"].convert_temp()
    dev["due"] = time.ticks_add(now, 750)
    dev["temps"] = temps
    dev["raws"] = raws
    dev["ids"] = ids_read
  temps = dev["temps"] or []
  good = [t for t in temps if t is not None]
  return {
      "count": len(good),
      "probes": len(temps),
      "ok_flags": [t is not None for t in temps],
      "temps_c": temps,
      "raw_c": dev.get("raws", []),
      "ids": dev.get("ids", []),
      "temp_c": good[0] if good else None,
  }


def data_fn():
  d = {"ok": sensor.ok, "ssid": app.ssid}
  if sensor.data:
    d.update(sensor.data)
    info = []
    ids = sensor.data.get("ids", [])
    raws = sensor.data.get("raw_c", [])
    for i, (pid, t) in enumerate(zip(ids, sensor.data.get("temps_c", []))):
      label, pos = places.get(pid)
      info.append({"id": pid, "label": label, "pos": pos, "t": t,
                   "raw": raws[i] if i < len(raws) else None,
                   "cal": pid in cal.data})
    d["probes_info"] = info
    d["cal_ids"] = list(cal.data)
  return d


places = picolab.Placements()
cal = picolab.Calibration()
sensor = picolab.Sensor("DS18B20", connect, read)
display = picolab.Display()
light = picolab.StatusLight()
app = picolab.WebApp()
app.index = "soil-temperature/index.html"  # dashboard path under the everything layout
tick = picolab.Throttle(250)
heartbeat = picolab.Throttle(5000)

app.announce("Soil Temperature Station Active!")

while True:
  light.poll()
  app.poll(data_fn, routes=[("/place", places.handle), ("/cal", cal.handle)])
  if not tick.ready():
    continue

  data = sensor.poll()
  if data and data["probes"] > 0:
    picolab.status(light, data["ok_flags"], display, app)
  else:
    picolab.status(light, [sensor.ok], display, app)

  if data and data["probes"] > 0:
    lines = [app.ssid, "probes: %d/%d" % (data["count"], data["probes"])]
    for idx, t in enumerate(data["temps_c"][:3]):
      lines.append("%d: %s" % (idx + 1, "fault!" if t is None else "%5.1f C" % t))
    display.show(lines)
  else:
    display.show([
        app.ssid,
        app.ip,
        "no probes...",
        "4.7k pullup?",
    ])

  if heartbeat.ready():
    picolab.log("DS18B20" if sensor.ok else "DS18B20 (unplugged)", data)

  gc.collect()
