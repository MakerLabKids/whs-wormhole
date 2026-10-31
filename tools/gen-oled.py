"""Pixel-exact pictures of what the Pico's OLED shows, for the docs.

    micropython tools/gen-oled.py          -> docs/img/oled/*.svg

Runs the real driver (lib/ssd1306.py, a framebuf) and the real layout code
(picolab.Display) under the MicroPython unix port with the picotest stubs,
so the pictures are the screen, not a drawing of it. Each lit pixel of the
128x64 buffer becomes a run of SVG rectangles on a dark panel.
"""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import picolab, ssd1306

OUT = "docs/img/oled/"
SCALE, PAD = 4, 10
BG, PX, BEZEL = "#0B1220", "#D7F0FF", "#1E293B"


class FakeI2C:
  def writeto(self, *a): pass
  def writeto_mem(self, *a): pass


def display():
  d = picolab.Display()
  d.oled = ssd1306.SSD1306_I2C(128, 64, FakeI2C())
  return d


def svg(o, name):
  W, H = 128 * SCALE + 2 * PAD, 64 * SCALE + 2 * PAD
  parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">' % (W, H, W, H),
           '<rect width="%d" height="%d" rx="12" fill="%s"/>' % (W, H, BEZEL),
           '<rect x="%d" y="%d" width="%d" height="%d" fill="%s"/>' % (PAD, PAD, 128 * SCALE, 64 * SCALE, BG),
           '<g fill="%s">' % PX]
  for y in range(64):
    x = 0
    while x < 128:
      if o.pixel(x, y):
        x0 = x
        while x < 128 and o.pixel(x, y):
          x += 1
        parts.append('<rect x="%d" y="%d" width="%d" height="%d"/>'
                     % (PAD + x0 * SCALE, PAD + y * SCALE, (x - x0) * SCALE, SCALE))
      else:
        x += 1
  parts.append('</g></svg>')
  with open(OUT + name + ".svg", "w") as f:
    f.write("\n".join(parts))
  print("wrote", OUT + name + ".svg")


def main():
  import os
  try:
    os.mkdir(OUT.rstrip("/"))
  except OSError:
    pass
  d = display()
  # the start-up card the worm-bin shows for 3 s (projects/worm-bin/main.py)
  d.show(["   WOODSTOCK", "  HIGH SCHOOL", " Maker Lab Kids", "", " Wormhole v" + picolab.VERSION], title=False)
  svg(d.oled, "startup")
  # a lean bin: one air sensor, a moisture probe, the compaction sensor
  lean = ["The Wrigglers", "AIR: 23.2C 45%", "PRESS: 1028 hPa", "MOIST: 84%", "DIST: 240 mm"]
  d.show(lean)
  svg(d.oled, "data")
  # the marquee, mid-scroll
  d.marquee = "Woodstock High School and Maker Lab Kids - Vermiculture PBL by:"
  d._mq, d._x = True, -8 * d.marquee.index("Maker")
  d._draw()
  svg(d.oled, "marquee")
  d._mq, d._x = False, None
  # a name wider than the screen scrolls instead of holding
  d.show(["The Magnificent Decomposers", "AIR: 23.2C 45%", "MOIST: 84%"])
  d._x = -8 * 4
  d._draw()
  svg(d.oled, "longname")
  d._x = None
  # a full bin: every row, so the rows tighten to fit
  d.show(["Dirt Nerds", "IN: 24.1C 71%", "OUT: 19.0C 46%", "DT: +5.1C", "SOIL: 23.8 22.9",
          "MOIST: 61% 58%", "LIGHT: 2% 14lx"])
  svg(d.oled, "full")
  # a demo with the bar (projects/soil-moisture)
  d.show(["PicoLab-3", "Soil:  61.0 %", "raw:  21880"], bar=0.61)
  svg(d.oled, "bar")


main()
