"""Render the worm shows off-board: micropython tools/gen-splash.py [outdir]

Runs lib/wormshow.py against the real driver (a framebuf) under the
MicroPython unix port and writes one raw file per show: 1024 bytes per
frame (128x64 bits, row-major, MSB first). tools/splash-gif.py turns
them into GIFs for the docs.
"""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import ssd1306, wormshow

OUT = (sys.argv[1] if len(sys.argv) > 1 else "docs/img/oled/raw").rstrip("/")


class FakeI2C:
  def writeto(self, *a): pass
  def writeto_mem(self, *a): pass


def main():
  import os
  try:
    os.mkdir(OUT)
  except OSError:
    pass
  o = ssd1306.SSD1306_I2C(128, 64, FakeI2C())
  for cls in wormshow.SHOWS:
    show = cls()
    path = "%s/%s.raw" % (OUT, cls.__name__.lower())
    with open(path, "wb") as f:
      for t in range(show.frames):
        o.fill(0)
        show.draw(o, t)
        row = bytearray(16)
        for y in range(64):
          for i in range(16):
            row[i] = 0
          for x in range(128):
            if o.pixel(x, y):
              row[x >> 3] |= 0x80 >> (x & 7)
          f.write(row)
    print("%-12s %3d frames -> %s" % (cls.name, show.frames, path))


main()
