"""Shows sent from the website (phase 2 of "make your own show"): keep the board's shows/
folder and shows.txt in step with what the team set on the website.

The Burrow's reply to a push may carry {"rev", "list", "files": [{"name", "sha256", "size"}]}
when the website has something newer than this board. ShowSync fetches each new or changed
file from that Burrow (GET /shows/<sha256>.pbm, streamed to flash, checked against its sha256),
a few per push so the sensors and the screen keep going. When every file is here it removes the
website's files that are no longer listed (only files it got from the website: anything put on
with a USB cable is left alone), writes shows.txt from the website's playlist (or removes the
one it wrote, when the website goes back to "default"), reloads the playlist, and reports the
new rev in the next push (shows_rev). It remembers what came from the website in shows/web.json.

    sync = showsync.ShowSync(display, wormshow.SHOWS, app)
    app.on_reply -> sync.on_reply(reply);  app.push_extra -> sync.push_fields()
"""
import json
import os
import socket

import pbmshow

STATE = pbmshow.SHOW_DIR + "/web.json"
FILES_PER_PUSH = 3
MAX_FILE = 110 * 1024
WEB_LIST_MARK = "# set on the website"


def _log(*a):
  try:
    from picolab import log
    log(*a)
  except Exception:
    print(*a)


def _hex(b):
  import binascii
  return binascii.hexlify(b).decode()


def _exists(p):
  try:
    os.stat(p)
    return True
  except OSError:
    return False


def fetch(host, port, path, dest, sha, timeout=10, sock=None):
  """GET http://host:port/path into dest, streaming, checking sha256. True if it matched."""
  import hashlib
  s = sock or socket.socket()
  tmp = dest + ".part"
  ok = False
  try:
    if sock is None:
      s.settimeout(timeout)
      s.connect(socket.getaddrinfo(host, port)[0][-1])
    req = "GET %s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n\r\n" % (path, host)
    s.send(req.encode())
    head = b""
    while b"\r\n\r\n" not in head:
      c = s.recv(256)
      if not c:
        raise OSError("closed before the headers")
      head += c
      if len(head) > 4096:
        raise OSError("headers too long")
    head, _, rest = head.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    if status != 200:
      raise OSError("HTTP %d" % status)
    h = hashlib.sha256()
    n = 0
    with open(tmp, "wb") as f:
      chunk = rest
      while chunk:
        n += len(chunk)
        if n > MAX_FILE:
          raise OSError("too big")
        h.update(chunk)
        f.write(chunk)
        chunk = s.recv(1024)
    if _hex(h.digest()) != sha:
      raise OSError("sha256 does not match")
    try:
      os.remove(dest)
    except OSError:
      pass
    os.rename(tmp, dest)
    ok = True
  finally:
    s.close()
    if not ok:
      try:
        os.remove(tmp)
      except OSError:
        pass
  return ok


class ShowSync:
  def __init__(self, display, builtins, app=None, show_dir=pbmshow.SHOW_DIR, list_file=pbmshow.LIST_FILE, fetcher=fetch):
    self.display = display
    self.builtins = builtins
    self.app = app
    self.dir = show_dir
    self.list_file = list_file
    self.state_file = show_dir + "/web.json"
    self.fetcher = fetcher
    self.rev = 0
    self.files = {}               # name -> sha256, the files that came from the website
    self.wrote_list = False
    try:
      with open(self.state_file) as f:
        st = json.load(f)
      self.rev = int(st.get("rev") or 0)
      self.files = dict(st.get("files") or {})
      self.wrote_list = bool(st.get("wrote_list"))
    except (OSError, ValueError):
      pass

  def push_fields(self):
    return {"shows_rev": self.rev}

  def _save(self):
    tmp = self.state_file + ".tmp"
    with open(tmp, "w") as f:
      json.dump({"rev": self.rev, "files": self.files, "wrote_list": self.wrote_list}, f)
    try:
      os.remove(self.state_file)
    except OSError:
      pass
    os.rename(tmp, self.state_file)

  def _path(self, name):
    return "%s/%s.pbm" % (self.dir, name)

  def on_reply(self, reply, addr=None):
    s = reply.get("shows") if isinstance(reply, dict) else None
    if not isinstance(s, dict) or not isinstance(s.get("rev"), int) or s["rev"] == self.rev:
      return False
    addr = addr or (self.app and getattr(self.app, "edge_addr", None))
    want = {}
    for f in s.get("files") or []:
      n, sha = f.get("name"), f.get("sha256")
      if isinstance(n, str) and isinstance(sha, str) and pbmshow._key(n) == n.replace("-", "") and 0 < len(n) <= 24:
        want[n] = sha
    try:
      os.mkdir(self.dir)
    except OSError:
      pass
    # 1. fetch what is new or changed, a few per push
    todo = [n for n, sha in want.items() if self.files.get(n) != sha or not _exists(self._path(n))]
    for n in todo[:FILES_PER_PUSH]:
      if not addr:
        return False
      try:
        self.fetcher(addr[0], addr[1], "/shows/%s.pbm" % want[n], self._path(n), want[n])
        self.files[n] = want[n]
        self._save()
        _log("shows: got %s from the website" % n)
      except Exception as e:
        _log("shows: %s not fetched: %s" % (n, e))
        return False
    if len(todo) > FILES_PER_PUSH:
      return False                    # the rest on the next pushes
    # 2. remove the website's files that are gone from it (never the USB ones)
    for n in [n for n in self.files if n not in want]:
      try:
        os.remove(self._path(n))
      except OSError:
        pass
      del self.files[n]
      _log("shows: removed %s (deleted on the website)" % n)
    # 3. the playlist
    lst = s.get("list")
    if isinstance(lst, list):
      with open(self.list_file, "w") as f:
        f.write(WEB_LIST_MARK + " (edit there, or delete this file to play everything)\n")
        for n in lst:
          f.write(str(n)[:40] + "\n")
      self.wrote_list = True
    elif self.wrote_list:
      try:
        os.remove(self.list_file)
      except OSError:
        pass
      self.wrote_list = False
    self.rev = s["rev"]
    self._save()
    # 4. play the new set from the next show on
    try:
      self.display.shows = pbmshow.playlist(self.builtins, self.list_file, self.dir)
    except Exception as e:
      _log("shows: playlist not reloaded:", e)
    _log("shows: now at website revision %d (%d of the website's files)" % (self.rev, len(self.files)))
    return True
