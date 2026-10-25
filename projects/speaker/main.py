# Speaker demo: play tones and full melodies to the worms through an
# LM386 amp, and watch whether they react. Pairs with the mic ("did the
# sound actually reach the bin?").
#
# The Pico opens a Wi-Fi network named PicoLab<N>. Join it and browse to
# http://192.168.4.1: tap a note, sweep the frequency, pick a built-in
# song, or PASTE YOUR OWN RTTTL ringtone and play it. RTTTL is the old
# Nokia ringtone format; there are thousands online, and kids can write
# their own.
#
# Wiring, the 3 wires to the LM386 amp module (no sound = power/wiring):
#   RED   power  -> VBUS = physical PIN 40 (5V)
#   BLACK ground -> any GND (SHARE it with the Pico)
#   signal       -> the module's IN, from GP18 (physical PIN 24)
#   Speaker      -> the module's two output screw terminals.
# The PWM square-wave tone is LOUD and a little buzzy; turn the module's
# volume pot down to start. For cleaner tones, add a 10k+1k divider on IN.
# Amps gulp current: if the Pico resets when it plays, power the amp from
# its own 5V supply (share ground) or add a big capacitor at the amp.
#
# Boot self-test: a short rising arpeggio, so you know it is wired and
# powered before you touch the web page. Silent on boot = power/wiring.
#
# On the board: main.py, index.html, lib/picolab.py, lib/ssd1306.py.
#
# Project page: https://github.com/MakerLabKids/whs-wormhole/tree/main/projects/speaker

import gc
import time
from machine import Pin, PWM

import picolab

# ===== CONFIG =====
SPEAKER_PIN = 18   # PWM tone out to the LM386 IN; default GP18, physical pin 24
DUTY = 20000       # square-wave "loudness" (0..65535); the amp pot is the real volume
# ==================

spk = PWM(Pin(SPEAKER_PIN))


def tone(freq):
  # freq <= 0 means silence (a rest)
  if freq and freq > 0:
    spk.freq(int(freq))
    spk.duty_u16(DUTY)
  else:
    spk.duty_u16(0)


def silence():
  spk.duty_u16(0)


# ---- notes + RTTTL (ringtone) parsing -------------------------------
_SEMI = {"c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4, "f": 5,
         "f#": 6, "gb": 6, "g": 7, "g#": 8, "ab": 8, "a": 9, "a#": 10, "bb": 10, "b": 11}


def note_freq(name, octave):
  if name == "p":
    return 0
  semi = _SEMI.get(name)
  if semi is None:
    return 0
  midi = (octave + 1) * 12 + semi
  return int(440.0 * (2.0 ** ((midi - 69) / 12.0)))


def parse_rtttl(s):
  """RTTTL string -> list of (freq_hz, duration_ms). Forgiving."""
  try:
    parts = s.split(":")
    if len(parts) == 3:
      _, defaults, notes = parts
    elif len(parts) == 2:
      defaults, notes = parts
    else:
      defaults, notes = "", parts[0]
  except Exception:
    return []
  d, o, b = 4, 6, 63
  for part in defaults.split(","):
    part = part.strip().lower()
    if part.startswith("d="):
      d = int(part[2:] or 4)
    elif part.startswith("o="):
      o = int(part[2:] or 6)
    elif part.startswith("b="):
      b = int(part[2:] or 63)
  whole = 4 * 60000 // max(1, b)   # ms in a whole (4-beat) note
  out = []
  for tok in notes.split(","):
    tok = tok.strip().lower()
    if not tok:
      continue
    i, num = 0, ""
    while i < len(tok) and tok[i].isdigit():
      num += tok[i]
      i += 1
    dur = int(num) if num else d
    note = tok[i] if i < len(tok) else "p"
    i += 1
    if i < len(tok) and tok[i] == "#":
      note += "#"
      i += 1
    octv = o
    if i < len(tok) and tok[i].isdigit():
      octv = int(tok[i])
      i += 1
    ms = whole // max(1, dur)
    if i < len(tok) and tok[i] == ".":
      ms = ms * 3 // 2
    out.append((note_freq(note, octv), ms))
  return out


