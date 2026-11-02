"""A bin's own settings, kept in settings.json on the board and changed from the bin's page.

main.py keeps its config section as the DEFAULTS (what a fresh board runs). This module lays
settings.json over them at power-on: every name in the schema that the file holds, with a value
that passes the check, replaces the default in main.py's globals. The page's Settings card (GET
/settings, behind the board's PIN like every change) lists them, saves one at a time
(?k=NAME&v=VALUE), puts one back to its default (?k=NAME&reset=1) and restarts the board to apply
(?restart=1). Code updates over Wi-Fi never touch settings.json (it is data, not code).

Safety: every value is checked when it is saved (type, range, pins that exist and are free) and
again when it is loaded. And a board that fails to start three times in a row with settings.json
present (each run dying before a minute) parks the file as settings.parked.json and starts on the
defaults; the page offers ?restore=1 to bring it back. So a setting can never brick a bin.

  SETTINGS = settings.Settings(globals(), SCHEMA)     # right after the config section
  ...SETTINGS.app = app ...  ROUTES += [("/settings", SETTINGS.handle)]
  after a minute of running: SETTINGS.started()

A schema row: (NAME, kind, group, help[, lo, hi]). Kinds:
  "num" float, "int" whole number (lo..hi), "bool", "text" (up to hi characters, default 80),
  "pin" a free GP pin, "adc" a GP pin with an ADC (26, 27, 28) or None,
  "parts" a list of part names to leave out (choices from Settings.parts).
"""
import json
import os

FILE = "settings.json"
PARKED = "settings.parked.json"
BOOTS = "settings.boots"
PARK_AFTER = 3
# GP0/GP1 carry the I2C bus (OLED, sensors); GP23-25 and GP29 belong to the Wi-Fi chip on a Pico W.
PINS = [p for p in range(29) if p not in (0, 1, 23, 24, 25)]
ADC_PINS = (26, 27, 28)


def _log(*a):
  try:
    from picolab import log
    log(*a)
  except Exception:
    print(*a)


def _read_json(path):
  try:
    with open(path) as f:
      d = json.load(f)
    return d if isinstance(d, dict) else {}
  except (OSError, ValueError):
    return {}


def _write_json(path, d):
  with open(path + ".tmp", "w") as f:
    json.dump(d, f)
  try:
    os.remove(path)
  except OSError:
    pass
  os.rename(path + ".tmp", path)


def _exists(path):
  try:
    os.stat(path)
    return True
  except OSError:
    return False


