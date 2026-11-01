"""Code updates over Wi-Fi for a Bin (the worm-bin project). The admin picks a version on the
website; the Burrow's reply to a push carries {"version", "files": [{"path", "sha256", "size"}]}
when this board runs something else. Ota downloads each file from that Burrow into .ota/new/
(GET /code/<sha256>, checked), a few per push; when all are here it carries this board's settings
into the new main.py (carry_config), writes ota.json "pending" and soft-resets. boot.py swaps the
files in and starts a trial; main.py calls confirm() after a minute of running, or boot.py puts
the old files back (see boot.py). A version that failed is never tried again.

What never changes: anything that is not one of the update's code files (CODE_PATTERNS): the
name and bin settings, shows and shows.txt, messages, calibration, Wi-Fi, buffered readings.
And in main.py, the board's own settings: every NAME = value line of the config section and
which parts are commented out in PARTS carry over into the new main.py.

    ota = Ota(app)                   # app.edge_addr: the Burrow that took the last push
    app.on_reply -> ota.on_reply(r); app.push_extra -> ota.push_fields(); after 60 s -> ota.confirm()
"""
import json
import os

STATE = "ota.json"
STAGE = ".ota/new"
PREV = ".ota/prev"
FILES_PER_PUSH = 4
CONFIG_END = "===== end of config"


def _log(*a):
  try:
    from picolab import log
    log(*a)
  except Exception:
    print(*a)


def code_path_ok(p):
  """Only code is ever replaced: main.py, the board's page and scripts, lib/*.py. Never boot.py
  (the safety net), never data (json, txt other than toc.txt, shows/, anything with ..)."""
  if not isinstance(p, str) or not p or ".." in p or p.startswith("/") or "//" in p:
    return False
  if p in ("main.py", "index.html", "cal.js", "msg.js", "toc.txt"):
    return True
  return p.startswith("lib/") and p.endswith(".py") and p.count("/") == 1


def _load(path=STATE):
  try:
    with open(path) as f:
      return json.load(f)
  except (OSError, ValueError):
    return {}


def _save(st, path=STATE):
  with open(path + ".tmp", "w") as f:
    json.dump(st, f)
  try:
    os.remove(path)
  except OSError:
    pass
  os.rename(path + ".tmp", path)


def _makedirs(d):
  cur = ""
  for part in d.split("/"):
    if not part:
      continue
    cur = cur + "/" + part if cur else part
    try:
      os.mkdir(cur)
    except OSError:
      pass


def _rmtree(d):
  try:
    for name in os.listdir(d):
      p = d + "/" + name
      if os.stat(p)[0] & 0x4000:
        _rmtree(p)
      else:
        os.remove(p)
    os.rmdir(d)
  except OSError:
    pass


def _exists(p):
  try:
    os.stat(p)
    return True
  except OSError:
    return False


# ---- carrying the board's settings into a new main.py ------------------------
def _setting(line):
  """'NAME = value  # note' -> 'NAME' for a config line, else None."""
  s = line.strip()
  if not s or s[0] == "#" or " = " not in s:
    return None
  name = s.split(" = ", 1)[0].strip()
  if name and name[0].isupper() and all(c.isupper() or c.isdigit() or c == "_" for c in name):
    return name
  return None


def _part_call(line):
  """'    bme("in", 0x76),' -> 'bme("in", 0x76)'; '    # bme("in", 0x76),   # not fitted' -> same, off."""
  s = line.strip()
  off = s.startswith("#")
  if off:
    s = s[1:].strip()
  if "(" not in s or not s.split("(", 1)[0].replace("_", "").isalpha():
    return None, off
  depth, end = 0, -1
  for i, c in enumerate(s):
    if c == "(":
      depth += 1
    elif c == ")":
      depth -= 1
      if depth == 0:
        end = i
        break
  if end < 0 or not s[end + 1:].lstrip().startswith(","):
    return None, off
  return s[:end + 1], off


def carry_config(old, new):
  """The new main.py with this board's settings: each NAME = ... line of the old config section
  replaces the same NAME's line in the new one (new names keep their defaults), and every part
  call commented out in the old PARTS list is commented out in the new one."""
  old_lines, new_lines = old.split("\n"), new.split("\n")
  mine = {}
  for line in old_lines:
    if CONFIG_END in line:
      break
    n = _setting(line)
    if n:
      mine[n] = line
  off = set()
  in_parts = False
  for line in old_lines:
    if line.startswith("PARTS"):
      in_parts = True
      continue
    if in_parts:
      if line.strip().startswith("]"):
        break
      call, is_off = _part_call(line)
      if call and is_off:
        off.add(call)
  out, in_config, in_parts = [], True, False
  for line in new_lines:
    if in_config and CONFIG_END in line:
      in_config = False
    if in_config:
      n = _setting(line)
      if n and n in mine:
        line = mine[n]
    if line.startswith("PARTS"):
      in_parts = True
    elif in_parts:
      if line.strip().startswith("]"):
        in_parts = False
      else:
        call, is_off = _part_call(line)
        if call and not is_off and call in off:
          indent = line[:len(line) - len(line.lstrip())]
          line = indent + "# " + line.strip() + "   # not fitted on this bin (kept from before the update)"
    out.append(line)
  return "\n".join(out)


