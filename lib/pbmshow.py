"""Shows the kids make: pictures and little videos for the 128x64 OLED.

A show file is a PBM ("portable bitmap", the black-and-white netpbm format)
in the board's shows/ folder: one frame is a picture, several frames one
after another in the same file are a video. Each frame is

    P4
    # fps 10          (optional, first frame only: video speed, 1-20)
    # hold 3000       (optional, first frame only: ms the last frame stays up)
    128 64
    <1024 bytes: 8 pixels a byte, left to right, top row first, 1 = lit>

At most 128 x 64 (a smaller picture is centred) and MAX_FRAMES frames.
docs/shows.html turns a PNG or an animated GIF into one, with a preview.

shows.txt on the board picks what plays and in what order, one per line:
a built-in show's name (any case, e.g. "Wormhole" or "worm party") or a
file in shows/ ("cat" or "cat.pbm"). Lines starting with # are notes.
No shows.txt: every built-in show, then every file in shows/, A to Z.

    import pbmshow, wormshow
    display.shows = pbmshow.playlist(wormshow.SHOWS)
"""
import framebuf

SHOW_DIR = "shows"
LIST_FILE = "shows.txt"
MAX_W, MAX_H = 128, 64
MAX_FRAMES = 100
DEFAULT_FPS = 10
PICTURE_HOLD_MS = 4000      # a one-frame show (a picture) stays up this long
VIDEO_HOLD_MS = 600         # a video's last frame lingers this long


def _log(*a):
  try:
    from picolab import log
    log(*a)
  except Exception:
    print(*a)


def _token(f, notes):
  """The next whitespace-separated header token; '# key value' comments go into notes."""
  tok = b""
  while True:
    c = f.read(1)
    if not c:
      return tok or None
    if c == b"#":
      line = b""
      while True:
        c = f.read(1)
        if not c or c == b"\n":
          break
        line += c
      parts = line.strip().split()
      if len(parts) >= 2:
        notes.setdefault(parts[0].decode().lower(), parts[1].decode())
      if tok:
        return tok
      continue
    if c in b" \t\r\n":
      if tok:
        return tok
      continue
    tok += c


def scan(path):
  """(w, h, [data offsets], notes) of a PBM show file; raises ValueError if it is not one."""
  offsets, notes, size = [], {}, None
  with open(path, "rb") as f:
    while True:
      magic = _token(f, notes)
      if magic is None:
        break
      if magic != b"P4":
        raise ValueError("not a P4 PBM (frame %d starts %r)" % (len(offsets) + 1, magic[:8]))
      try:
        w, h = int(_token(f, notes)), int(_token(f, notes))
      except (TypeError, ValueError):
        raise ValueError("bad size in frame %d" % (len(offsets) + 1))
      if not (0 < w <= MAX_W and 0 < h <= MAX_H):
        raise ValueError("%dx%d is bigger than %dx%d" % (w, h, MAX_W, MAX_H))
      if size and size != (w, h):
        raise ValueError("frame %d is %dx%d, the first was %dx%d" % (len(offsets) + 1, w, h, size[0], size[1]))
      size = (w, h)
      offsets.append(f.tell())          # the single whitespace after the height was eaten by _token
      n = ((w + 7) // 8) * h
      f.seek(n, 1)
      if len(offsets) > MAX_FRAMES:
        raise ValueError("more than %d frames" % MAX_FRAMES)
    if offsets:
      f.seek(0, 2)
      if f.tell() < offsets[-1] + ((size[0] + 7) // 8) * size[1]:
        raise ValueError("the last frame is cut short")
  if not offsets:
    raise ValueError("empty file")
  return size[0], size[1], offsets, notes


class PbmShow:
  """One show file, played like a built-in show (frames, draw(o, t), name, fps, hold_ms)."""

  def __init__(self, path, name=None):
    self.path = path
    self.w, self.h, self._offsets, notes = scan(path)
    self.frames = len(self._offsets)
    self.name = name or path.split("/")[-1].rsplit(".", 1)[0]
    try:
      self.fps = max(1, min(20, int(notes.get("fps", DEFAULT_FPS))))
    except ValueError:
      self.fps = DEFAULT_FPS
    try:
      self.hold_ms = max(0, min(30000, int(notes.get("hold", 0)))) or (
          PICTURE_HOLD_MS if self.frames == 1 else VIDEO_HOLD_MS)
    except ValueError:
      self.hold_ms = PICTURE_HOLD_MS if self.frames == 1 else VIDEO_HOLD_MS
    self._buf = bytearray(((self.w + 7) // 8) * self.h)
    self._fb = framebuf.FrameBuffer(self._buf, self.w, self.h, framebuf.MONO_HLSB)

  def draw(self, o, t):
    with open(self.path, "rb") as f:
      f.seek(self._offsets[t])
      f.readinto(self._buf)
    o.blit(self._fb, (MAX_W - self.w) // 2, (MAX_H - self.h) // 2)


class ShowFile:
  """A show file in a playlist: the Display starts it like a show class (ShowFile() makes
  the PbmShow). Scanned once here, so a broken file is reported at boot and left out.
  (A class, not a closure: MicroPython functions take no attributes.)"""

  def __init__(self, path, name=None):
    probe = PbmShow(path, name)
    self.path, self.name, self.frames = path, probe.name, probe.frames

  def __call__(self):
    return PbmShow(self.path, self.name)


def _files(show_dir):
  try:
    import os
    return sorted(n for n in os.listdir(show_dir) if n.lower().endswith(".pbm"))
  except OSError:
    return []


def _key(s):
  return "".join(c for c in s.lower() if c.isalpha() or c.isdigit())   # MicroPython str has no isalnum


def playlist(builtins=(), list_file=LIST_FILE, show_dir=SHOW_DIR):
  """The shows to play, in order: built-in classes and show files (see the module doc).
  Anything named in shows.txt that is not found, or a file that is not a valid show,
  is logged and skipped; it never stops the board."""
  by_name = {}
  for cls in builtins:
    by_name[_key(cls.__name__)] = cls
    by_name[_key(getattr(cls, "name", cls.__name__))] = cls
  files = _files(show_dir)
  by_file = {_key(n.rsplit(".", 1)[0]): n for n in files}
  try:
    with open(list_file) as f:
      wanted = [l.strip() for l in f.read().split("\n")]
    wanted = [w for w in wanted if w and not w.startswith("#")]
  except OSError:
    wanted = None
  out = []
  if wanted is None:
    out = list(builtins)
    entries = [(n, None) for n in files]
  else:
    entries = []
    for w in wanted:
      k = _key(w[:-4] if w.lower().endswith(".pbm") else w)
      if k in by_file:
        entries.append((by_file[k], len(out) + len(entries)))
      elif k in by_name:
        entries.append((by_name[k], len(out) + len(entries)))
      else:
        _log("shows.txt: no show called %r (built-in or shows/%s.pbm)" % (w, w))
  for item, _ in entries:
    if isinstance(item, str):
      try:
        out.append(ShowFile(show_dir + "/" + item))
      except (OSError, ValueError) as e:
        _log("%s/%s skipped: %s" % (show_dir, item, e))
    else:
      out.append(item)
  return out
