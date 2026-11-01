"""Code updates over Wi-Fi: micropython tools/picotest/test_ota.py (lib/ota.py + projects/worm-bin/boot.py)"""
import sys, os
HERE = os.getcwd()
sys.path.insert(0, HERE + "/tools/picotest/stubs"); sys.path.insert(0, HERE + "/lib"); sys.path.insert(0, HERE + "/projects/worm-bin")
import hashlib, binascii
import ota
import boot

# ---- carry_config ----
OLD = """# ===== config =====
MOIST_PIN = 26      # on this board
MIC_PIN = None          # not fitted
ELEVATION_M = 330   # Roswell
TEACHER_PIN = "4321"
# ===== end of config ==================================================
ELEVATION_M = 1   # after the config: not a setting
PARTS = [
    bme("in", 0x76),
    # analog_bank(),   # not fitted on this bin
    distance(),
    # lux_meter(),   # not fitted on this bin
]
"""
NEW = """# ===== config =====
MOIST_PIN = None      # capacitive probe AOUT
MIC_PIN = 27          # MAX9814
LIGHT_PIN = 28        # new in this version
ELEVATION_M = 305
TEACHER_PIN = ""
# ===== end of config ==================================================
ELEVATION_M = 2
PARTS = [
    bme("in", 0x76),
    analog_bank(),
    distance(),
    lux_meter(),
    new_sensor(1, (2, 3)),
]
"""
m = ota.carry_config(OLD, NEW)
assert "MOIST_PIN = 26      # on this board" in m
assert "MIC_PIN = None          # not fitted" in m
assert "LIGHT_PIN = 28        # new in this version" in m      # a new setting keeps its default
assert "ELEVATION_M = 330   # Roswell" in m and "ELEVATION_M = 2" in m   # only the config section carries
assert 'TEACHER_PIN = "4321"' in m
assert "    # analog_bank(),   # not fitted on this bin" in m
assert "    # lux_meter(),   # not fitted on this bin" in m
assert "    bme(\"in\", 0x76)," in m and "    distance()," in m and "    new_sensor(1, (2, 3))," in m
assert ota.carry_config(NEW, NEW) == NEW                         # nothing to carry: unchanged

# ---- path rules ----
for p in ("main.py", "index.html", "cal.js", "msg.js", "toc.txt", "lib/picolab.py"):
  assert ota.code_path_ok(p), p
for p in ("boot.py", "bin.json", "wifi.json", "name.txt", "msg.json", "cal.json", "shows/x.pbm", "shows.txt",
          "lib/../bin.json", "/main.py", "lib/sub/x.py", "ota.json", "buf/0.bin"):
  assert not ota.code_path_ok(p), p

# ---- the whole flow, in a temp folder ----
T = "/tmp/ota-test"


def rm(d):
  try:
    for n in os.listdir(d):
      p = d + "/" + n
      if os.stat(p)[0] & 0x4000:
        rm(p)
      else:
        os.remove(p)
    os.rmdir(d)
  except OSError:
    pass


def put(p, data):
  if "/" in p:
    ota._makedirs(p.rsplit("/", 1)[0])
  with open(p, "w") as f:
    f.write(data)


def read(p):
  with open(p) as f:
    return f.read()


def sha(s):
  return binascii.hexlify(hashlib.sha256(s.encode()).digest()).decode()


def setup():
  rm(T)
  os.mkdir(T)
  os.chdir(T)
  put("main.py", OLD)
  put("lib/picolab.py", "VERSION = 'old'\n")
  put("lib/old_only.py", "x = 1\n")
  KIDS = {"bin.json": '{"team": "Dirt Vader", "bin": 37}', "name.txt": "Dirt Vader", "msg.json": '{"slots": []}',
          "cal.json": '{"moist1": [1, 2]}', "wifi.json": '{"ssid": "WormHole"}', "shows/cat.pbm": "P4 cat",
          "shows.txt": "cat\n", "buf/0.bin": "readings", "clock.txt": "1793550000"}
  for p, v in KIDS.items():
    put(p, v)
  return KIDS


def kids_untouched(KIDS):
  for p, v in KIDS.items():
    assert read(p) == v, p


NEWFILES = {"main.py": NEW, "lib/picolab.py": "VERSION = 'new'\n", "lib/ota.py": "# ota\n", "index.html": "<h1>new</h1>",
            "lib/a.py": "a", "lib/b.py": "b"}
SERVED = {sha(v): v for v in NEWFILES.values()}
CALLS = []