class Ota:
  def __init__(self, app=None, fetcher=None, reset=None, state=STATE, stage=STAGE, root=""):
    self.app = app
    self.fetcher = fetcher
    self.reset = reset
    self.state = state
    self.stage = stage
    self.root = root            # tests run in a temp folder
    self._confirmed = False

  def _p(self, p):
    return self.root + p if self.root else p

  def st(self):
    return _load(self._p(self.state))

  def version(self):
    st = self.st()
    t = st.get("trial")
    return (t and t.get("version")) or st.get("current") or "unknown"

  def push_fields(self):
    st = self.st()
    d = {"code": self.version()}
    if st.get("trial"):
      d["code_trial"] = True
    if st.get("last_error"):
      d["code_error"] = st["last_error"][:80]
    return d

  def confirm(self):
    """The new code ran a minute: keep it (boot.py's timer then finds no trial)."""
    if self._confirmed:
      return False
    st = self.st()
    t = st.get("trial")
    self._confirmed = True
    if not t:
      return False
    st["current"] = t["version"]
    del st["trial"]
    st.pop("last_error", None)
    _save(st, self._p(self.state))
    _rmtree(self._p(PREV))
    _log("code: %s confirmed" % st["current"])
    return True

  def on_reply(self, reply, addr=None):
    c = reply.get("code") if isinstance(reply, dict) else None
    if not isinstance(c, dict) or not isinstance(c.get("version"), str):
      return False
    st = self.st()
    v = c["version"]
    if v == self.version() or v in (st.get("failed") or []) or st.get("pending") or st.get("trial"):
      return False
    files = [f for f in (c.get("files") or []) if isinstance(f, dict) and code_path_ok(f.get("path"))
             and isinstance(f.get("sha256"), str) and len(f["sha256"]) == 64]
    if not files or len(files) != len(c.get("files") or []):
      st["last_error"] = "%s: refused (a file outside the code)" % v
      _save(st, self._p(self.state))
      return False
    addr = addr or (self.app and getattr(self.app, "edge_addr", None))
    if not addr:
      return False
    fetch = self.fetcher
    if fetch is None:
      import showsync
      fetch = showsync.fetch
    staging = st.get("staging") or {}
    if staging.get("version") != v:
      staging = {"version": v, "got": {}}
    got = staging["got"]
    todo = [f for f in files if got.get(f["path"]) != f["sha256"] or not _exists(self._p(self.stage + "/" + f["path"]))]
    for f in todo[:FILES_PER_PUSH]:
      dest = self._p(self.stage + "/" + f["path"])
      _makedirs(dest.rsplit("/", 1)[0])
      try:
        fetch(addr[0], addr[1], "/code/%s" % f["sha256"], dest, f["sha256"])
      except Exception as e:
        _log("code: %s not fetched: %s" % (f["path"], e))
        st["staging"] = staging
        _save(st, self._p(self.state))
        return False
      got[f["path"]] = f["sha256"]
    st["staging"] = staging
    if len(todo) > FILES_PER_PUSH:
      _save(st, self._p(self.state))
      _log("code: %s, %d of %d files here" % (v, len(files) - len(todo) + FILES_PER_PUSH, len(files)))
      return False
    # all here: carry this board's settings into the new main.py, then hand over to boot.py
    paths = [f["path"] for f in files]
    if "main.py" in paths and _exists(self._p("main.py")):
      try:
        with open(self._p("main.py")) as f:
          old = f.read()
        with open(self._p(self.stage + "/main.py")) as f:
          new = f.read()
        with open(self._p(self.stage + "/main.py"), "w") as f:
          f.write(carry_config(old, new))
      except Exception as e:
        _log("code: settings not carried, update skipped:", e)
        st.setdefault("failed", []).append(v)
        st["last_error"] = "%s: could not carry settings (%s)" % (v, e)
        st.pop("staging", None)
        _save(st, self._p(self.state))
        return False
    st.pop("staging", None)
    st["pending"] = {"version": v, "files": paths}
    _save(st, self._p(self.state))
    _log("code: %s staged (%d files); restarting to switch over" % (v, len(paths)))
    (self.reset or _soft_reset)()
    return True


def _soft_reset():
  import machine
  machine.soft_reset()
