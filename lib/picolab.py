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
import os
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
VERSION = "0.2.2"

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


def _bump_boot():
  """Boot counter in a file: the n-th power-up or reset of this board."""
  n = 0
  try:
    with open(BOOT_FILE) as f:
      n = int(f.read().strip() or 0)
  except Exception:
    pass
  n += 1
  try:
    with open(BOOT_FILE, "w") as f:
      f.write(str(n))
  except Exception:
    pass
  return n


def _read_clock():
  """A starting point for wall time when no Burrow has spoken yet: the
  RTC if a previous boot of this power cycle set it, else the time saved
  in CLOCK_FILE (so the estimate is late by the length of the power cut
  plus up to 10 min; the Burrow corrects that when the rows arrive)."""
  try:
    t = int(time.time())
    if t > 1700000000:
      return t - uptime_s()
  except Exception:
    pass
  try:
    with open(CLOCK_FILE) as f:
      return int(f.read().strip())
  except Exception:
    return None


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


class Smoother:
  """Two views of a noisy reading: `now`, an exponential average biased to
  the latest samples (alpha 0.5 at 2 samples/s is a second or two: what
  a screen should show), and `avg`, the plain mean of the last `n`
  samples (120 at 2/s = a minute: what the record should keep). feed()
  returns (now, avg). reset() on a reconnect so a stale history does not
  drag a fresh part."""

  def __init__(self, alpha=0.5, n=120):
    self.alpha, self.n = alpha, n
    self.reset()

  def reset(self):
    self.now = None
    self._ring, self._i, self._sum, self.count = [0] * self.n, 0, 0, 0

  def feed(self, x):
    self.now = x if self.now is None else self.now + self.alpha * (x - self.now)
    if self.count < self.n:
      self.count += 1
    else:
      self._sum -= self._ring[self._i]
    self._ring[self._i] = x
    self._sum += x
    self._i = (self._i + 1) % self.n
    return self.now, self.avg

  @property
  def avg(self):
    return None if not self.count else self._sum / self.count


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

  HOLD_MS = 5000      # the title shows (still, or scrolling if long) this long between marquee runs
  SCROLL_PX_S = 50    # scrolling text moves this fast (~6 letters/s; a 60-char line crosses in ~12 s),
                      #    on the wall clock, so the pace is the same however fast the loop runs
  SHOW_FPS = 20       # a show's frames come this fast (an I2C refresh is ~25 ms, so this is the ceiling)
  SHOW_HOLD_MS = 600  # ...and its last frame lingers this long

  def __init__(self, addr=0x3C):
    self.addr = addr
    self.oled = None
    self._retry = Throttle(3000)
    self._was_ok = False
    # The title row. A name that fits (16 chars) sits centered; a longer
    # one scrolls through. With `marquee` set (and tick() called every
    # pass): show the name HOLD_MS, scroll the marquee through, repeat.
    # With `shows` set too (a list of classes with .frames and .draw(o, t),
    # see lib/wormshow.py) the two take turns after each hold: name,
    # marquee, name, a show, name, marquee, name, the next show...
    self.marquee = None
    self.shows = None
    self._show = None                 # the show now playing (an instance), else None
    self._show_t = 0                  # its next frame
    self._show_drawn = 0              # frames drawn so far (fewer than frames when the loop stalled)
    self._show_at = 0                 # when it started
    self._show_idx = 0                # which show plays next (in order, so it is predictable)
    self._show_next = False           # True: the next hold ends with a show, False: the marquee
    self._mq = False                  # True while the marquee text is crossing
    self._x = None                    # x of whatever is scrolling (None: nothing yet)
    self._hold_at = time.ticks_ms()   # when the current hold began
    self._scroll_at = self._hold_at   # when the current scrolling pass entered from the right
    self._lines, self._bar, self._title = None, None, True
    self._title_seen = False

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
    if title and not self._title_seen:          # the first titled screen starts the first hold
      self._title_seen, self._hold_at = True, time.ticks_ms()
    self._lines, self._bar, self._title = lines, bar, title
    if not self._show:                          # a running show keeps the screen; the rows wait
      self._draw()

  def tick(self):
    """Call every loop pass: scrolls a long title, runs the marquee and
    plays the shows."""
    if not self._title or not self._lines or not self.oled:
      return
    now = time.ticks_ms()
    if self._show:
      self._show_tick(now)
      return
    name = str(self._lines[0])
    long = len(name) * self.FONT > 128
    if not self._mq and not long:               # a short name holds still
      if time.ticks_diff(now, self._hold_at) < self.HOLD_MS or not self._after_hold(now):
        return
    else:                                       # something is crossing, on the wall clock
      text = self.marquee if self._mq else name
      if self._x is None:                       # a pass begins: enter from the right
        self._x, self._scroll_at = 128, now
      else:
        x = 128 - (time.ticks_diff(now, self._scroll_at) * self.SCROLL_PX_S) // 1000
        if x == self._x:
          return                                # not a pixel further yet
        self._x = x
      if self._x + len(text) * self.FONT <= 0:  # this pass has left the screen
        if self._mq:
          self._mq, self._hold_at = False, now  # back to the name
        elif time.ticks_diff(now, self._hold_at) >= self.HOLD_MS:
          self._after_hold(now)                 # the name has had its HOLD_MS
        self._x, self._scroll_at = 128, now
    if not self._show:
      self._draw()

  def _after_hold(self, now):
    """The name has had its HOLD_MS: start what follows it. The marquee
    and the shows take turns; with only one of them set it is always that
    one. False when there is nothing to follow it."""
    if self.shows and (self._show_next or not self.marquee):
      cls = self.shows[self._show_idx % len(self.shows)]
      self._show_idx += 1
      self._show, self._show_t, self._show_at, self._show_next = cls(), 0, now, False
      self._show_drawn = 0
      self._show_tick(now)                      # frame 0 right away
      return True
    if self.marquee:
      self._mq, self._x, self._scroll_at, self._show_next = True, 128, now, True
      return True
    return False

  def _show_tick(self, now):
    """The running show, on the wall clock: frame elapsed // period, so a
    sensor sweep that stalls the loop skips frames rather than slowing the
    show down, and every show takes its frames / SHOW_FPS seconds plus
    SHOW_HOLD_MS on the last frame. Then the name again, for a fresh hold."""
    s = self._show
    period = 1000 // self.SHOW_FPS
    elapsed = time.ticks_diff(now, self._show_at)
    if elapsed >= (s.frames - 1) * period + self.SHOW_HOLD_MS:
      log("%s: %d of %d frames in %d ms" % (getattr(s, "name", "show"), self._show_drawn, s.frames, elapsed))
      self._show, self._hold_at, self._x = None, now, None
      self._draw()
      return
    t = min(elapsed // period, s.frames - 1)
    if t < self._show_t:
      return
    try:
      o = self.oled
      o.fill(0)
      s.draw(o, t)
      o.show()
    except Exception as e:
      log("show lost:", e)
      self._show, self.oled = None, None
      return
    self._show_t, self._show_drawn = t + 1, self._show_drawn + 1

  def _draw(self):
    if not self.oled and self._retry.ready():
      self._connect()
    if not self.oled:
      return
    lines, bar, title = self._lines, self._bar, self._title
    try:
      o = self.oled
      o.fill(0)
      rows = [str(t)[:16] for t in (lines[:5] if bar is not None else lines[:7])]
      for text, y in zip(rows, self.layout(len(rows), title, bar is not None)):
        if y == 0 and title and len(rows) > 1:
          continue                              # the title row is drawn below
        o.text(text, 0, y)
      if title and len(rows) > 1:
        text = self.marquee if self._mq else str(lines[0])
        w = len(text) * self.FONT
        if not self._mq and w <= 128:           # a name that fits: centered, held still
          x = (128 - w) // 2
        else:                                   # scrolling: tick() moves it
          x = 0 if self._x is None else self._x
        o.text(text, x, 0)                      # framebuf clips what is off-screen
        o.hline(max(0, x), self.RULE_Y, min(128, x + w) - max(0, x), 1)
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
HEADER_403 = HEADER_JSON.replace(b"200 OK", b"403 Forbidden")

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


def pin_for(name, ip):
  """The board's PIN, from what is written on its screen: its name and
  the address you browse to. Two numbers glued together: the 2nd letter
  of the name as a number (a=1 ... z=26) plus the FIRST digit of the
  address's last octet, then the 2nd-to-last letter plus the LAST digit.
  'The Wrigglers' at 192.168.4.16: h=8 + 1 = 9, r=18 + 6 = 24 -> '924'.
  Letters only count (spaces, digits, punctuation are skipped); a one-
  letter name uses that letter twice. Guessable by someone who reads the
  rule, which is the point: a low wall that rewards effort."""
  letters = [c for c in name.lower() if "a" <= c <= "z"] or ["a"]
  second = letters[1] if len(letters) > 1 else letters[0]
  penult = letters[-2] if len(letters) > 1 else letters[0]
  octet = str(ip).rsplit(".", 1)[-1]
  digits = [int(c) for c in octet if c.isdigit()] or [0]
  return "%d%d" % (ord(second) - 96 + digits[0], ord(penult) - 96 + digits[-1])


PIN_MAX_FAILS = 5          # wrong PINs in a row before...
PIN_LOCK_S = 60            # ...every PIN-gated request is refused for this long


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
# The bin number IS the board's address: 192.168.4.<bin> on its own hotspot
# and <tunnel subnet>.<bin> (static, not a DHCP lease) on the classroom
# network, so the number on the lid, the screen, the PIN and the URL agree.
# Numbers a bin cannot have: 1 (the router), 10 (the Burrow), 16-23 (the
# hotspot hands those to phones), 100+ (the Tunnels' DHCP pool).
AP_NET = "192.168.4."


def valid_octet(n):
  try:
    n = int(n)
  except (TypeError, ValueError):
    return False
  return 2 <= n <= 99 and n != 10 and not 16 <= n <= 23

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
# The flash buffer: every push the Burrows did not get, kept on the board
# until one does. A month with every Burrow dark is the design case (spring
# break): at one record a minute and ~12 bytes a record that is ~500 KB.
BUF_DIR = "buf"
BUF_MAX_BYTES = 1500000    # then the oldest file is thinned 4x, again, then dropped
BUF_FILE_RECORDS = 720     # a new file every 12 h of records (or when the field set changes)
BUF_BATCH = 60             # rows per /ingest/batch POST...
BUF_BATCHES_PER_TICK = 8   # ...and POSTs per push tick while catching up (~8 h of rows a minute)
BUF_SCALE = 10             # values are stored as tenths
CLOCK_FILE = "clock.txt"   # the last unix time a Burrow told us, saved every 10 min
BOOT_FILE = "boot.txt"     # boot counter: records say which boot's clock they were stamped by
HIST_STEP_S = 300          # history ring: one sample every 5 min...
HIST_SLOTS = 288           # ...for 24 hours
HIST_MAX_METRICS = 24
HIST_SKIP = ("big", "small", "relay", "probes", "probe_count", "up", "buffered")


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


# ---- varint / zigzag helpers for the buffer records -----------------
def _vw(out, n):
  while n >= 0x80:
    out.append((n & 0x7F) | 0x80)
    n >>= 7
  out.append(n)


def _vr(buf, i):
  n, shift = 0, 0
  while True:
    b = buf[i]
    i += 1
    n |= (b & 0x7F) << shift
    if not b & 0x80:
      return n, i
    shift += 7


def _zz(n):
  return n * 2 if n >= 0 else -n * 2 - 1


def _unzz(u):
  return (u >> 1) if not (u & 1) else -((u + 1) >> 1)


def _fixed(v):
  return int(round(v * BUF_SCALE))


def _unfixed(n):
  return n // BUF_SCALE if n % BUF_SCALE == 0 else n / BUF_SCALE


class Buffer:
  """Pushes the Burrows did not get, packed on flash until one does.

  One file at a time is open for appending; a file holds up to
  BUF_FILE_RECORDS records with one field set (a JSON header line names
  the fields, the boot, and the scale). A record is: varint(seconds since
  the previous record), a flags byte (bit 0 = the clock was an estimate,
  bit 1 = no clock at all), varint(presence bitmask), then one zigzag
  varint per present field holding the change since that field's last
  stored value. Steady readings cost a byte a field; a whole record of a
  lean bin is about 12 bytes.

  Sending: batch() hands the oldest rows (from the cursor), ack() moves
  the cursor (persisted, so a reboot mid-file resends at most one
  batch) and deletes a file once every row of it was accepted.

  Eviction: over max_bytes the oldest file is rewritten keeping every
  4th record; a file thinned to 1-in-64 (hourly) is deleted instead.
  """

  def __init__(self, path=BUF_DIR, max_bytes=BUF_MAX_BYTES):
    self.path = path
    self.max_bytes = max_bytes
    self._cur = None          # [name, fields, last_ts, last_vals(list), n]
    try:
      os.mkdir(path)
    except OSError:
      pass
    self.counts = self._read_json("index.json") or {}
    self.cursor = self._read_json("cursor.json")   # {"file": name, "i": n}
    self.files = sorted(f for f in os.listdir(path) if f.endswith(".rec"))
    self.size = 0
    for f in self.files:
      self.size += self._size_of(f)
      if f not in self.counts or f == self.files[-1]:
        self.counts[f] = sum(1 for _ in self.records(f))   # the file open at the last boot
    for f in list(self.counts):
      if f not in self.files:
        del self.counts[f]
    self.seq = (int(self.files[-1][:8]) + 1) if self.files else 1
    if self.cursor and self.cursor.get("file") not in self.files:
      self.cursor = None

  # ---- small files ---------------------------------------------------
  def _p(self, name):
    return self.path + "/" + name

  def _size_of(self, name):
    try:
      return os.stat(self._p(name))[6]
    except OSError:
      return 0

  def _read_json(self, name):
    try:
      with open(self._p(name)) as f:
        return json.load(f)
    except Exception:
      return None

  def _write_json(self, name, obj):
    try:
      with open(self._p(name), "w") as f:
        json.dump(obj, f)
    except OSError as e:
      log("buffer: write", name, "failed:", e)

  def total(self):
    return sum(self.counts.values())

  def pending(self):
    """Rows not yet acknowledged."""
    n = self.total()
    if self.cursor:
      n -= self.cursor.get("i", 0)
    return n

  # ---- writing -------------------------------------------------------
  def _rotate(self, fields, boot, thin=1):
    name = "%08d.rec" % self.seq
    self.seq += 1
    head = json.dumps({"v": 1, "boot": boot, "fields": fields, "scale": BUF_SCALE, "thin": thin}) + "\n"
    with open(self._p(name), "w") as f:
      f.write(head)
    self.files.append(name)
    self.counts[name] = 0
    self.size += len(head)
    self._cur = [name, fields, 0, [0] * len(fields), 0]
    self._write_json("index.json", self.counts)
    return name

  @staticmethod
  def _encode(fields, last_ts, last_vals, ts, clk, vals):
    rec = bytearray()
    _vw(rec, max(0, ts - last_ts))
    rec.append(0 if clk == "ok" else (1 if clk == "est" else 2))
    mask = 0
    for i in range(len(fields)):
      if vals.get(fields[i]) is not None:
        mask |= 1 << i
    _vw(rec, mask)
    for i in range(len(fields)):
      if mask & (1 << i):
        v = _fixed(vals[fields[i]])
        _vw(rec, _zz(v - last_vals[i]))
        last_vals[i] = v
    return rec

  def add(self, ts, clk, boot, d):
    vals = _flatten_numeric(d, {})
    if not vals:
      return                                    # nothing measured yet (parts still connecting)
    cur = self._cur
    # A file's field list only grows: a reading that is absent for a while
    # (a probe unplugged) is a gap in the mask, not a new file. A field
    # never seen in this file starts a new one with the union.
    if cur is None or cur[4] >= BUF_FILE_RECORDS:
      self._rotate(sorted(vals), boot)
      cur = self._cur
    elif any(k not in cur[1] for k in vals):
      self._rotate(sorted(set(cur[1]) | set(vals)), boot)
      cur = self._cur
    rec = self._encode(cur[1], cur[2], cur[3], ts, clk, vals)
    try:
      with open(self._p(cur[0]), "ab") as f:
        f.write(rec)
    except OSError as e:
      log("buffer: append failed:", e)
      return
    cur[2] = max(cur[2], ts)
    cur[4] += 1
    self.counts[cur[0]] = cur[4]
    self.size += len(rec)
    if self.size > self.max_bytes:
      self._evict()

  # ---- reading -------------------------------------------------------
  def _head_and_body(self, name):
    with open(self._p(name), "rb") as f:
      data = f.read()
    nl = data.find(b"\n")
    head = json.loads(data[:nl])
    return head, data, nl + 1

  def records(self, name):
    """Yield (ts, clk, boot, d) for every record in a file."""
    try:
      head, data, i = self._head_and_body(name)
    except Exception as e:
      log("buffer: unreadable", name, e)
      return
    fields, boot, scale = head["fields"], head.get("boot"), head.get("scale", BUF_SCALE)
    last_vals = [0] * len(fields)
    ts = 0
    end = len(data)
    while i < end:
      try:
        dt, i = _vr(data, i)
        flags = data[i]
        i += 1
        mask, i = _vr(data, i)
        d = {}
        for k in range(len(fields)):
          if mask & (1 << k):
            u, i = _vr(data, i)
            last_vals[k] += _unzz(u)
            d[fields[k]] = _unfixed(last_vals[k]) if scale == BUF_SCALE else last_vals[k] / scale
      except IndexError:
        break                                     # torn tail (power cut mid-record)
      ts += dt
      yield ts, ("ok", "est", "none")[flags & 3], boot, d

  def batch(self, n=BUF_BATCH):
    """(file, start_index, rows) for the oldest unsent rows, rows being
    dicts ready for /ingest/batch. ([], when nothing is waiting.)"""
    if not self.files:
      return None, 0, []
    name = self.files[0]
    start = self.cursor["i"] if self.cursor and self.cursor.get("file") == name else 0
    rows = []
    k = 0
    for ts, clk, boot, d in self.records(name):
      if k >= start:
        rows.append({"ts": ts, "clk": clk, "boot": boot, "d": d})
        if len(rows) >= n:
          break
      k += 1
    return name, start, rows

  def ack(self, name, upto):
    """Rows [0, upto) of `name` were accepted."""
    if name not in self.counts:
      return
    if upto >= self.counts[name] and (self._cur is None or self._cur[0] != name):
      try:
        os.remove(self._p(name))
      except OSError:
        pass
      self.size -= self._size_of(name)
      self.files.remove(name)
      self.counts.pop(name, None)
      self.cursor = None
      self._write_json("index.json", self.counts)
      try:
        os.remove(self._p("cursor.json"))
      except OSError:
        pass
    else:
      self.cursor = {"file": name, "i": upto}
      self._write_json("cursor.json", self.cursor)

  # ---- eviction ------------------------------------------------------
  def _evict(self):
    while self.size > self.max_bytes and self.files:
      name = self.files[0]
      if self._cur and self._cur[0] == name:
        return                                    # only the open file left: let it grow
      try:
        head = self._head_and_body(name)[0]
      except Exception:
        head = {"thin": 64}
      thin = head.get("thin", 1)
      if thin >= 64:
        log("buffer: full, dropping", name)
        self.ack(name, self.counts.get(name, 0))
        continue
      kept = []
      for k, rec in enumerate(self.records(name)):
        if k % 4 == 0:
          kept.append(rec)
      fields = head["fields"]
      body = bytearray()
      last_ts, last_vals = 0, [0] * len(fields)
      for ts, clk, boot, d in kept:
        body += self._encode(fields, last_ts, last_vals, ts, clk, d)
        last_ts = ts
      head["thin"] = thin * 4
      newhead = json.dumps(head) + "\n"
      try:
        with open(self._p(name), "wb") as f:
          f.write(newhead.encode())
          f.write(body)
      except OSError as e:
        log("buffer: thin failed:", e)
        return
      self.size = sum(self._size_of(f) for f in self.files)
      self.counts[name] = len(kept)
      if self.cursor and self.cursor.get("file") == name:
        self.cursor = {"file": name, "i": self.cursor["i"] // 4}
        self._write_json("cursor.json", self.cursor)
      self._write_json("index.json", self.counts)
      log("buffer: full, thinned", name, "to 1 in", thin * 4)


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
    self.num = None               # the bin number = the address's last octet (see AP_NET)
    try:
      with open(BIN_FILE) as f:
        b = json.load(f)
        if isinstance(b, dict):
          self.bin = b
          if valid_octet(b.get("bin")):
            self.num = int(b["bin"])
          elif b.get("bin") is not None:
            log("bin.json: bin %r cannot be an address (2-99, not 10, not 16-23): DHCP + 192.168.4.1" % (b.get("bin"),))
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
    self.buffer = None
    self._pin_fails = 0
    self._pin_locked_until = 0
    self._restart_at = None         # uptime at which to reset (after a rename)
    self.boot = _bump_boot()
    self._clock_est = _read_clock()   # unix time at boot if a Burrow ever told us (else None)
    self._clock_saved = 0

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
      if self.push and creds.get("buffer", True) is not False:
        try:
          self.buffer = Buffer()
          if self.buffer.total():
            log("buffer: %d rows waiting for a Burrow" % self.buffer.total())
        except Exception as e:
          log("buffer: disabled:", e)
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
      ip = self.ap_ip()
      self.ap.ifconfig((ip, "255.255.255.0", ip, ip))
      self.ap.config(essid=self.ssid, security=0)
      for _ in range(50):
        if self.ap.active():
          break
        time.sleep(0.1)
      self.ip = ip
      self._ap_hold_since = None
      log("hotspot '" + self.ssid + "' open at http://" + ip)
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

  def ap_ip(self):
    """Our hotspot address: 192.168.4.<bin>, or .1 for a board with no card."""
    return AP_NET + str(self.num if self.num else 1)

  def _fix_address(self, name):
    """On the classroom network, trade the DHCP lease for <subnet>.<bin>
    (same mask, gateway and DNS the lease came with). Only there: a
    rescue hotspot's pool is unknown, so its lease stays."""
    if not self.num or not self.creds or name != self.creds.get("ssid"):
      return
    try:
      ip, mask, gw, dns = self.sta.ifconfig()
      want = ip.rsplit(".", 1)[0] + "." + str(self.num)
      if want == ip:
        return
      if gw.rsplit(".", 1)[-1] == str(self.num):
        log("address: .%d is the gateway here; keeping the lease %s" % (self.num, ip))
        return
      self.sta.ifconfig((want, mask, gw, dns))
      log("address: lease", ip, "-> static", want, "(bin %d)" % self.num)
    except Exception as e:
      log("address: could not set the static address:", e)

  def _on_joined(self, name):
    self.joined = name
    self._fix_address(name)
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
  def wall(self):
    """(unix time, clk): clk is "ok" when a Burrow set the clock this
    boot, "est" when it is the saved/RTC estimate, "none" when it is
    seconds since boot. The Burrow re-bases est/none rows on arrival."""
    up = uptime_s()
    if self.edge_ts:
      ts, at = self.edge_ts
      return ts + (up - at), "ok"
    if self._clock_est is not None:
      return self._clock_est + up, "est"
    return up, "none"

  def _save_clock(self, ts, up):
    if up - self._clock_saved < 600:
      return
    self._clock_saved = up
    try:
      with open(CLOCK_FILE, "w") as f:
        f.write(str(int(ts)))
    except Exception:
      pass

  def _uplink_tick(self, data_fn):
    if not self.push or not self.creds:
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
      if self.joined:                      # the station's signal; junk while on the hotspot
        try:
          d["rssi"] = self.sta.status("rssi")
        except Exception:
          pass
      if self.buffer:
        d["buffered"] = self.buffer.pending()
      body = json.dumps(d).encode("utf-8")
    except Exception as e:
      log("push: could not build payload:", e)
      return
    ts, clk = self.wall()
    if not (self.joined and self.edges):
      self._keep(ts, clk, d)
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
          self._save_clock(int(reply["ts"]), up)
        if self.buffer and self.buffer.pending():
          self._drain(host, int(port or 8080))
        return
      log("push:", target, "answered", status)
    except Exception as e:
      if self.edge_ok:
        log("push:", target, "unreachable (" + str(e) + "), trying the next Burrow next minute")
    self.edge_ok = False
    self._edge_i += 1
    self._keep(ts, clk, d)
    # retry sooner than a full minute while hunting for a Burrow
    self._push_due = up + (15 if len(self.edges) > 1 else PUSH_EVERY_S)

  def _keep(self, ts, clk, d):
    if not self.buffer:
      return
    try:
      self.buffer.add(ts, clk, self.boot, d)
    except Exception as e:
      log("buffer: could not keep the row:", e)

  def _drain(self, host, port):
    """Hand the Burrow the backlog, oldest first, a few batches a tick."""
    import gc
    for _ in range(BUF_BATCHES_PER_TICK):
      name, start, rows = self.buffer.batch(BUF_BATCH)
      if not rows:
        return
      ts, clk = self.wall()
      body = {"id": self.uid, "name": self.name, "boot": self.boot, "now": ts, "clk": clk, "rows": rows}
      if self.bin:
        body["bin"] = self.bin
      n = len(rows)
      try:
        status, reply = _http_post_json(host, port, "/ingest/batch", json.dumps(body).encode("utf-8"), timeout=10)
      except Exception as e:
        log("buffer: batch failed:", e)
        return
      finally:
        body = rows = None
        gc.collect()
      if status != 200 or not reply or not reply.get("ok"):
        log("buffer: Burrow refused a batch:", status, reply)
        return
      self.buffer.ack(name, start + n)
      log("buffer: %d rows delivered (%d kept, %d dup, %d unplaceable), %d to go"
          % (n, reply.get("n", 0), reply.get("dup", 0), reply.get("dropped", 0), self.buffer.pending()))
      feed()

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
        self.server.settimeout(0)   # accept() returns at once: the loop (screen, shows) never waits on it
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
    octet of its address (the bin number, on either network), or its
    PicoLab number for a board with no card on its own hotspot (join
    that SSID). StatusLight blinks it."""
    if self.joined or self.num:
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
          "Browse: http://" + self.ip,
      ]
      if self.rescue_target:
        lines.append("Rescue net: " + self.rescue_target)
      banner(title, lines)

  def pin(self):
    """This board's PIN right now (it changes with the name and the address)."""
    return pin_for(self.name, self.ip)

  def _pin_ok(self, req):
    """True if the request carries the right PIN. Five misses in a row
    lock every gated route for a minute (a 3-4 digit PIN is small)."""
    up = uptime_s()
    if up < self._pin_locked_until:
      return False
    if query_str(req, "pin") == self.pin():
      self._pin_fails = 0
      return True
    self._pin_fails += 1
    if self._pin_fails >= PIN_MAX_FAILS:
      self._pin_fails = 0
      self._pin_locked_until = up + PIN_LOCK_S
      log("PIN: %d wrong in a row, locked for %d s" % (PIN_MAX_FAILS, PIN_LOCK_S))
    return False

  def _rename(self, req):
    """/name?name=New%20Name: write name.txt and restart in 2 s. The new
    name is the new hotspot and the new PIN, so the page says so."""
    new = (query_str(req, "name") or "").strip()
    if not (1 <= len(new) <= 24) or any(ord(c) < 32 or ord(c) > 126 for c in new):
      return {"error": "name: 1-24 plain characters"}
    with open(NAME_FILE, "w") as f:
      f.write(new)
    self._restart_at = uptime_s() + 2
    log("renamed to '%s' from the web; restarting" % new)
    return {"ok": True, "name": new, "restart_s": 2}

  def poll(self, data_fn, routes=None):
    """Serve one pending request, if any. Never raises.

    data_fn() -> dict, served as JSON at /data.
    routes: optional list of (prefix, handler); handler(req) -> dict,
    also served as JSON. Use for actions like /set?angle=90. Every
    route (and the built-in /name) needs ?pin=<the board's PIN>, see
    pin_for(); reading (/data, /history, the page) never does. USB
    (Viper, mpremote) is not gated: plugging in IS the key.
    """
    if self._restart_at is not None and uptime_s() >= self._restart_at:
      try:
        self.close()
      except Exception:
        pass
      machine.reset()
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
      gated = list(routes or []) + [("/name", self._rename)]
      for prefix, handler in gated:
        if (b"GET " + prefix.encode()) in req or (b"POST " + prefix.encode()) in req:
          if not self._pin_ok(req):
            cl.sendall(HEADER_403 + b'{"error":"pin","locked":%s}' % (b"true" if uptime_s() < self._pin_locked_until else b"false"))
            handled = True
            break
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
