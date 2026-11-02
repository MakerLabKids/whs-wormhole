"""lib/settings.py (a bin's settings.json over main.py's defaults), off-board:
    micropython tools/picotest/test_settings.py
Also checks main.py's schema against its config section, and that a code update
(lib/ota.py carry_config) still carries parts switched off by commenting out."""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import faketime
sys.modules["time"] = faketime
import os
import json
import settings
import picolab

D = "/tmp/picotest-settings"
try:
  os.mkdir(D)
except OSError:
  pass
F, P, B = D + "/settings.json", D + "/settings.parked.json", D + "/settings.boots"
def clean():
  for f in (F, P, B, F + ".tmp"):
    try:
      os.remove(f)
    except OSError:
      pass
def put(d):
  with open(F, "w") as f:
    json.dump(d, f)
def saved():
  try:
    with open(F) as f:
      return json.load(f)
  except OSError:
    return None
SCHEMA = [("FAN", "bool", "Fan", "fan"), ("RUN_S", "int", "Fan", "run", 5, 3600), ("DRY_V", "num", "Soil", "dry", 0, 3.3),
          ("MIC_PIN", "adc", "Pins", "mic"), ("LIGHT_PIN", "adc", "Pins", "light"), ("RELAY_PIN", "pin", "Pins", "relay"),
          ("MARQUEE", "text", "Screen", "marquee", 0, 20), ("NOT_FITTED", "parts", "Parts", "off")]
def fresh():
  return {"FAN": True, "RUN_S": 60, "DRY_V": 2.22, "MIC_PIN": 27, "LIGHT_PIN": 28, "RELAY_PIN": 15, "MARQUEE": "hi", "NOT_FITTED": []}
def mk(g=None):
  g = g if g is not None else fresh()
  return g, settings.Settings(g, SCHEMA, path=F, parked=P, boots=B)

# no file: the defaults, untouched
clean(); g, s = mk()
assert g == fresh() and s.applied == {}, g

# a file: good values apply, bad ones are ignored (and the rest still apply)
clean(); put({"RUN_S": 30, "FAN": False, "DRY_V": 9, "RELAY_PIN": 23, "MIC_PIN": 26, "MARQUEE": "Go worms", "BOGUS": 1})
g, s = mk()
assert g["RUN_S"] == 30 and g["FAN"] is False and g["MIC_PIN"] == 26 and g["MARQUEE"] == "Go worms", g
assert g["DRY_V"] == 2.22 and g["RELAY_PIN"] == 15 and "BOGUS" not in g, g

# the checks
clean(); g, s = mk()
def bad(name, v):
  try:
    s.check(name, v)
  except ValueError:
    return True
  return False
assert s.check("RUN_S", "90") == 90 and bad("RUN_S", "4") and bad("RUN_S", "x")
assert s.check("DRY_V", "1.5") == 1.5 and bad("DRY_V", "3.4")
assert s.check("FAN", "0") is False and s.check("FAN", "on") is True and bad("FAN", "maybe")
assert s.check("MIC_PIN", "none") is None and bad("MIC_PIN", "15") and bad("MIC_PIN", "28"), "28 is the light's"
assert bad("RELAY_PIN", "0") and bad("RELAY_PIN", "1") and bad("RELAY_PIN", "23") and bad("RELAY_PIN", "29") and bad("RELAY_PIN", "27")
assert s.check("RELAY_PIN", "14") == 14
assert s.check("MARQUEE", "") == "" and bad("MARQUEE", "x" * 21) and bad("MARQUEE", "tab\there")
s.parts = ["BME280 in (0x76)", "BME280 out (0x77)"]
assert s.check("NOT_FITTED", "BME280 out (0x77)|nonsense") == ["BME280 out (0x77)"]
assert s.check("NOT_FITTED", "") == []

# the page: list, save, refuse, back to default
class App:
  _restart_at = None