class Settings:
  def __init__(self, g, schema, path=FILE, parked=PARKED, boots=BOOTS):
    self.g, self.path, self.parked_path, self.boots_path = g, path, parked, boots
    self.rows = {}
    self.order = []
    for row in schema:
      self.rows[row[0]] = row
      self.order.append(row[0])
    self.defaults = dict((n, g[n]) for n in self.order)
    self.parts = []            # part names for the "parts" kind (main.py fills it in)
    self.app = None            # for the restart (main.py sets it once the web app exists)
    self.parked = False
    self.applied = {}
    n = self._boots() + 1
    if n >= PARK_AFTER and _exists(path):
      try:
        os.remove(parked)
      except OSError:
        pass
      os.rename(path, parked)
      self.parked = True
      n = 0
      _log("settings: %d starts in a row died early: settings.json parked, running on the defaults" % PARK_AFTER)
    self._set_boots(n)
    saved = _read_json(path)
    for name in self.order:
      if name in saved:
        try:
          v = self.check(name, saved[name], saved)
        except ValueError as e:
          _log("settings: %s ignored (%s)" % (name, e))
          continue
        g[name] = v
        self.applied[name] = v
    if self.applied:
      _log("settings:", ", ".join("%s=%r" % kv for kv in sorted(self.applied.items())))

  # ---- the boot counter (cleared after a minute of running) ----
  def _boots(self):
    try:
      with open(self.boots_path) as f:
        return int(f.read().strip() or 0)
    except (OSError, ValueError):
      return 0

  def _set_boots(self, n):
    try:
      with open(self.boots_path, "w") as f:
        f.write(str(n))
    except OSError:
      pass

  def started(self):
    """A minute of running: these settings are fine."""
    self._set_boots(0)

  # ---- checking one value ----
  def check(self, name, raw, others=None):
    """The value for name from raw (a string from the page, or JSON from the file), or ValueError.
    others: the values the other settings will have (pin clashes are checked against them)."""
    if name not in self.rows:
      raise ValueError("no setting " + name)
    row = self.rows[name]
    kind = row[1]
    lo = row[4] if len(row) > 4 else None
    hi = row[5] if len(row) > 5 else None
    if isinstance(raw, str):
      raw = raw.strip()
    if kind == "bool":
      if raw in (True, "1", "true", "True", "on", "yes"):
        return True
      if raw in (False, "0", "false", "False", "off", "no"):
        return False
      raise ValueError("on or off")
    if kind == "text":
      s = str(raw)
      if len(s) > (hi or 80) or any(ord(c) < 32 or ord(c) > 126 for c in s):
        raise ValueError("up to %d plain characters" % (hi or 80))
      return s
    if kind == "parts":
      if isinstance(raw, str):
        raw = [x.strip() for x in raw.split("|") if x.strip()] if raw else []
      if not isinstance(raw, list) or any(not isinstance(x, str) for x in raw):
        raise ValueError("a list of part names")
      if self.parts:
        raw = [x for x in raw if x in self.parts]
      return raw
    if kind in ("pin", "adc"):
      if raw in (None, "", "none", "None") and kind == "adc":
        return None
      try:
        v = int(raw)
      except (TypeError, ValueError):
        raise ValueError("a GP number")
      if kind == "adc" and v not in ADC_PINS:
        raise ValueError("an ADC pin: 26, 27 or 28 (or none)")
      if v not in PINS:
        raise ValueError("GP%d is not free (GP0/1 are I2C, GP23-25 the Wi-Fi chip)" % v)
      vals = self.values()
      if others:
        vals.update(dict((k, others[k]) for k in others if k in self.rows))
      for other in self.order:
        if other != name and self.rows[other][1] in ("pin", "adc") and vals.get(other) == v:
          raise ValueError("GP%d is already %s" % (v, other))
      return v
    try:
      v = float(raw) if kind == "num" else int(raw)
    except (TypeError, ValueError):
      raise ValueError("a number")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
      raise ValueError("between %s and %s" % (lo, hi))
    return v

  def values(self):
    return dict((n, self.g.get(n)) for n in self.order)

  # ---- the page ----
  def listing(self):
    saved = _read_json(self.path)
    out = []
    for n in self.order:
      row = self.rows[n]
      item = {"name": n, "kind": row[1], "group": row[2], "help": row[3],
              "value": saved[n] if n in saved else self.defaults[n], "default": self.defaults[n],
              "running": self.g.get(n), "changed": n in saved}
      if len(row) > 4:
        item["lo"] = row[4]
      if len(row) > 5:
        item["hi"] = row[5]
      if row[1] == "parts":
        item["choices"] = self.parts
      out.append(item)
    return {"settings": out, "parked": _exists(self.parked_path),
            "pending": any(saved.get(n, self.defaults[n]) != self.g.get(n) for n in self.order)}

  def handle(self, req):
    import picolab
    if picolab.query_str(req, "restart"):
      if self.app is not None:
        self.app._restart_at = picolab.uptime_s() + 2
        _log("settings: restart from the web")
      return {"ok": True, "restart_s": 2}
    if picolab.query_str(req, "restore"):
      if not _exists(self.parked_path):
        return {"error": "nothing parked"}
      try:
        os.remove(self.path)
      except OSError:
        pass
      os.rename(self.parked_path, self.path)
      _log("settings: parked settings restored (restart to apply)")
      return dict(self.listing(), ok=True)
    name = picolab.query_str(req, "k")
    if name:
      saved = _read_json(self.path)
      if picolab.query_str(req, "reset"):
        saved.pop(name, None)
      else:
        others = dict(self.values())
        others.update(saved)
        others.pop(name, None)
        try:
          v = self.check(name, picolab.query_str(req, "v", ""), others)
        except ValueError as e:
          return {"error": "%s: %s" % (name, e)}
        if v == self.defaults.get(name):
          saved.pop(name, None)
        else:
          saved[name] = v
      _write_json(self.path, saved)
      _log("settings: %s -> %r (restart to apply)" % (name, saved.get(name, self.defaults.get(name))))
      return dict(self.listing(), ok=True)
    return self.listing()
