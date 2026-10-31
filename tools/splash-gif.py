"""Raw OLED frames -> animated GIFs (and a PNG of one frame) for the docs.

    python3 tools/splash-gif.py            # docs/img/oled/raw/*.raw -> docs/img/oled/splash-*.gif

Pure Python: a two-colour GIF with LZW, each frame scaled up 3x on a
dark panel, 50 ms per frame (the show's 20 fps), looping forever.
"""
import glob
import os
import struct
import sys
import zlib

RAW = "docs/img/oled/raw"
OUT = "docs/img/oled"
SCALE = 3
BG = (11, 18, 32)
FG = (215, 240, 255)
W, H = 128 * SCALE, 64 * SCALE


def frames_of(path):
  data = open(path, "rb").read()
  n = len(data) // 1024
  for k in range(n):
    f = data[k * 1024:(k + 1) * 1024]
    yield [[(f[y * 16 + (x >> 3)] >> (7 - (x & 7))) & 1 for x in range(128)] for y in range(64)]


def lzw(pixels, min_code_size=2):
  """GIF LZW for an index stream with codes < 2**min_code_size."""
  clear, end = 1 << min_code_size, (1 << min_code_size) + 1
  out = bytearray()
  bitbuf, bitcnt = 0, 0

  def emit(code, size):
    nonlocal bitbuf, bitcnt
    bitbuf |= code << bitcnt
    bitcnt += size
    while bitcnt >= 8:
      out.append(bitbuf & 0xFF)
      bitbuf >>= 8
      bitcnt -= 8

  table = {bytes((i,)): i for i in range(clear)}
  nxt, size = end + 1, min_code_size + 1
  emit(clear, size)
  w = b""
  for p in pixels:
    wc = w + bytes((p,))
    if wc in table:
      w = wc
    else:
      emit(table[w], size)
      if nxt < 4096:
        table[wc] = nxt
        nxt += 1
        if nxt - 1 == (1 << size) and size < 12:
          size += 1
      else:
        emit(clear, size)
        table = {bytes((i,)): i for i in range(clear)}
        nxt, size = end + 1, min_code_size + 1
      w = bytes((p,))
  if w:
    emit(table[w], size)
  emit(end, size)
  if bitcnt:
    out.append(bitbuf & 0xFF)
  return bytes(out)


def gif(path, frames, delay_cs=5):
  with open(path, "wb") as f:
    f.write(b"GIF89a")
    f.write(struct.pack("<HHBBB", W, H, 0x80 | 0x00, 0, 0))   # global colour table, 2 colours
    f.write(bytes(BG) + bytes(FG))
    f.write(b"!\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00")       # loop forever
    for fr in frames:
      idx = bytearray()
      for y in range(H):
        row = fr[y // SCALE]
        for x in range(W):
          idx.append(row[x // SCALE])
      f.write(b"!\xf9\x04" + struct.pack("<BHB", 0x00, delay_cs, 0) + b"\x00")
      f.write(b"," + struct.pack("<HHHHB", 0, 0, W, H, 0))
      f.write(b"\x02")
      data = lzw(idx, 2)
      for i in range(0, len(data), 255):
        chunk = data[i:i + 255]
        f.write(bytes((len(chunk),)) + chunk)
      f.write(b"\x00")
    f.write(b";")


def png(path, fr):
  raw = b"".join(b"\x00" + bytes(c for x in range(W) for c in (FG if fr[y // SCALE][x // SCALE] else BG)) for y in range(H))

  def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
  open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
                         + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def main():
  for raw in sorted(glob.glob(os.path.join(RAW, "*.raw"))):
    name = os.path.basename(raw)[:-4]
    frames = list(frames_of(raw))
    out = os.path.join(OUT, "splash-%s.gif" % name)
    gif(out, frames)
    if len(sys.argv) > 1:                       # a frame PNG for eyeballing: tools/splash-gif.py <frame>
      k = min(int(sys.argv[1]), len(frames) - 1)
      png(os.path.join(sys.argv[2] if len(sys.argv) > 2 else OUT, "%s-%d.png" % (name, k)), frames[k])
    print("%-12s %3d frames -> %s (%d KB)" % (name, len(frames), out, os.path.getsize(out) // 1024))


main()
