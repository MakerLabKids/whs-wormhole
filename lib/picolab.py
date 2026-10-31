# picolab.py - shared plumbing for Maker Lab Kids Pico 2 W demos.
#
# Every demo follows the same rules:
#   * Nothing crashes because a part is missing or flaky.
#   * The OLED is optional. If it is absent (or dies) the demo keeps going
#     and quietly retries it every few seconds.
#   * Sensors are optional AND hot-pluggable: plug one in mid-run and it
#     starts reporting within a couple of seconds, no restart needed.
#   * Terminal logging: a startup banner and first readings immediately,
#     then a slow heartbeat so the terminal stays readable.
#   * The onboard LED is a truth light (StatusLight): if code is running
#     the light is active, and blink codes say which part is unhappy.
#   * Each board has a PERMANENT identity from its hardware serial:
#     name "PicoLab<4hex>" (or name.txt), reported with its IP at /data.
#   * Web demos either JOIN a network (wifi.json, with a rescue ladder)
#     or open their own access point, serving index.html and /data.

import json
import socket
import time
import machine
from machine import I2C, Pin, unique_id

# Version of the SOFTWARE THAT RUNS ON THE PICO (this framework + the project
# programs + drivers). Bump on ANY change to on-Pico code, NOT for changes to
# the repo's docs/JS/website. Scheme:
#   0.1.x  patch: routine change (bumped freely).
#   0.2.0  minor: a SIGNIFICANT change -- ASK THE OWNER before this bump.
#   1.0.0  go-live: after this, no breaking changes.
# Shown by the self-test (header + healthy message + OLED) and the worm-bin
# startup screen, so a board tells you what it runs with no computer attached.
VERSION = "0.2.0"

_i2c = None

# Candidate I2C pin pairs, (controller, SDA, SCL), tried in this order. The
# sensor bank works on ANY of these, so a bin can be wired to whichever pair
# is convenient and it is found automatically. These are exactly the pairs
# that do NOT collide with the worm-bin actuator/analog/1-wire pins:
#   EXCLUDED on purpose: GP16/17 (servos), GP14/15 (relay),
#                        GP26/27 (mic on GP27 + spare ADC GP26).
#   GP22 (1-wire) and GP28 (light ADC) are not usable I2C pairs anyway.
# If you move an actuator, update this list to match.
I2C_CANDIDATES = [
    (0, 0, 1),     # primary
    (0, 20, 21),   # first backup: nearest the 3V3/GND pins, no conflicts
    (0, 4, 5), (0, 8, 9), (0, 12, 13),
    (1, 2, 3), (1, 6, 7), (1, 10, 11), (1, 18, 19),
]


def _open_i2c(controller, sda, scl):
  return I2C(controller, sda=Pin(sda), scl=Pin(scl), freq=400000)


def i2c():
  """The shared I2C bus, AUTO-LOCATED. Scans the candidate pin pairs
  (I2C_CANDIDATES) once and uses the FIRST pair that has a device on it, so
  the sensor bank works whichever clean pair it is plugged into. A bare board
  (no devices on any pair) falls back to GP0/GP1 so hot-plug still works."""
  global _i2c
  if _i2c is not None:
    return _i2c
  for controller, sda, scl in I2C_CANDIDATES:
    try:
      bus = _open_i2c(controller, sda, scl)
      if bus.scan():
        if (sda, scl) != (0, 1):
          log("I2C bus located on GP%d/GP%d (not the default GP0/GP1)." % (sda, scl))
        _i2c = bus
        return _i2c
    except Exception:
      pass
  # Nothing found anywhere: (re)open the primary so a later hot-plug onto
  # GP0/GP1 is picked up by the per-sensor retry loops.
  _i2c = _open_i2c(0, 0, 1)
  return _i2c


_UP = [time.ticks_ms(), 0]   # last ticks sample, accumulated ms (wrap-safe)


def uptime_s():
  """Seconds since boot. ticks_ms() wraps every ~12 days; this accumulates
  across the wrap as long as it is called at least that often (poll() does)."""
  now = time.ticks_ms()
  _UP[1] += time.ticks_diff(now, _UP[0])
  _UP[0] = now
  return _UP[1] // 1000


def _uptime():
  return uptime_s()


def log(*args):
  print("[%4ds]" % _uptime(), *args)


# ---- hardware watchdog ----------------------------------------------
# A wedged board in a worm bin reboots itself; a board on a laptop does not
# fight the person at the keyboard. The RP2 watchdog cannot be disarmed once
# started, so it is only armed when NO USB host is attached (a plain power
# supply never asserts CONNECTED). Every wait in this file that can exceed a
# couple of seconds calls feed(); demo loops feed through WebApp.poll().
WATCHDOG_MS = 8000        # the RP2040/RP2350 hardware maximum is about 8.3 s
_wdt = None


def usb_host_attached():
  """True when a computer is on the USB port (Viper, Thonny, mpremote),
  False on a power-only supply. USB SIE_STATUS bit 16 = CONNECTED."""
  try:
    return bool(machine.mem32[0x50110000 + 0x50] & (1 << 16))
  except Exception:
    return True            # cannot tell: assume a human, stay out of the way


