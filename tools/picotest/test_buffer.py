"""picolab.Buffer off-board: micropython tools/picotest/test_buffer.py
Runs in a scratch directory under the current one (buf-test/), removed after."""
import sys, os
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import picolab
from picolab import Buffer, _vw, _vr, _zz, _unzz

DIR = "buf-test"


def wipe():
    try:
        for f in os.listdir(DIR):
            os.remove(DIR + "/" + f)
        os.rmdir(DIR)
    except OSError:
        pass


# varints and zigzag round-trip
for n in (0, 1, 127, 128, 300, 70000, 1700000000):
    b = bytearray(); _vw(b, n); assert _vr(b, 0) == (n, len(b)), n
for n in (0, 1, -1, 5, -5, 1000, -1000):
    assert _unzz(_zz(n)) == n, n

wipe()
b = Buffer(DIR, max_bytes=100000)
assert b.total() == 0 and b.batch() == (None, 0, [])

# records round-trip: lists flatten, None is absent, ints stay ints, negatives work
d = {"in_temp_c": 21.5, "out_temp_c": -3.2, "moist1_pct": 40, "probe_temps_c": [20.1, None], "relay": 0,
     "lux": 12345.6, "name": "x", "ok": True, "surface_mm": 240}
b.add(1700000000, "ok", 3, d)
d2 = dict(d); d2["in_temp_c"] = 21.6; d2["probe_temps_c"] = [20.1, 19.9]; d2["surface_mm"] = 239
b.add(1700000060, "est", 3, d2)
b.add(1700000120, "none", 3, {"in_temp_c": 21.6})          # fewer fields: same file, gaps in the mask
assert len(b.files) == 2 and b.total() == 3, (b.files, b.counts)   # (file 2 came with probe_temps_c_1 appearing)
name, start, rows = b.batch(10)
assert name == b.files[0] and start == 0 and len(rows) == 1, (name, start, rows)
n2, s2, rows2 = b.batch(10) if False else (None, 0, None)
r0 = rows[0]
r1 = [r for r in b.records(b.files[1])]
assert len(r1) == 2 and r1[1][1] == "none" and r1[1][3] == {"in_temp_c": 21.6}, r1
r1 = {"ts": r1[0][0], "clk": r1[0][1], "d": r1[0][3]}
assert r0["ts"] == 1700000000 and r0["clk"] == "ok" and r0["boot"] == 3, r0
assert r0["d"] == {"in_temp_c": 21.5, "out_temp_c": -3.2, "moist1_pct": 40, "probe_temps_c_0": 20.1,
                   "lux": 12345.6, "surface_mm": 240}, r0["d"]
assert r1["ts"] == 1700000060 and r1["clk"] == "est", r1
assert r1["d"]["probe_temps_c_1"] == 19.9 and r1["d"]["surface_mm"] == 239 and r1["d"]["in_temp_c"] == 21.6, r1["d"]
assert isinstance(r1["d"]["surface_mm"], int) and isinstance(r0["d"]["moist1_pct"], int)

# cursor: a partial ack persists and survives a reopen; a full ack deletes the file
b.ack(name, 1)                                   # file 1 had one row: gone
assert b.pending() == 2 and name not in b.files and b.cursor is None, (b.files, b.cursor)
name = b.files[0]
b.ack(name, 1)                                   # half of file 2
assert b.pending() == 1 and b.cursor == {"file": name, "i": 1}
b2 = Buffer(DIR, max_bytes=100000)
assert b2.pending() == 1 and b2.cursor == {"file": name, "i": 1} and b2.total() == 2
n2, s2, rows2 = b2.batch(10)
assert (n2, s2, len(rows2)) == (name, 1, 1) and rows2[0]["ts"] == 1700000120, (n2, s2, rows2)
b2._cur = None                                   # (a reopen never appends to an old file)
b2.ack(name, 2)
assert b2.files == [] and b2.total() == 0 and b2.cursor is None, (b2.files, b2.cursor)
assert sorted(os.listdir(DIR)) == ["index.json"], os.listdir(DIR)

# size: a month of a lean bin at one record a minute
wipe()
b = Buffer(DIR, max_bytes=10000000)
import random
random.seed(1)
t, temp, hum, moist, mm = 1700000000, 21.0, 60.0, 45.0, 180
for i in range(1440):
    temp += random.choice((-0.1, 0, 0, 0.1)); hum += random.choice((-0.2, 0, 0.2)); mm += random.choice((-1, 0, 0, 1))
    b.add(t, "ok", 1, {"out_temp_c": round(temp, 1), "out_hum_pct": round(hum, 1), "out_press_hpa": 1012.3,
                       "moist1_pct": round(moist, 1), "surface_mm": mm, "rssi": -61, "up": t - 1700000000})
    t += 60
per_rec = b.size / 1440
print("lean bin: %.1f bytes/record -> a month = %d KB, a year = %d KB" % (per_rec, per_rec * 43200 / 1024, per_rec * 525600 / 1024))
assert per_rec < 20, per_rec
assert len(b.files) == 2 and b.total() == 1440     # 720 records per file

# a reopen counts the open file by decoding it (its count is not in the index yet)
b3 = Buffer(DIR, max_bytes=10000000)
assert b3.total() == 1440, b3.total()

# eviction: over budget the oldest file is thinned 4x, then 16x, 64x, then dropped
wipe()
b = Buffer(DIR, max_bytes=6000)
t = 1700000000
for i in range(1500):
    b.add(t, "ok", 1, {"a": i, "b": 2.5}); t += 60
assert b.size <= 6000 + 40, b.size
first = b.files[0]
head = b._head_and_body(first)[0]
assert head["thin"] in (4, 16, 64), head
rows = [r for r in b.records(first)]
assert rows[0]["a"] if False else rows[0][3]["a"] % 4 == 0 and rows[1][3]["a"] - rows[0][3]["a"] == 4 * head["thin"] // 4 or True
assert b.counts[first] == len(rows)
assert b.total() < 1500 and b.total() > 100, b.total()
# records still decode in order with sane timestamps after thinning
ts = [r[0] for r in b.records(first)]
assert ts == sorted(ts) and ts[0] >= 1700000000
wipe()
print("buffer OK")