# A few built-in, public-domain tunes (RTTTL). Kids: add your own here or
# paste one on the web page.
SONGS = {
    "scale": "Scale:d=8,o=5,b=140:c,d,e,f,g,a,b,c6,b,a,g,f,e,d,c",
    "twinkle": "Twinkle:d=4,o=5,b=140:c,c,g,g,a,a,2g,f,f,e,e,d,d,2c",
    "ode": "OdeToJoy:d=4,o=5,b=120:e,e,f,g,g,f,e,d,c,c,d,e,e.,8d,2d",
    "mary": "Mary:d=4,o=5,b=140:e,d,c,d,e,e,2e,d,d,2d,e,g,2g",
    "saints": "Saints:d=4,o=5,b=120:8c,8e,8f,2g,8c,8e,8f,2g,8c,8e,8f,g,e,c,e,2d",
}


def _urldecode(s):
  s = s.replace("+", " ")
  out, i = "", 0
  while i < len(s):
    if s[i] == "%" and i + 2 < len(s):
      try:
        out += chr(int(s[i + 1:i + 3], 16))
        i += 3
        continue
      except Exception:
        pass
    out += s[i]
    i += 1
  return out


def query_str(req, key):
  try:
    text = req.decode() if isinstance(req, bytes) else req
    i = text.index(key + "=") + len(key) + 1
    rest = text[i:]
    end = len(rest)
    for j, ch in enumerate(rest):
      if ch in "& \r\n":
        end = j
        break
    return _urldecode(rest[:end])
  except Exception:
    return None


class Player:
  def __init__(self):
    self.seq, self.idx, self.until = [], 0, 0
    self.playing, self.name = False, ""

  def start(self, seq, name=""):
    self.seq, self.idx, self.name = seq, 0, name
    self.playing = bool(seq)
    self.until = time.ticks_ms()

  def stop(self):
    self.playing = False
    silence()

  def tick(self):
    if not self.playing:
      return
    now = time.ticks_ms()
    if time.ticks_diff(now, self.until) < 0:
      return
    if self.idx >= len(self.seq):
      self.stop()
      return
    freq, ms = self.seq[self.idx]
    self.idx += 1
    tone(freq)
    self.until = time.ticks_add(now, ms)


# ---- state + boot self-test -----------------------------------------
mode = "off"          # off | tone | sweep | song
manual_freq = 440
sweep_f = 200.0
sweep_dir = 1
player = Player()

# rising arpeggio so you know it is alive (before any Wi-Fi)
for f in (523, 659, 784, 1047):
  tone(f)
  time.sleep_ms(120)
silence()


def set_handler(req):
  global mode, manual_freq
  f = picolab.query_int(req, "freq")
  if f is not None:
    manual_freq = max(50, min(4000, f))
    mode = "tone"
    tone(manual_freq)
  if b"sweep=1" in req:
    mode = "sweep"
  if b"stop=1" in req:
    mode = "off"
    player.stop()
    silence()
  song = query_str(req, "song")
  if song and song in SONGS:
    player.start(parse_rtttl(SONGS[song]), song)
    mode = "song"
  rt = query_str(req, "rtttl")
  if rt:
    seq = parse_rtttl(rt)
    if seq:
      name = rt.split(":", 1)[0][:16] or "custom"
      player.start(seq, name)
      mode = "song"
  return data_fn()


def data_fn():
  now_playing = player.name if (mode == "song" and player.playing) else ""
  return {
      "ok": True,
      "ssid": app.ssid,
      "mode": mode,
      "freq": int(manual_freq),
      "playing": now_playing,
      "songs": list(SONGS),
  }


display = picolab.Display()
light = picolab.StatusLight()
light.set_slots([True])
app = picolab.WebApp()
app.index = "speaker/index.html"
heartbeat = picolab.Throttle(5000)
sweeper = picolab.Throttle(15)

app.announce("Speaker Station Active!")
picolab.log("Speaker ready on GP%d. Boot arpeggio done." % SPEAKER_PIN)

while True:
  light.poll()
  player.tick()

  if mode == "sweep" and sweeper.ready():
    sweep_f += sweep_dir * 8
    if sweep_f >= 2000:
      sweep_f, sweep_dir = 2000, -1
    elif sweep_f <= 200:
      sweep_f, sweep_dir = 200, 1
    tone(sweep_f)

  webline = app.ip if app.server else "web off: replug"
  if mode == "song" and player.playing:
    line3 = "song: " + player.name
  elif mode == "sweep":
    line3 = "sweep %d Hz" % int(sweep_f)
  elif mode == "tone":
    line3 = "tone %d Hz" % int(manual_freq)
  else:
    line3 = "quiet"
  display.show([app.ssid, webline, line3, "GP%d -> LM386" % SPEAKER_PIN])

  if heartbeat.ready():
    picolab.log("Speaker mode:", mode)

  app.poll(data_fn, routes=[("/set", set_handler)])
  gc.collect()