def arm_watchdog(force=False):
  """Start the hardware watchdog unless a USB host is attached (or force)."""
  global _wdt
  if _wdt:
    return True
  if usb_host_attached() and not force:
    log("USB host attached: hardware watchdog left off")
    return False
  try:
    _wdt = machine.WDT(timeout=WATCHDOG_MS)
    log("hardware watchdog armed: a stuck board reboots after %d s" % (WATCHDOG_MS // 1000))
    return True
  except Exception as e:
    log("watchdog unavailable:", e)
    return False


def feed():
  """Pat the watchdog. Cheap; safe to call when it is not armed."""
  if _wdt:
    _wdt.feed()


def banner(title, lines=()):
  print("\n" + "=" * 40)
  print(title)
  for ln in lines:
    print("  " + ln)
  print("=" * 40)


class Throttle:
  """True at most once every interval_ms. First call is True immediately."""

  def __init__(self, interval_ms):
    self.interval = interval_ms
    self._next = time.ticks_ms()

  def ready(self):
    now = time.ticks_ms()
    if time.ticks_diff(now, self._next) >= 0:
      self._next = time.ticks_add(now, self.interval)
      return True
    return False


class StatusLight:
  """The onboard LED as a truth light. Poll it; it never blocks.

  If code is running, the light is doing something. Modes:

    set_ok(bool)    Simplest demos: solid ON means working, OFF means not.
    set_slots(list) POST blinks: one blink per entry, in a fixed order,
                    then a pause, then repeat. Short blink = that part is
                    OK. Long blink = that part is in trouble. So with five
                    probes, ". . . _ ." means probe 4 has a problem.
    set_number(n)   Blink a number 0-999 by place, so a board with NO
                    display can still tell you its address. LONG blinks =
                    hundreds, MEDIUM = tens, SHORT = ones, a zero place is
                    skipped, and the blink SPEED tells you the place so
                    skipping is never ambiguous. 203 = two long, (skip),
                    three short. 42 = four medium, two short. Big pause
                    between repeats. Read the last octet of the IP this
                    way and you can browse straight to the station.

  No blinking at all means the code is not running. Call poll() every
  trip through the main loop (50 ms or faster keeps the blinks crisp).
  """

  SHORT_MS = 110
  MED_MS = 330
  LONG_MS = 640
  GAP_MS = 240          # between blinks within one place
  GROUP_GAP_MS = 780    # between places (hundreds -> tens -> ones)
  PAUSE_MS = 1400       # between repeats of a slot pattern
  NUM_PAUSE_MS = 2600   # longer, so a number's repeat boundary is obvious

  def __init__(self):
    try:
      self.led = Pin("LED", Pin.OUT)
      self.led.off()
    except Exception:
      self.led = None
    self._solid = None
    # A schedule is a list of (on_ms, gap_after_ms) pulses, played in
    # order, then _pause, then repeat. set_slots/set_number build one.
    self._sched = [(self.SHORT_MS, self.GAP_MS)]
    self._pause = self.PAUSE_MS
    self._cycle = None
    self._i = 0
    self._lit = False
    self._until = time.ticks_ms()

  def set_ok(self, ok):
    self._solid = bool(ok)

  def set_slots(self, slots):
    self._solid = None
    sl = [bool(s) for s in slots] or [False]
    self._sched = [(self.SHORT_MS if s else self.LONG_MS, self.GAP_MS) for s in sl]
    self._pause = self.PAUSE_MS

  def set_number(self, n):
    self._solid = None
    n = max(0, min(999, int(n)))
    sched = []
    for count, dur in ((n // 100, self.LONG_MS),
                       (n // 10 % 10, self.MED_MS),
                       (n % 10, self.SHORT_MS)):
      for k in range(count):
        gap = self.GROUP_GAP_MS if k == count - 1 else self.GAP_MS
        sched.append((dur, gap))
    self._sched = sched or [(self.SHORT_MS, self.GAP_MS)]  # 0 -> a lone blip
    self._pause = self.NUM_PAUSE_MS

  def poll(self):
    if not self.led:
      return
    if self._solid is not None:
      self.led.value(1 if self._solid else 0)
      return
    now = time.ticks_ms()
    if time.ticks_diff(now, self._until) < 0:
      return
    if self._lit:
      self.led.off()
      self._lit = False
      _, gap = self._cycle[self._i]
      self._i += 1
      if self._i >= len(self._cycle):
        self._cycle = None
        self._until = time.ticks_add(now, self._cyclepause)
      else:
        self._until = time.ticks_add(now, gap)
    else:
      if self._cycle is None:
        self._cycle = self._sched[:]      # snapshot so mid-play edits are clean
        self._cyclepause = self._pause
        self._i = 0
      on, _ = self._cycle[self._i]
      self.led.on()
      self._lit = True
      self._until = time.ticks_add(now, on)


class Display:
  """SSD1306 wrapper that never raises. Retries the display every 3 s."""

  def __init__(self, addr=0x3C):
    self.addr = addr
    self.oled = None
    self._retry = Throttle(3000)
    self._was_ok = False

  @property
  def present(self):
    return self.oled is not None

  def _connect(self):
    try:
      import ssd1306

      o = ssd1306.SSD1306_I2C(128, 64, i2c(), addr=self.addr)
      # Clear display RAM snow and wake charge pump
      o.poweroff()
      time.sleep_ms(50)
      o.poweron()
      time.sleep_ms(50)
      o.fill(0)
      o.show()
      self.oled = o
      if not self._was_ok:
        log("OLED connected.")
      self._was_ok = True
    except Exception:
      self.oled = None

  FONT = 8            # the built-in 8x8 font
  PANEL = 64
  BAR_Y = 58          # the 6 px bar sits on rows 58..63
  RULE_Y = 9          # the title's underline, one blank row under the glyphs

  @staticmethod
  def layout(count, title=True, bar=False):
    """y of each of `count` rows on the 64 px panel.

    Row 0 is the title: it sits at the top with an underline. The rest are
    the readings, stacked up from the bottom edge (or from above the bar)
    at a roomy 11 px pitch, so whatever is left over is air under the
    title. Only when the top reading would run into the underline does the
    pitch tighten, to 10 then 9 px (six readings at 9 px start at y=11, one
    blank row under the rule). title=False: plain rows from the top, no
    rule, for a card like the splash.
    """
    D = Display
    if not title:
      pitch = 11 if count <= 5 else (10 if count == 6 else 9)
      return [idx * pitch for idx in range(count)]
    n = count - 1
    if n <= 0:
      return [0][:count]
    floor = D.BAR_Y if bar else D.PANEL
    for pitch in (11, 10, 9):
      top = floor - D.FONT - (n - 1) * pitch
      if top >= D.RULE_Y + 2:
        break
    return [0] + [top + idx * pitch for idx in range(n)]

  def show(self, lines, bar=None, title=True):
    """Draw text rows plus an optional 0.0-1.0 bar at the bottom.

    See layout() for where they go. With a bar, 5 rows max; else 7.
    """
    if not self.oled and self._retry.ready():
      self._connect()
    if not self.oled:
      return
    try:
      o = self.oled
      o.fill(0)
      rows = [str(t)[:16] for t in (lines[:5] if bar is not None else lines[:7])]
      for text, y in zip(rows, self.layout(len(rows), title, bar is not None)):
        o.text(text, 0, y)
      if title and rows and len(rows) > 1:
        o.hline(0, self.RULE_Y, len(rows[0]) * self.FONT, 1)
      if bar is not None:
        width = int(min(1.0, max(0.0, bar)) * 128)
        o.rect(0, 58, 128, 6, 1)
        o.fill_rect(0, 58, width, 6, 1)
      o.show()
    except Exception as e:
      log("OLED lost:", e)
      self.oled = None


class Sensor:
  """Hot-pluggable sensor wrapper.

  connect() must return a device object (raise if the part is absent).
  read(dev) must return a dict of values (raise if the part vanished).
  poll() keeps .data fresh and never raises; .ok says if the part is alive.
  """

  def __init__(self, name, connect, read, retry_ms=2000):
    self.name = name
    self._connect = connect
    self._read = read
    self.dev = None
    self.data = None
    self._retry = Throttle(retry_ms)

  @property
  def ok(self):
    return self.dev is not None

  def poll(self):
    if self.dev is None:
      if not self._retry.ready():
        return self.data
      try:
        self.dev = self._connect()
      except Exception:
        self.dev = None
        return self.data
      try:
        self.data = self._read(self.dev)
        log(self.name, "connected. First reading:", self.data)
      except Exception:
        self.data = None
      return self.data
    try:
      self.data = self._read(self.dev)
    except Exception as e:
      log(self.name, "lost:", e)
      self.dev = None
      self.data = None
    return self.data


class Placements:
  """Labels + positions for probes, persisted on the board.

  Any probe with a stable id can be placed: a DS18B20's ROM serial
  (burned in at the factory, survives rewiring), an ADS1115 channel
  ("A0"), whatever. The file (default placements.json) maps
  id -> {"label": str, "pos": [x, y, z] or None} and can be edited
  from a dashboard (see handle()) or by hand in the Viper file panel,
  so a sticky label on the wire stays in sync either way.
  """

  def __init__(self, path="placements.json"):
    self.path = path
    try:
      with open(path) as f:
        self.data = json.load(f)
    except Exception:
      self.data = {}

  def get(self, pid):
    ent = self.data.get(pid, {})
    return ent.get("label") or pid[-4:], ent.get("pos")

  def save(self):
    try:
      with open(self.path, "w") as f:
        json.dump(self.data, f)
    except Exception as e:
      log("placements save failed:", e)

  def handle(self, req):
    """Route handler for /place?id=X&label=Y&x=0&y=1&z=2 (label and
    position each optional; empty x clears the position)."""
    pid = query_str(req, "id")
    if not pid:
      return {"error": "no id"}
    ent = self.data.get(pid, {})
    label = query_str(req, "label")
    if label is not None:
      ent["label"] = label
    xs = query_str(req, "x")
    if xs is not None:
      try:
        ent["pos"] = [float(query_str(req, a, "0") or 0) for a in "xyz"]
      except ValueError:
        ent["pos"] = None
      if xs == "":
        ent["pos"] = None
    self.data[pid] = ent
    self.save()
    log("placed", pid, "->", ent)
    return {"ok": True, "id": pid, "ent": ent}


class Calibration:
  """Per-sensor linear calibration, persisted on the board (cal.json).

  value = raw * scale + offset, applied AT THE SOURCE so the OLED, the
  JSON, and every dashboard agree. Keyed by the same permanent ids as
  Placements. Two-point (ice slurry = 0, boiling = 100) or one-point
  (offset to a known-true value), and resettable. The file is read at
  boot; no file = no correction.
  """

  def __init__(self, path="cal.json"):
    self.path = path
    try:
      with open(path) as f:
        self.data = json.load(f)
    except Exception:
      self.data = {}

  def apply(self, pid, raw, digits=2):
    if raw is None:
      return None
    ent = self.data.get(pid)
    if not ent:
      return raw
    return round(raw * ent.get("scale", 1.0) + ent.get("offset", 0.0), digits)

  def save(self):
    try:
      with open(self.path, "w") as f:
        json.dump(self.data, f)
    except Exception as e:
      log("cal save failed:", e)

  def handle(self, req):
    """Route handler. /cal?id=X&reset=1 clears. Two-point:
    /cal?id=X&raw1=..&act1=..&raw2=..&act2=..  One-point offset:
    /cal?id=X&raw1=<reading>&act1=<true value>."""
    pid = query_str(req, "id")
    if not pid:
      return {"error": "no id"}
    if query_str(req, "reset") is not None:
      self.data.pop(pid, None)
      self.save()
      log("cal reset", pid)
      return {"ok": True, "id": pid, "cal": None}
    try:
      r1 = float(query_str(req, "raw1"))
      a1 = float(query_str(req, "act1"))
    except (TypeError, ValueError):
      return {"error": "need raw1 and act1"}
    r2s = query_str(req, "raw2")
    a2s = query_str(req, "act2")
    if r2s and a2s:
      try:
        r2 = float(r2s)
        a2 = float(a2s)
      except ValueError:
        return {"error": "bad raw2/act2"}
      if r2 == r1:
        return {"error": "two points need different raw readings"}
      scale = (a2 - a1) / (r2 - r1)
      offset = a1 - scale * r1
    else:
      scale = 1.0
      offset = a1 - r1
    self.data[pid] = {"scale": round(scale, 6), "offset": round(offset, 4)}
    self.save()
    log("cal", pid, "->", self.data[pid])
    return {"ok": True, "id": pid, "cal": self.data[pid]}


# ---------------------------------------------------------------------
# Web app + board identity.
# ---------------------------------------------------------------------
NAME_FILE = "name.txt"

HEADER_HTML = b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n"
HEADER_JSON = b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n"

_CTYPES = {"js": "application/javascript", "css": "text/css", "html": "text/html",
           "svg": "image/svg+xml", "json": "application/json", "txt": "text/plain"}


def _req_path(req):
  """Pull the path out of a raw 'GET /path HTTP/1.0' request."""
  try:
    text = req.decode() if isinstance(req, bytes) else req
    parts = text.split(" ", 2)
    return parts[1] if len(parts) > 1 else None
  except Exception:
    return None


def _static_header(name):
  ext = name.rsplit(".", 1)[-1] if "." in name else ""
  ct = _CTYPES.get(ext, "application/octet-stream")
  return ("HTTP/1.0 200 OK\r\nContent-Type: " + ct
          + "\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n").encode()


def _try_join(sta, ssid, password, attempts=2, wait_s=12):
  """Try to join one network a couple of times. Returns True on success.
  Two tries because a single attempt at weak signal is a coin flip."""
  for _ in range(attempts):
    try:
      sta.connect(ssid, password)
      for _ in range(wait_s * 2):
        if sta.isconnected():
          return True
        feed()
        time.sleep_ms(500)
    except Exception:
      pass
    if sta.isconnected():
      return True
    try:
      sta.disconnect()
    except Exception:
      pass
    time.sleep(1)
  return sta.isconnected()


def status(light, slots, display, app):
  """Drive the truth light for a web station. Normally POST codes for the
  parts (slots). But if the OLED is MISSING, the light instead blinks the
  board's locator number (IP octet, or AP number) so you can still reach
  the web interface. Sensors do not matter if you can't find the page."""
  if display.present:
    light.set_slots(slots)
  else:
    light.set_number(app.locate())


def board_uid():
  """The board's PERMANENT, globally-unique id: the factory-burned flash
  serial (16 hex chars). Same every boot, survives a re-flash and a
  wiped filesystem. This is the identity to TRUST when it must be
  unique. It is long, so it is not what you read off the screen."""
  return "".join("%02x" % b for b in unique_id())


def board_num():
  """A SHORT, stable number (0-999) derived from the permanent uid: the
  friendly tag you read off the OLED and type into a rescue-hotspot
  name. Same forever (survives re-flash). Not guaranteed unique in a
  big room (a collision or two among 50 boards is possible); when it
  matters, board_uid() is the unique id and name.txt lets you rename."""
  return int(board_uid()[-6:], 16) % 1000


def station_name():
  """A short, STABLE, human-friendly name for this board.

  Default: 'PicoLab' + board_num(), e.g. 'PicoLab742'. Same forever, no
  file needed. To give a board a real name, write it into name.txt on
  the board (Viper file panel): 'Bin-P3-4' becomes its name everywhere."""
  try:
    with open(NAME_FILE) as f:
      custom = f.read().strip()
      if custom:
        return custom
  except Exception:
    pass
  return "PicoLab" + str(board_num())


def query_str(req, key, default=None):
  """Pull ?key=some%20text out of a raw request, urldecoded. Matches the
  whole key only (?key= or &key=), so 'label' never matches 'xlabel'."""
  try:
    text = req.decode() if isinstance(req, bytes) else req
    idx = -1
    for lead in ("?", "&"):
      try:
        idx = text.index(lead + key + "=")
        break
      except ValueError:
        pass
    if idx < 0:
      return default
    start = idx + len(key) + 2
    end = start
    while end < len(text) and text[end] not in "& \r\n":
      end += 1
    raw = text[start:end].replace("+", " ")
    out = ""
    i = 0
    while i < len(raw):
      if raw[i] == "%" and i + 2 < len(raw) + 1:
        try:
          out += chr(int(raw[i + 1:i + 3], 16))
          i += 3
          continue
        except ValueError:
          pass
      out += raw[i]
      i += 1
    return out
  except Exception:
    return default


def query_int(req, key, default=None):
  """Pull ?key=123 out of a raw request. Returns default on any trouble."""
  try:
    marker = key + "="
    text = req.decode() if isinstance(req, bytes) else req
    start = text.index(marker) + len(marker)
    end = start
    while end < len(text) and (text[end].isdigit() or text[end] == "-"):
      end += 1
    return int(text[start:end])
  except Exception:
    return default



# ---------------------------------------------------------------------
# Fleet plumbing: identity file, the push loop, and the RAM history ring.
# All opt-in through files on the board; demos without them behave as before.
# ---------------------------------------------------------------------
BIN_FILE = "bin.json"      # {"team": "Dirt Vader", "period": 3, "bin": 7, "room": 1}
PORT = 80                  # web port (tests override)
PUSH_EVERY_S = 60          # how often a joined station POSTs /ingest to its Burrow
PUSH_TIMEOUT_S = 3         # per attempt; the loop stalls at most this long
AP_AFTER_LOST_S = 60       # open our own hotspot this long after losing the network
RESCAN_EVERY_S = 120       # while on the hotspot: look for the ladder networks this often
AP_HOLD_MAX_S = 600        # ...unless a phone is on the hotspot: then wait up to this long
# NOTE: the Pico W cannot run the hotspot and the station at the same time
# (MicroPython's rp2 port does not route between two active interfaces), so
# the board ALTERNATES: hotspot while lost, a ~15 s switch to station mode
# every RESCAN_EVERY_S to look for the ladder, back to the hotspot if nothing.
HIST_STEP_S = 300          # history ring: one sample every 5 min...
HIST_SLOTS = 288           # ...for 24 hours
HIST_MAX_METRICS = 24
HIST_SKIP = ("big", "small", "relay", "probes", "probe_count", "up")


def _flatten_numeric(d, out):
  """Numeric top-level fields of a /data dict, lists of numbers as name_i.
  Booleans, strings, dicts and the actuator fields are skipped."""
  for k in d:
    if k in HIST_SKIP:
      continue
    v = d[k]
    if isinstance(v, bool):
      continue
    if isinstance(v, (int, float)):
      out[k] = v
    elif isinstance(v, list):
      for i in range(len(v)):
        x = v[i]
        if isinstance(x, (int, float)) and not isinstance(x, bool):
          out["%s_%d" % (k, i)] = x
  return out


class History:
  """A 24-hour ring of 5-minute samples kept in RAM, served at /history so a
  bin that cannot reach anything still shows graphs to a phone on its hotspot.
  array('f') per metric: 288 slots x 24 metrics ~ 28 KB."""

  def __init__(self, step_s=HIST_STEP_S, slots=HIST_SLOTS):
    from array import array
    self._array = array
    self.step = step_s
    self.n = slots
    self.t = array("I", [0] * slots)     # uptime seconds at each sample
    self.m = {}                          # metric -> array('f')
    self.i = 0                           # next slot to write
    self.count = 0
    self._due = 0                        # uptime of the next capture

  def tick(self, data, up):
    if up < self._due:
      return False
    self._due = up - (up % self.step) + self.step
    vals = _flatten_numeric(data, {})
    nan = float("nan")
    for k in vals:
      if k not in self.m:
        if len(self.m) >= HIST_MAX_METRICS:
          continue
        self.m[k] = self._array("f", [nan] * self.n)
      self.m[k][self.i] = vals[k]
    for k in self.m:
      if k not in vals:
        self.m[k][self.i] = nan
    self.t[self.i] = up
    self.i = (self.i + 1) % self.n
    if self.count < self.n:
      self.count += 1
    return True

  def _order(self):
    if self.count < self.n:
      return range(0, self.count)
    return [(self.i + j) % self.n for j in range(self.n)]

  def send(self, cl, up, ts):
    """Stream the ring as JSON without building one big string."""
    order = self._order()
    cl.sendall(HEADER_JSON)
    cl.sendall(('{"step":%d,"n":%d,"up":%d,"ts":%s,"t":[' % (
        self.step, self.count, up, "null" if ts is None else str(ts))).encode())
    cl.sendall(",".join(str(self.t[j]) for j in order).encode())
    cl.sendall(b'],"m":{')
    first = True
    for k in self.m:
      arr = self.m[k]
      cl.sendall(('%s"%s":[' % ("" if first else ",", k)).encode())
      first = False
      parts = []
      for j in order:
        v = arr[j]
        parts.append("null" if v != v else ("%.4g" % v))
      cl.sendall(",".join(parts).encode())
      cl.sendall(b"]")
    cl.sendall(b"}}")


def _http_post_json(host, port, path, body, timeout=PUSH_TIMEOUT_S):
  """Tiny blocking POST. Returns (status, parsed-json-or-None). Raises on
  network trouble; the caller decides what that means."""
  addr = socket.getaddrinfo(host, port)[0][-1]
  s = socket.socket()
  s.settimeout(timeout)
  try:
    s.connect(addr)
    head = ("POST %s HTTP/1.0\r\nHost: %s\r\nContent-Type: application/json\r\n"
            "Content-Length: %d\r\nConnection: close\r\n\r\n" % (path, host, len(body)))
    s.send(head.encode())
    s.send(body)
    resp = b""
    while len(resp) < 2048:
      chunk = s.recv(512)
      if not chunk:
        break
      resp += chunk
  finally:
    s.close()
  sep = resp.find(b"\r\n\r\n")
  if sep < 0:
    raise OSError("bad reply")
  status = int(resp[:sep].split(b" ")[1])
  payload = resp[sep + 4:]
  try:
    return status, (json.loads(payload) if payload else None)
  except ValueError:
    return status, None


def _edge_candidates(ip, override=None):
  """Where to push: the Burrow on our own subnet (.10), then the three
  Tunnels' WAN addresses (each forwards 8080 to its Burrow)."""
  if override:
    return list(override)
  out = []
  try:
    out.append(ip.rsplit(".", 1)[0] + ".10:8080")
  except Exception:
    pass
  for n in (21, 22, 23):
    out.append("192.168.80.%d:8080" % n)
  return out

class WebApp:
  def __init__(self, import_network=True, index="index.html"):
    arm_watchdog()
    import network

    # Where this app's dashboard lives. Under the EVERYTHING install a
    # project's files sit in their own folder (bme280/index.html); when
    # a project is installed alone, its index.html is at the root. We
    # try the given path first and fall back to the root copy.
    self.index = index
    # Identity: uid is the permanent hardware serial, name is the stable
    # human-friendly handle (both survive re-flashing). ssid = name.
    self.uid = board_uid()
    self.name = station_name()
    self.ssid = self.name
    self.ip = "192.168.4.1"
    self.ap = None
    self.joined = None
    self.rescue_target = None

    # Fleet identity (team card), written by the flash script. Optional.
    self.bin = None
    try:
      with open(BIN_FILE) as f:
        b = json.load(f)
        if isinstance(b, dict):
          self.bin = b
    except Exception:
      pass

    # Wi-Fi state machine + push loop + history ring (see _net_tick).
    self.sta = None
    self.creds = None
    self.ladder = []
    self._net_state = "idle"      # idle | connecting
    self._net_try_i = 0
    self._net_candidates = []
    self._net_deadline = 0
    self._net_next = 0            # uptime of the next rescan while lost
    self._lost_at = None          # uptime when the link went away
    self._joined_at = None        # uptime when the link came (back)
    self._ap_hold_since = None    # uptime when we first deferred a rescan for a hotspot user
    self.edges = []
    self._edge_i = 0
    self.edge = None              # "host:port" that last accepted a push
    self.edge_ok = False
    self.last_push = None         # uptime of the last accepted push
    self.edge_ts = None           # (unix ts from the Burrow, uptime when received)
    self._push_due = 0
    self.push = True
    self.history = None

    # Mission-control mode: if wifi.json exists on the board
    # ({"ssid": "WormHole", "password": "supersecret"}), JOIN that
    # network so every station lives on one router and an aggregator
    # can find them all. No file, the file is bad, or the join fails
    # after retries: open our own AP, so a board is ALWAYS reachable
    # one way or the other. Delete wifi.json to force AP mode.
    creds = None
    try:
      with open("wifi.json") as f:
        creds = json.load(f)
    except Exception:
      pass
    if creds and creds.get("ssid"):
      self.creds = creds
      self.push = creds.get("push", True) is not False
      if creds.get("history", True) is not False:
        self.history = History()
      try:
        sta = network.WLAN(network.STA_IF)
        sta.active(True)
        self.sta = sta
        password = creds.get("password", "")

        # The join ladder, highest priority first. rescue nets share the
        # password and let a teacher intervene: bring up "wormmaster<X>"
        # (X = this board's 4-hex tag) and ONLY this board hops over;
        # bring up plain "wormmaster" (a phone hotspot) and EVERY board
        # hops over. Neither present: join the real classroom network.
        rescue = creds.get("rescue", "wormmaster")
        tag = str(board_num())
        ladder = []
        if rescue:
          ladder.append(rescue + tag)   # 1: just me
          ladder.append(rescue)         # 2: all boards (phone hotspot)
        ladder.append(creds["ssid"])    # 3: the real network
        self.rescue_target = (rescue + tag) if rescue else None
        self.ladder = ladder

        # Scan so we only dial networks that actually exist (blind-
        # dialing dead SSIDs would waste ~30 s each before the fallback).
        present = None
        try:
          seen = set(s[0].decode() for s in sta.scan() if s[0])
          present = [n for n in ladder if n in seen]
        except Exception:
          present = ladder      # scan failed: just try them all in order

        for name in present:
          if _try_join(sta, name, password):
            self._on_joined(name)
            break
          log("could not join", name, "- next in the ladder...")
        if not self.joined:
          log("no network joined - opening own AP; will keep looking every %ds." % RESCAN_EVERY_S)
          sta.active(False)
          self._lost_at = uptime_s() - AP_AFTER_LOST_S
          self._net_next = uptime_s() + RESCAN_EVERY_S
      except Exception as e:
        log("Wi-Fi join errored (" + str(e) + ") - opening own AP instead.")
        try:
          self.sta.active(False)
        except Exception:
          pass
        self._net_next = uptime_s() + RESCAN_EVERY_S

    if not self.joined:
      self._open_ap(network)

    self.server = None
    self._init_server()

  # ---- Wi-Fi state machine ------------------------------------------
  def _open_ap(self, network=None):
    """Open our hotspot. The station must be off first (rp2 cannot run both)."""
    if self.ap:
      return
    if network is None:
      import network
    try:
      if self.sta:
        try:
          self.sta.active(False)
        except Exception:
          pass
      self.ap = network.WLAN(network.AP_IF)
      self.ap.active(True)
      self.ap.ifconfig(("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1"))
      self.ap.config(essid=self.ssid, security=0)
      for _ in range(50):
        if self.ap.active():
          break
        time.sleep(0.1)
      self.ip = "192.168.4.1"
      self._ap_hold_since = None
      log("hotspot '" + self.ssid + "' open at http://192.168.4.1")
    except Exception as e:
      log("could not open hotspot:", e)
      self.ap = None

  def _close_ap(self):
    if not self.ap:
      return
    try:
      self.ap.active(False)
    except Exception:
      pass
    self.ap = None

  def _ap_in_use(self):
    """Is a phone or laptop on our hotspot right now?"""
    try:
      return bool(self.ap and self.ap.status("stations"))
    except Exception:
      return False

  def _on_joined(self, name):
    self.joined = name
    self.ip = self.sta.ifconfig()[0]
    self._joined_at = uptime_s()
    self._lost_at = None
    self._net_state = "idle"
    self.edges = _edge_candidates(self.ip, (self.bin or {}).get("edges") or (self.creds or {}).get("edges"))
    self._edge_i = 0
    self._push_due = uptime_s() + 5        # first push soon after joining
    log("Joined", name, "as", self.ip, "- browse http://" + self.ip)

  def _net_tick(self):
    """Keep the station on the ladder, without ever blocking for long while
    joined. Joined -> lost: quick non-blocking retries for AP_AFTER_LOST_S,
    then the hotspot opens (station off). On the hotspot: every
    RESCAN_EVERY_S switch to the station for a few seconds to look for the
    ladder (deferred while someone is using the hotspot, at most
    AP_HOLD_MAX_S), rejoin if found, else back to the hotspot."""
    if not self.sta:
      return
    up = uptime_s()
    if self.joined:
      try:
        ok = self.sta.isconnected()
      except Exception:
        ok = False
      if ok:
        return
      log("network", self.joined, "lost - retrying; hotspot opens in %ds" % AP_AFTER_LOST_S)
      self.joined = None
      self.edge_ok = False
      self._lost_at = up
      self._net_next = up + 5           # a quick first retry
      self._net_state = "idle"
      return
    if self.ap:
      # hotspot mode: periodically go looking, unless a phone is on us
      if up < self._net_next:
        return
      if self._ap_in_use():
        if self._ap_hold_since is None:
          self._ap_hold_since = up
        if up - self._ap_hold_since < AP_HOLD_MAX_S:
          self._net_next = up + 30      # check again soon
          return
      self._net_next = up + RESCAN_EVERY_S
      self._try_ladder_blocking()
      return
    # station only, not joined: the grace period after a loss
    if self._lost_at is not None and up - self._lost_at >= AP_AFTER_LOST_S:
      self._net_state = "idle"
      self._net_next = up + RESCAN_EVERY_S
      self._open_ap()
      return
    if self._net_state == "idle":
      if up < self._net_next:
        return
      self._net_next = up + RESCAN_EVERY_S
      try:
        seen = set(x[0].decode() for x in self.sta.scan() if x[0])
        present = [n for n in self.ladder if n in seen]
      except Exception:
        present = list(self.ladder)
      if not present:
        return
      self._net_candidates = present
      self._net_try_i = 0
      self._start_connect()
    elif self._net_state == "connecting":
      try:
        if self.sta.isconnected():
          self._on_joined(self._net_candidates[self._net_try_i])
          return
      except Exception:
        pass
      if up >= self._net_deadline:
        self._net_try_i += 1
        if self._net_try_i < len(self._net_candidates):
          self._start_connect()
        else:
          self._net_state = "idle"

  def _start_connect(self):
    name = self._net_candidates[self._net_try_i]
    try:
      try:
        self.sta.disconnect()
      except Exception:
        pass
      self.sta.connect(name, (self.creds or {}).get("password", ""))
      self._net_state = "connecting"
      self._net_deadline = uptime_s() + 15
      log("trying to join", name, "...")
    except Exception as e:
      log("connect to", name, "failed:", e)
      self._net_state = "idle"

  def _try_ladder_blocking(self):
    """From hotspot mode: drop the hotspot, bring the station up, try the
    ladder once (a few seconds per network present), and either stay joined
    or put the hotspot back. Blocks the loop for up to ~15 s per present
    network; the sensors and screen pause, the hotspot is briefly gone."""
    log("hotspot pausing to look for", "/".join(self.ladder))
    self._close_ap()
    try:
      self.sta.active(True)
      time.sleep_ms(300)
      try:
        seen = set(x[0].decode() for x in self.sta.scan() if x[0])
        present = [n for n in self.ladder if n in seen]
      except Exception:
        present = []
      for name in present:
        if _try_join(self.sta, name, (self.creds or {}).get("password", ""), attempts=1, wait_s=12):
          self._on_joined(name)
          return True
      if present:
        log("could not join", ", ".join(present), "- hotspot back on")
    except Exception as e:
      log("rescan failed:", e)
    try:
      self.sta.active(False)
    except Exception:
      pass
    self._open_ap()
    return False

  # ---- push loop -----------------------------------------------------
  def _uplink_tick(self, data_fn):
    if not (self.push and self.joined and self.edges):
      return
    up = uptime_s()
    if up < self._push_due:
      return
    self._push_due = up + PUSH_EVERY_S
    try:
      d = data_fn()
      ident = self.identity()
      for k in ident:
        if k not in d:
          d[k] = ident[k]
      d["up"] = up
      try:
        d["rssi"] = self.sta.status("rssi")
      except Exception:
        pass
      body = json.dumps(d).encode("utf-8")
    except Exception as e:
      log("push: could not build payload:", e)
      return
    # ONE candidate per tick: a dead Burrow costs at most PUSH_TIMEOUT_S of
    # stall per minute, never a stacked 4 x 3 s freeze of the sensor loop.
    # On failure the next tick tries the next Burrow in the list.
    target = self.edges[self._edge_i % len(self.edges)]
    host, _, port = target.partition(":")
    try:
      status, reply = _http_post_json(host, int(port or 8080), "/ingest", body)
      if status == 200 and reply and reply.get("ok"):
        if not self.edge_ok or self.edge != target:
          log("push: Burrow", reply.get("edge", "?"), "at", target, "accepted us")
        self.edge = target
        self.edge_ok = True
        self.last_push = up
        if reply.get("ts"):
          self.edge_ts = (int(reply["ts"]), up)
        return
      log("push:", target, "answered", status)
    except Exception as e:
      if self.edge_ok:
        log("push:", target, "unreachable (" + str(e) + "), trying the next Burrow next minute")
    self.edge_ok = False
    self._edge_i += 1
    # retry sooner than a full minute while hunting for a Burrow
    self._push_due = up + (15 if len(self.edges) > 1 else PUSH_EVERY_S)

  def now_ts(self):
    """Unix time, if a Burrow ever told us; else None (the Pico has no clock)."""
    if not self.edge_ts:
      return None
    ts, at = self.edge_ts
    return ts + (uptime_s() - at)

  def _init_server(self):
    # Re-running a program (Viper: Stop then Run) can leave the OLD web
    # socket still holding port 80 for a few seconds. So retry with a
    # growing wait, freeing memory each time. And if it truly will not
    # bind, DO NOT crash: the station keeps running with its screen,
    # sensors, and light -- only the web page is missing. A dead screen
    # is never worth an unbindable port.
    import gc
    addr = socket.getaddrinfo("0.0.0.0", PORT)[0][-1]
    for attempt in range(6):
      try:
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(addr)
        self.server.listen(2)
        self.server.settimeout(0.05)
        return
      except OSError as e:
        try:
          self.server.close()
        except Exception:
          pass
        self.server = None
        if e.errno != 98:      # not "address in use": a real problem
          log("Web server error:", e, "- station runs without the web page.")
          return
        gc.collect()
        if self.ap:
          log("Port 80 busy, recycling Wi-Fi (try %d)..." % (attempt + 1))
          try:
            self.ap.active(False)
            time.sleep(0.5)
            self.ap.active(True)
            self.ap.ifconfig(("192.168.4.1", "255.255.255.0", "192.168.4.1", "192.168.4.1"))
            self.ap.config(essid=self.ssid, security=0)
          except Exception:
            pass
        else:
          log("Port 80 busy, waiting for the old socket to free (try %d)..." % (attempt + 1))
        for _ in range(1 + attempt):   # 1, 2, 3, 4, 5 s, fed each second
          feed()
          time.sleep(1)
    log("Port 80 stayed busy - station is running WITHOUT the web page")
    log("(the screen and sensors work; do a full reset to get the web page back).")
    self.server = None

  def close(self):
    """Release port 80 so the NEXT run does not hit 'address in use'.

    Call this from a `finally:` around your main loop. The finally runs on
    a normal exit AND on a crash (an unhandled exception or the
    KeyboardInterrupt a Stop/Ctrl-C raises unwinds THROUGH finally), so the
    socket is closed either way. The only thing that skips it is a hard
    power event (brownout, hard reset, watchdog), and that frees the port
    on its own. Safe to call anytime, more than once, and never raises."""
    try:
      if self.server:
        self.server.close()
        log("web port 80 released for the next run.")
    except Exception:
      pass
    self.server = None

  def locate(self):
    """The number that finds this board when it has no screen: the last
    octet of its IP when joined (browse to it), or its PicoLab number
    when hosting its own AP (join that SSID). StatusLight blinks it."""
    if self.joined:
      try:
        return int(self.ip.rsplit(".", 1)[-1])
      except Exception:
        return 0
    return board_num()

  def identity(self):
    """Who this board is, for the dashboard and the wall to label by."""
    mode = "joined" if self.joined else "ap"
    d = {
        "id": self.uid,                       # permanent hardware serial
        "name": self.name,                    # stable friendly name
        "ip": self.ip,                        # where to browse right now
        "ssid": self.ssid,
        "mode": mode,
        "net": self.joined or self.ssid,
    }
    if self.bin:
      d["bin"] = self.bin                     # team card: team/period/bin/room
    if self.sta and self.push:
      d["edge"] = self.edge if self.edge_ok else None
    return d

  def announce(self, title):
    if self.joined:
      lines = [
          "Name:   " + self.name,
          "Board:  " + self.uid,
          "On:     " + self.joined,
          "Browse: http://" + self.ip,
      ]
      if self.rescue_target:
        lines.append("Rescue: " + self.rescue_target)
      if self.bin:
        lines.append("Team:   %s (P%s bin %s, room %s)" % (self.bin.get("team"), self.bin.get("period"),
                                                           self.bin.get("bin"), self.bin.get("room")))
      if self.push:
        lines.append("Pushes: to " + ", ".join(self.edges[:2]) + ("..." if len(self.edges) > 2 else ""))
      banner(title, lines)
    else:
      lines = [
          "Name:   " + self.name,
          "Board:  " + self.uid,
          "Wi-Fi:  join '" + self.ssid + "'",
          "Browse: http://192.168.4.1",
      ]
      if self.rescue_target:
        lines.append("Rescue net: " + self.rescue_target)
      banner(title, lines)

  def poll(self, data_fn, routes=None):
    """Serve one pending request, if any. Never raises.

    data_fn() -> dict, served as JSON at /data.
    routes: optional list of (prefix, handler); handler(req) -> dict,
    also served as JSON. Use for actions like /set?angle=90.
    """
    # Housekeeping first, every call, all cheap unless something changed:
    # the Wi-Fi ladder, the push to the Burrow, the history sample.
    feed()
    try:
      self._net_tick()
    except Exception as e:
      log("net tick:", e)
    try:
      self._uplink_tick(data_fn)
    except Exception as e:
      log("push tick:", e)
    if self.history:
      try:
        up = uptime_s()
        if up >= self.history._due:
          self.history.tick(data_fn(), up)
      except Exception as e:
        log("history tick:", e)
    if not self.server:      # port 80 never opened; run without the web page
      return
    try:
      cl, _ = self.server.accept()
    except OSError:
      return
    try:
      cl.settimeout(0.5)
      req = b""
      try:
        req = cl.recv(512)
      except Exception:
        pass

      handled = False
      if routes:
        for prefix, handler in routes:
          if prefix.encode() in req:
            try:
              payload = json.dumps(handler(req)).encode("utf-8")
            except Exception as e:
              payload = json.dumps({"error": str(e)}).encode("utf-8")
            cl.sendall(HEADER_JSON + payload)
            handled = True
            break

      if not handled and b"GET /history" in req:
        try:
          if self.history:
            self.history.send(cl, uptime_s(), self.now_ts())
          else:
            cl.sendall(HEADER_JSON + b'{"step":0,"n":0,"t":[],"m":{}}')
        except Exception as e:
          log("history send:", e)
        handled = True

      if not handled and b"/data" in req:
        try:
          data = data_fn()
          # Every station reports its identity for free, so the wall
          # and any kid can tell boards apart and know where to browse.
          ident = self.identity()
          for k in ident:
            if k not in data:
              data[k] = ident[k]
          payload = json.dumps(data).encode("utf-8")
        except Exception as e:
          payload = json.dumps({"error": str(e)}).encode("utf-8")
        cl.sendall(HEADER_JSON + payload)
        handled = True

      if not handled:
        # Serve a real static file if the request names one (e.g.
        # /cal.js, the shared calibration widget). Anything else falls
        # back to the dashboard page.
        path = _req_path(req)
        static = None
        if path and path != "/" and "." in path and ".." not in path:
          static = path.lstrip("/")
        if static:
          try:
            with open(static, "rb") as f:
              cl.sendall(_static_header(static))
              while True:
                chunk = f.read(512)
                if not chunk:
                  break
                cl.sendall(chunk)
            cl.close()
            return
          except Exception:
            # The request named a real file (e.g. /cal.js) that isn't on
            # the board. Answer with an honest 404, NOT the dashboard
            # HTML: a <script src> or <link> that receives HTML fails in
            # confusing ways (undefined globals) instead of failing clean.
            try:
              cl.sendall(b"HTTP/1.0 404 Not Found\r\nConnection: close\r\n\r\nnot found")
              cl.close()
            except Exception:
              pass
            return
        cl.sendall(HEADER_HTML)
        served = False
        for page in (self.index, "index.html"):
          try:
            with open(page, "rb") as f:
              while True:
                chunk = f.read(512)
                if not chunk:
                  break
                cl.sendall(chunk)
            served = True
            break
          except Exception:
            continue
        if not served:
          cl.sendall(b"<h1>404: File Not Found</h1>")
      cl.close()
    except Exception:
      try:
        cl.close()
      except Exception:
        pass