def fetcher(host, port, path, dest, want):
  CALLS.append(path)
  with open(dest, "w") as f:
    f.write(SERVED[want])
  return True


RESETS = []
REPLY = {"code": {"version": "abc1234", "files": [{"path": p, "sha256": sha(v), "size": len(v)} for p, v in NEWFILES.items()]}}

KIDS = setup()
o = ota.Ota(fetcher=fetcher, reset=lambda: RESETS.append(1))
assert o.version() == "unknown" and o.push_fields() == {"code": "unknown"}
assert o.on_reply(REPLY, ("10.0.0.1", 8080)) is False                    # 4 of 6 this push
assert len(CALLS) == ota.FILES_PER_PUSH and not RESETS
assert o.on_reply(REPLY, ("10.0.0.1", 8080)) is True and RESETS == [1]   # the last 2, staged, reset
assert len(CALLS) == 6
st = ota._load()
assert st["pending"]["version"] == "abc1234" and sorted(st["pending"]["files"]) == sorted(NEWFILES)
staged_main = read(".ota/new/main.py")
assert "MOIST_PIN = 26" in staged_main and "# analog_bank()" in staged_main and "LIGHT_PIN = 28" in staged_main
kids_untouched(KIDS)
# boot.py switches over and starts a trial
assert boot.boot(arm=False) == "swapped"
assert read("lib/picolab.py") == "VERSION = 'new'\n" and read("index.html") == "<h1>new</h1>"
assert read("lib/old_only.py") == "x = 1\n"                               # not part of the update: left alone
assert "MOIST_PIN = 26" in read("main.py")
assert read(".ota/prev/lib/picolab.py") == "VERSION = 'old'\n"
kids_untouched(KIDS)
o = ota.Ota(fetcher=fetcher, reset=lambda: RESETS.append(1))
assert o.version() == "abc1234" and o.push_fields()["code_trial"] is True
assert o.on_reply(REPLY, ("h", 1)) is False                                 # running it already
assert o.confirm() is True and o.confirm() is False
assert ota._load()["current"] == "abc1234" and "trial" not in ota._load()
assert ".ota" not in os.listdir(".") or "prev" not in os.listdir(".ota")
assert boot.boot(arm=False) == "ok"
kids_untouched(KIDS)

# ---- a version that never confirms rolls back, and is never tried again ----
KIDS = setup()
CALLS.clear(); RESETS.clear()
o = ota.Ota(fetcher=fetcher, reset=lambda: RESETS.append(1))
o.on_reply(REPLY, ("h", 1)); o.on_reply(REPLY, ("h", 1))
assert boot.boot(arm=False) == "swapped"              # start 1
assert boot.boot(arm=False) == "trial"                # start 2 (it crashed, or the power blinked)
assert boot.boot(arm=False) == "rolled back"          # start 3: put the old files back
assert read("lib/picolab.py") == "VERSION = 'old'\n" and read("main.py") == OLD
assert "lib/ota.py" not in [("lib/" + n) for n in os.listdir("lib")] or not True
assert "ota.py" not in os.listdir("lib")               # a file the update added is gone again
st = ota._load()
assert "abc1234" in st["failed"] and "did not confirm" in st["last_error"]
kids_untouched(KIDS)
o = ota.Ota(fetcher=fetcher, reset=lambda: RESETS.append(1))
n = len(CALLS)
assert o.on_reply(REPLY, ("h", 1)) is False and len(CALLS) == n     # never again
assert "did not confirm" in o.push_fields()["code_error"]

# the 5-minute timer path does the same
KIDS = setup()
o = ota.Ota(fetcher=fetcher, reset=lambda: None)
o.on_reply(REPLY, ("h", 1)); o.on_reply(REPLY, ("h", 1))
boot.boot(arm=False)
boot.rollback(boot._load(), "not confirmed within 5 min")
assert read("lib/picolab.py") == "VERSION = 'old'\n"
kids_untouched(KIDS)

# ---- an update that names a data file is refused outright ----
KIDS = setup()
bad = {"code": {"version": "evil", "files": [{"path": "main.py", "sha256": sha(NEW)}, {"path": "bin.json", "sha256": "0" * 64}]}}
o = ota.Ota(fetcher=fetcher, reset=lambda: RESETS.append("evil"))
assert o.on_reply(bad, ("h", 1)) is False
assert "refused" in ota._load()["last_error"] and "evil" not in RESETS
kids_untouched(KIDS)
os.chdir(HERE)
print("ota OK")
