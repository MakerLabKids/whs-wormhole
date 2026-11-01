"""Kids' shows (PBM pictures/videos + shows.txt): micropython tools/picotest/test_pbmshow.py"""
import sys, os
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import framebuf
import pbmshow

D = "/tmp/pbmshow-test"
try:
  os.mkdir(D)
except OSError:
  pass
for n in os.listdir(D):
  os.remove(D + "/" + n)


def frame(w, h, fill=0, notes=b""):
  return b"P4\n" + notes + b"%d %d\n" % (w, h) + bytes([fill]) * (((w + 7) // 8) * h)


def put(name, data):
  with open(D + "/" + name, "wb") as f:
    f.write(data)


# a picture: one full-screen frame, held 4 s
put("sun.pbm", frame(128, 64, 0xFF))
s = pbmshow.PbmShow(D + "/sun.pbm")
assert (s.w, s.h, s.frames, s.name, s.hold_ms) == (128, 64, 1, "sun", pbmshow.PICTURE_HOLD_MS), (s.w, s.h, s.frames, s.name, s.hold_ms)
buf = bytearray(1024)
o = framebuf.FrameBuffer(buf, 128, 64, framebuf.MONO_HLSB)
s.draw(o, 0)
assert buf == bytearray(b"\xff" * 1024)

# a video: 3 frames, fps and hold from the first frame's comments
put("blink.pbm", frame(128, 64, 0x00, b"# fps 5\n# hold 1500\n") + frame(128, 64, 0xFF) + frame(128, 64, 0x0F))
v = pbmshow.PbmShow(D + "/blink.pbm")
assert (v.frames, v.fps, v.hold_ms) == (3, 5, 1500), (v.frames, v.fps, v.hold_ms)
v.draw(o, 2)
assert buf[0] == 0x0F and buf[1023] == 0x0F
v.draw(o, 0)
assert buf[0] == 0x00
pbmshow.PbmShow(D + "/blink.pbm").fps == 5

# a video with no notes: 10 fps, short hold
put("plain.pbm", frame(128, 64) + frame(128, 64))
p = pbmshow.PbmShow(D + "/plain.pbm")
assert (p.fps, p.hold_ms) == (pbmshow.DEFAULT_FPS, pbmshow.VIDEO_HOLD_MS)

# a small picture is centred: 16 x 8 all lit -> x 56..71, y 28..35
put("dot.pbm", frame(16, 8, 0xFF))
o.fill(0)
pbmshow.PbmShow(D + "/dot.pbm").draw(o, 0)
assert o.pixel(56, 28) == 1 and o.pixel(71, 35) == 1, (o.pixel(56, 28), o.pixel(71, 35))
assert o.pixel(55, 28) == 0 and o.pixel(72, 35) == 0 and o.pixel(56, 27) == 0 and o.pixel(56, 36) == 0

# odd width: rows pad to whole bytes (netpbm), 10 px -> 2 bytes a row
put("odd.pbm", b"P4\n10 2\n" + bytes([0xFF, 0xC0, 0x80, 0x00]))
o.fill(0)
pbmshow.PbmShow(D + "/odd.pbm").draw(o, 0)
assert o.pixel(59, 31) == 1 and o.pixel(68, 31) == 1 and o.pixel(69, 31) == 0 and o.pixel(59, 32) == 1 and o.pixel(60, 32) == 0

# broken files say why
for name, data, why in [
    ("png.pbm", b"\x89PNG\r\n", "not a P4"),
    ("big.pbm", frame(256, 64), "bigger than"),
    ("cut.pbm", frame(128, 64)[:500], "cut short"),
    ("mixed.pbm", frame(128, 64) + frame(64, 32), "the first was"),
    ("many.pbm", frame(8, 1) * (pbmshow.MAX_FRAMES + 1), "more than"),
    ("empty.pbm", b"", "empty"),
]:
  put(name, data)
  try:
    pbmshow.scan(D + "/" + name)
    raise AssertionError(name + " should fail")
  except ValueError as e:
    assert why in str(e), (name, str(e))


class Wormhole:
  name = "Wormhole"
  frames = 100


class WormParty:
  name = "Worm Party"
  frames = 100


# no shows.txt: built-ins first, then every valid file A-Z (broken ones skipped)
pl = pbmshow.playlist([Wormhole, WormParty], list_file=D + "/none.txt", show_dir=D)
names = [getattr(x, "name", None) for x in pl]
assert names == ["Wormhole", "Worm Party", "blink", "dot", "odd", "plain", "sun"], names
show = pl[2]()                       # the Display starts a file show like a class
assert show.frames == 3 and show.fps == 5

# shows.txt picks and orders: any case, spaces, .pbm optional, notes and unknowns skipped
with open(D + "/shows.txt", "w") as f:
  f.write("# our playlist\nSUN.pbm\n\nworm party\nnope\nblink\npng\n")
pl = pbmshow.playlist([Wormhole, WormParty], list_file=D + "/shows.txt", show_dir=D)
assert [x.name for x in pl] == ["sun", "Worm Party", "blink"], [x.name for x in pl]

# an empty list plays nothing (the Display then gives the shows' turn to messages)
with open(D + "/shows.txt", "w") as f:
  f.write("# nothing today\n")
assert pbmshow.playlist([Wormhole], list_file=D + "/shows.txt", show_dir=D) == []

# no shows folder at all: just the built-ins
assert pbmshow.playlist([Wormhole], list_file=D + "/none.txt", show_dir=D + "/missing") == [Wormhole]
print("pbmshow OK")