r = s.handle("GET /settings HTTP/1.1")
assert [x["name"] for x in r["settings"]] == [x[0] for x in SCHEMA] and not r["pending"] and not r["parked"], r
r = s.handle("GET /settings?k=RUN_S&v=30 HTTP/1.1")
assert r["ok"] and saved() == {"RUN_S": 30} and r["pending"], (r, saved())
row = [x for x in r["settings"] if x["name"] == "RUN_S"][0]
assert row["value"] == 30 and row["running"] == 60 and row["default"] == 60 and row["changed"], row
r = s.handle("GET /settings?k=RUN_S&v=2 HTTP/1.1")
assert "error" in r and saved() == {"RUN_S": 30}, r
r = s.handle("GET /settings?k=MIC_PIN&v=none HTTP/1.1")
r = s.handle("GET /settings?k=LIGHT_PIN&v=27 HTTP/1.1")
assert r.get("ok") and saved() == {"RUN_S": 30, "MIC_PIN": None, "LIGHT_PIN": 27}, (r, saved())
r = s.handle("GET /settings?k=RELAY_PIN&v=27 HTTP/1.1")
assert "error" in r, "the light is going to GP27 (saved): the relay cannot have it"
r = s.handle("GET /settings?k=RUN_S&reset=1 HTTP/1.1")
assert "RUN_S" not in saved(), saved()
r = s.handle("GET /settings?k=FAN&v=1 HTTP/1.1")
assert "FAN" not in saved(), "saving the default value stores nothing"
r = s.handle("GET /settings?k=MARQUEE&v=Dirt%20Nerds%20rule HTTP/1.1")
assert saved()["MARQUEE"] == "Dirt Nerds rule", saved()
s.app = App()
r = s.handle("GET /settings?restart=1 HTTP/1.1")
assert r["ok"] and s.app._restart_at is not None
g2, s2 = mk()
assert g2["MARQUEE"] == "Dirt Nerds rule" and g2["LIGHT_PIN"] == 27 and g2["MIC_PIN"] is None, g2

# three starts in a row that die before a minute: the file is parked, the defaults run
clean(); put({"RUN_S": 30})
g, s = mk(); assert g["RUN_S"] == 30
g, s = mk(); assert g["RUN_S"] == 30
g, s = mk(); assert g["RUN_S"] == 60 and s.parked and saved() is None, (g, s.parked)
r = s.handle("GET /settings HTTP/1.1"); assert r["parked"]
r = s.handle("GET /settings?restore=1 HTTP/1.1"); assert r["ok"] and saved() == {"RUN_S": 30} and not r["parked"]
g, s = mk(); assert g["RUN_S"] == 30, "restored, and the count started over"
s.started()
g, s = mk(); g, s = mk(); assert g["RUN_S"] == 30, "a minute of running clears the count"
s.started()
clean()
print("settings OK")

# ---- main.py: its schema matches its config section ----
src = open("projects/worm-bin/main.py").read()
cfg = src[src.index("===== CONFIG"):src.index("===== end of config")]
names = {}
for line in cfg.split("\n"):
  t = line.strip()
  if t and t[0] != "#" and " = " in t:
    names[t.split(" = ")[0]] = t.split(" = ", 1)[1].split("#")[0].strip()
a = src.index("SETTINGS = settings.Settings(globals(), ["); b = src.index("\n])", a)
rows = []
for line in src[a:b].split("\n"):
  t = line.strip()
  if t.startswith('("'):
    rows.append(t[2:].split('"')[0])
assert rows and all(n in names for n in rows), [n for n in rows if n not in names]
assert "TEACHER_PIN" not in rows, "the teacher PIN never goes on the page"
print("main.py schema OK (%d settings)" % len(rows))

# ---- a code update still carries parts switched off by commenting out ----
import ota
old = src.replace('    bme("out", 0x77),', '    # bme("out", 0x77),', 1).replace("FAN_RUN_S = 60 ", "FAN_RUN_S = 90 ", 1)
assert old != src
new = ota.carry_config(old, src)
assert '    # bme("out", 0x77),' in new and "FAN_RUN_S = 90 " in new, "carry_config lost a setting or a part"
assert new.count("# bme(") == 1
print("carry_config with settings OK")
