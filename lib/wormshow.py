"""Ten animated worm splash screens for the 128x64 OLED.

Each show is a class with a name, a frame count and draw(o, t): draw
frame t (0..frames-1) into the framebuffer o. Everything is framebuf
primitives (ellipse, line, rect, text, pixel), so a frame costs a few
ms on a Pico and the I2C refresh (~25 ms) sets the pace: ~20 fps.

    import wormshow
    wormshow.play(display, loop=True)       # every show, forever
    wormshow.play(display, only="Wormhole") # one of them

SHOWS lists them in order. Demo rendering off-board: tools/gen-splash.py.
"""
import math
import time
import framebuf
import micropython

W, H = 128, 64
ON, OFF = 1, 0


# ---- building blocks ---------------------------------------------------
def dot(o, x, y, r, c=ON):
  o.ellipse(int(x), int(y), int(r), int(r), c, True)


def worm(o, pts, r, head=True, eyes=True, c=ON):
  """A worm along pts (head first): fat round segments, the head a bit
  bigger, two eyes looking the way it goes."""
  for i in range(len(pts) - 1, -1, -1):
    x, y = pts[i]
    rr = r + 1 if (i == 0 and head) else r
    dot(o, x, y, rr, c)
  if eyes and len(pts) > 1 and r >= 2:
    hx, hy = pts[0]
    nx, ny = pts[1]
    dx = 1 if hx >= nx else -1
    ex = hx + dx * (r // 2)
    o.pixel(int(ex), int(hy - r // 2) - 1, OFF)
    o.pixel(int(ex), int(hy + r // 2) - 1, OFF)
    if r >= 4:
      o.pixel(int(ex) + dx, int(hy - r // 2) - 1, OFF)
      o.pixel(int(ex) + dx, int(hy + r // 2) - 1, OFF)


def sine_worm(o, x0, y0, length, segs, amp, phase, r, step=None, heading=1, **kw):
  """A worm whose body is a sine wave: head at (x0, y0), tail trailing
  behind it (to the left when heading=1)."""
  step = step or max(2, length // segs)
  pts = []
  for i in range(segs):
    x = x0 - heading * i * step
    y = y0 + amp * math.sin(phase + i * 0.9)
    pts.append((x, y))
  worm(o, pts, r, **kw)
  return pts


def center_text(o, s, y, c=ON):
  o.text(s, (W - len(s) * 8) // 2, y, c)


def ease(t, n):
  """0..1 over n frames, smooth at both ends."""
  u = min(1.0, max(0.0, t / float(n)))
  return u * u * (3 - 2 * u)


# ---- logos (lib/logos.py: MONO_HLSB bitmaps made by tools/gen-logos.py) --
def logo(which):
  """(FrameBuffer, w, h) of a logo; blit it with o.blit(fb, x, y)."""
  import logos
  w, h, data = getattr(logos, which)
  return framebuf.FrameBuffer(bytearray(data), w, h, framebuf.MONO_HLSB), w, h


@micropython.viper
def _scale(src: ptr8, sw: int, sh: int, dst: ptr8, dw: int, dh: int):
  """Nearest-neighbour resize of a MONO_HLSB bitmap (viper: ~4 ms for a
  full-screen frame on a Pico, where plain Python takes ~100)."""
  ss = (sw + 7) >> 3
  ds = (dw + 7) >> 3
  for dy in range(dh):
    sy = (dy * sh) // dh
    for dx in range(dw):
      sx = (dx * sw) // dw
      if src[sy * ss + (sx >> 3)] & (0x80 >> (sx & 7)):
        dst[dy * ds + (dx >> 3)] |= 0x80 >> (dx & 7)


def blit_scaled(o, data, w, h, cx, cy, s):
  """Draw bitmap data (w x h, MONO_HLSB) centred on (cx, cy) at scale s."""
  if s >= 1:
    o.blit(framebuf.FrameBuffer(bytearray(data), w, h, framebuf.MONO_HLSB), cx - w // 2, cy - h // 2)
    return
  dw, dh = max(1, int(w * s)), max(1, int(h * s))
  buf = bytearray(((dw + 7) >> 3) * dh)
  _scale(data, w, h, buf, dw, dh)
  o.blit(framebuf.FrameBuffer(buf, dw, dh, framebuf.MONO_HLSB), cx - dw // 2, cy - dh // 2)


# ---- the school: the wolverine zooms in, lands with a shake, then the name --
class School:
  name = "Woodstock High"
  frames = 100
  SHAKE = (-3, 3, -2, 2, -1, 1, 0, 0)

  def __init__(self):
    import logos
    self.w, self.h, self.data = logos.WHS

  def draw(self, o, t):
    cx, cy = W // 2, self.h // 2
    if t < 30:
      blit_scaled(o, self.data, self.w, self.h, cx, cy, ease(t, 29))
      return
    dx = self.SHAKE[t - 30] if t < 38 else 0
    blit_scaled(o, self.data, self.w, self.h, cx + dx, cy, 1)
    if t >= 42:
      s = "WOODSTOCK HIGH"
      n = min(len(s), (t - 42) // 2 + 1)
      o.text(s[:n], (W - len(s) * 8) // 2, 56)


# ---- Maker Lab Kids: the gear, flask and rocket, wiped in -----------------
class MakerLab:
  name = "Maker Lab Kids"
  frames = 70

  def __init__(self):
    self.fb, self.w, self.h = logo("MLK")

  def draw(self, o, t):
    x, y = (W - self.w) // 2, (H - self.h) // 2
    o.blit(self.fb, x, y)
    if t < 16:                                  # reveal left to right over 0.8 s
      shown = (t + 1) * self.w // 16
      o.fill_rect(x + shown, y, self.w - shown, self.h, OFF)


# ---- 1. one big worm crossing, with a grin -------------------------------
class BigWorm:
  name = "Big Worm"
  frames = 90

  def draw(self, o, t):
    x = -40 + t * 2.1
    y = 30 + 3 * math.sin(t * 0.25)
    pts = sine_worm(o, x, y, 70, 11, 6, t * 0.35, 5, step=6)
    # a grin under the eyes
    hx, hy = pts[0]
    o.line(int(hx) + 1, int(hy) + 3, int(hx) + 4, int(hy) + 2, OFF)
    if t > 25:
      center_text(o, "WORMHOLE", 50)


# ---- 2. lots of little worms wiggling ------------------------------------
class WormParty:
  name = "Worm Party"
  frames = 100
  SEED = [(9, 8), (40, 5), (77, 10), (112, 6), (22, 24), (60, 20), (98, 26), (8, 42), (46, 38),
          (84, 44), (118, 40), (30, 56), (66, 57), (104, 58), (52, 48)]

  def draw(self, o, t):
    for i, (x, y) in enumerate(self.SEED):
      heading = 1 if i % 2 else -1
      r = 1 + (i % 3 == 0)
      sine_worm(o, x + 3 * math.sin(t * 0.2 + i), y, 12, 5, 2 + (i % 2), t * 0.5 + i * 1.3, r,
                step=3, heading=heading, eyes=r > 1)
    if (t // 10) % 2:
      center_text(o, "wiggle wiggle", 28)


# ---- 3. the wormhole: a tunnel you fall into -----------------------------
class Wormhole:
  name = "Wormhole"
  frames = 100

  def draw(self, o, t):
    cx, cy = 64, 32
    for k in range(7):
      p = ((t * 0.035) + k / 7.0) % 1.0        # 0 = far away, 1 = at the rim
      rx = int(2 + p * p * 70)
      ry = int(1 + p * p * 36)
      if rx > 1:
        o.ellipse(cx, cy, rx, ry, ON)
    # a worm shrinking into the hole
    s = 1 - ease(t, 70)
    r = max(1, int(5 * s))
    pts = []
    for i in range(7):
      pts.append((cx + 20 * s - i * 6 * s, cy - 10 * s + 4 * s * math.sin(t * 0.4 + i)))
    worm(o, pts, r, eyes=r > 1)
    if t > 70:
      o.rect(28, 24, 72, 16, OFF, True)
      center_text(o, "WORM HOLE", 28)


# ---- 4. underground: tunnels and a soil probe ----------------------------
class Underground:
  name = "Underground"
  frames = 110

  def draw(self, o, t):
    # sky, sun, ground line
    dot(o, 110, 7, 5)
    o.hline(0, 15, W, ON)
    for x in range(0, W, 9):                   # grass
      o.vline(x + 2, 12, 3, ON)
    # soil speckle
    for i in range(40):
      o.pixel((i * 37) % W, 18 + (i * 11) % 44, ON)
    # two worms tunnelling, their tunnels left behind as dotted trails
    for w, (y0, ph, sp) in enumerate(((28, 0.0, 1.4), (50, 2.0, 1.0))):
      hx = (t * sp + w * 50) % (W + 30) - 15
      for k in range(0, 40, 4):                # the trail
        tx = hx - k
        ty = y0 + 4 * math.sin(ph + (t * sp - k) * 0.08)
        o.pixel(int(tx), int(ty) - 3, ON)
        o.pixel(int(tx), int(ty) + 3, ON)
      pts = [(hx - i * 4, y0 + 4 * math.sin(ph + (t * sp - i * 4) * 0.08)) for i in range(6)]
      worm(o, pts, 2)
    # the probe: a thermometer stuck in the soil, reading rising
    o.rect(16, 4, 5, 46, ON)
    level = int(40 * ease(t, 60))
    o.rect(17, 49 - level, 3, level, ON, True)
    dot(o, 18, 52, 4)
    o.text("%d.%dC" % (18 + level // 4, (level * 3) % 10), 24, 4)


# ---- 5. the worm pulse (an ECG with a worm for a trace) -----------------
class Pulse:
  name = "Worm Pulse"
  frames = 96

  def trace(self, x):
    """Height of the ECG at horizontal position x (periodic)."""
    p = x % 48
    if p < 20:
      return 0
    if p < 24:
      return (p - 20) * 2
    if p < 28:
      return 8 - (p - 24) * 6
    if p < 32:
      return -16 + (p - 28) * 5
    return 0 if p > 36 else (36 - p)

  def draw(self, o, t):
    o.text("LIVE", 2, 2)
    # five hearts: an earthworm has five pairs of aortic arches, and they
    # squeeze one after another, front to back, so the beat runs along them
    for i in range(5):
      b = 1 if (t - i * 3) % 24 < 4 else 0
      cx = 46 + i * 17
      dot(o, cx - 3, 5, 2 + b)
      dot(o, cx + 3, 5, 2 + b)
      o.ellipse(cx, 8, 5 + b, 3 + b, ON, True)
    base = 38
    sweep = (t * 3) % (W + 40)
    for x in range(W):
      if x < sweep:
        y = base - self.trace(x)
        y2 = base - self.trace(x + 1)
        o.line(x, y, x + 1, y2, ON)
    # the worm IS the pen, riding the trace at the sweep point
    hx = min(sweep, W - 1)
    pts = [(hx - i * 3, base - self.trace(hx - i * 3) - 1) for i in range(6)]
    worm(o, pts, 2)
    o.text("5 hearts, 1 worm", 0, 55)


# ---- 6. compost: scraps fall in, worms come up for dinner ---------------
class Compost:
  name = "Compost"
  frames = 110

  def draw(self, o, t):
    # the pile
    o.ellipse(64, 70, 60, 22, ON, True)
    o.ellipse(64, 70, 60, 22, OFF)
    for i in range(30):
      o.pixel((i * 23) % 100 + 14, 52 + (i * 7) % 12, OFF)
    # falling scraps: an apple core and a peel, one after the other
    for k, (x0, delay) in enumerate(((40, 0), (84, 35))):
      f = t - delay
      if 0 <= f < 40:
        y = -8 + f * 1.6
        if k == 0:
          o.ellipse(x0, int(y), 3, 5, ON)       # core
          o.vline(x0, int(y) - 7, 3, ON)        # stalk
        else:
          o.line(x0 - 6, int(y), x0, int(y) + 6, ON)   # peel
          o.line(x0, int(y) + 6, x0 + 6, int(y), ON)
    # worms surfacing: heads poke up, bob, dive
    for i, x in enumerate((28, 52, 76, 100)):
      f = t - 20 - i * 12
      if f < 0:
        continue
      up = 16 * math.sin(min(f, 60) * 0.1) if f < 62 else 0
      if up > 0:
        # a wiggly S poking out of the pile, head waving
        pts = [(x + 3 * math.sin(f * 0.3 + k * 1.2), 52 - up + k * 4) for k in range(4)]
        worm(o, pts, 2, eyes=True)
    if t > 60 and (t // 8) % 2:
      center_text(o, "nom nom nom", 4)


# ---- 7. zoom in on a worm face ---------------------------------------------
class Face:
  name = "Hello Worm"
  frames = 100

  def draw(self, o, t):
    z = 0.15 + 0.85 * ease(t, 50)              # zoom factor
    cx, cy = 56, 34
    r = int(26 * z)
    # body segments behind the head, going off to the right
    for i in range(1, 5):
      dot(o, cx + int(i * r * 0.9), cy + int(r * 0.25 * math.sin(t * 0.2 + i)), max(1, int(r * 0.85)))
    dot(o, cx, cy, r)
    # eyes (blink every so often)
    blink = (t % 40) in (36, 37)
    ex, ey = int(r * 0.35), int(r * 0.3)
    for sx in (-1, 1):
      if blink:
        o.hline(cx + sx * ex - max(1, r // 6), cy - ey, max(2, r // 3), OFF)
      else:
        dot(o, cx + sx * ex, cy - ey, max(1, r // 6), OFF)
        if r > 10:
          o.pixel(cx + sx * ex + 1, cy - ey - 1, ON)
    # smile: the lower half of an ellipse (its top half painted back over)
    if r > 6:
      my, rx, ry = cy + int(r * 0.25), int(r * 0.5), int(r * 0.3)
      o.ellipse(cx, my, rx, ry, OFF)
      o.rect(cx - rx - 1, my - ry - 1, 2 * rx + 3, ry + 1, ON, True)
      # the eyes sit above the patch; put them back in case the patch brushed them
      for sx in (-1, 1):
        if not blink:
          dot(o, cx + sx * ex, cy - ey, max(1, r // 6), OFF)
          if r > 10:
            o.pixel(cx + sx * ex + 1, cy - ey - 1, ON)
        else:
          o.hline(cx + sx * ex - max(1, r // 6), cy - ey, max(2, r // 3), OFF)
    if t > 55:
      o.rect(84, 6, 42, 22, ON)
      o.rect(85, 7, 40, 20, OFF, True)
      o.text("hi!", 94, 13)
      o.line(84, 20, 78, 26, ON)


# ---- 8. the worm scientist and its data screen ---------------------------
class Scientist:
  name = "Worm Lab"
  frames = 100

  def draw(self, o, t):
    nod = int(2 * math.sin(t * 0.3))
    pts = [(30, 30 + nod), (24, 36), (18, 42), (12, 48), (8, 54)]
    worm(o, pts, 4, eyes=False)
    # glasses
    o.ellipse(27, 28 + nod, 4, 4, ON)
    o.ellipse(27, 28 + nod, 3, 3, OFF, True)
    o.ellipse(36, 28 + nod, 4, 4, ON)
    o.ellipse(36, 28 + nod, 3, 3, OFF, True)
    o.pixel(28, 28 + nod, ON)
    o.pixel(37, 28 + nod, ON)
    o.hline(31, 28 + nod, 2, ON)
    # the little screen on a stand, with live bars
    o.rect(56, 10, 66, 40, ON)
    o.rect(57, 11, 64, 38, OFF, True)
    o.vline(89, 50, 6, ON)
    o.hline(80, 56, 20, ON)
    for i in range(8):
      h = int(14 + 12 * math.sin(t * 0.15 + i * 0.8) + 6 * math.sin(t * 0.05 + i))
      o.rect(60 + i * 8, 47 - h, 5, h, ON, True)
    o.text("DATA", 74, 13)
    if (t // 6) % 2:
      o.text("!", 106, 13)


# ---- 9. the conga line: six worms doing the wave --------------------------
class Conga:
  name = "Conga"
  frames = 120

  def draw(self, o, t):
    for i in range(6):
      x = (t * 1.2 + i * 24) % (W + 30) - 15
      y = 32 + 14 * math.sin(t * 0.25 - i * 0.7)
      pts = [(x - k * 4, y + 2 * math.sin(t * 0.5 + k)) for k in range(4)]
      worm(o, pts, 3)
    if (t // 15) % 2:
      center_text(o, "do the worm", 54)
    else:
      center_text(o, "~ ~ ~ ~ ~ ~", 54)


# ---- 10. radar: sweeping for worms -----------------------------------------
class Radar:
  name = "Worm Radar"
  frames = 120
  BLIPS = [(0.4, 0.5), (1.3, 0.8), (2.1, 0.35), (3.0, 0.9), (4.2, 0.6), (5.1, 0.75), (5.8, 0.45)]

  def draw(self, o, t):
    cx, cy, R = 40, 32, 30
    for r in (10, 20, 30):
      o.ellipse(cx, cy, r, r, ON)
    o.hline(cx - R, cy, 2 * R, ON)
    o.vline(cx, cy - R, 2 * R, ON)
    a = (t * 0.11) % (2 * math.pi)
    o.line(cx, cy, int(cx + R * math.cos(a)), int(cy + R * math.sin(a)), ON)
    o.line(cx, cy, int(cx + R * math.cos(a - 0.15)), int(cy + R * math.sin(a - 0.15)), ON)
    found = 0
    for (ba, bd) in self.BLIPS:
      da = (a - ba) % (2 * math.pi)             # how long since the sweep passed
      if da < 2.5:
        found += 1
        bx, by = cx + R * bd * math.cos(ba), cy + R * bd * math.sin(ba)
        if da < 1.2:
          sine_worm(o, bx + 3, by, 8, 3, 1, t * 0.6, 1, step=3, eyes=False)
        else:
          o.pixel(int(bx), int(by), ON)
    o.text("WORMS", 80, 10)
    o.text("FOUND", 80, 20)
    o.text(" %d" % found, 84, 34)
    if found >= 5 and (t // 5) % 2:
      o.text("!!", 100, 34)


SHOWS = [School, MakerLab, BigWorm, WormParty, Wormhole, Underground, Pulse, Compost, Face, Scientist, Conga, Radar]


def play(display, loop=True, only=None, fps=20, hold_ms=600):
  """Run the shows on a picolab.Display (or anything with .oled). Each
  show runs its frames, holds its last frame a moment, then the next."""
  period = 1000 // fps
  while True:
    for cls in SHOWS:
      if only and cls.name != only and cls.__name__ != only:
        continue
      show = cls()
      if hasattr(display, "oled"):
        if display.oled is None and hasattr(display, "_connect"):
          display._connect()                  # picolab.Display connects lazily, on first use
        o = display.oled
      else:
        o = display
      if o is None:
        time.sleep_ms(500)
        continue
      start = time.ticks_ms()
      for t in range(show.frames):
        t0 = time.ticks_ms()
        o.fill(OFF)
        show.draw(o, t)
        o.show()
        left = period - time.ticks_diff(time.ticks_ms(), t0)
        if left > 0:
          time.sleep_ms(left)
      took = time.ticks_diff(time.ticks_ms(), start)
      print("%s: %d frames in %d ms (%d fps)" % (show.name, show.frames, took, show.frames * 1000 // max(1, took)))
      time.sleep_ms(hold_ms)
    if not loop:
      return
