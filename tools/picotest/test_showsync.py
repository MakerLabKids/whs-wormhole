"""Website shows onto the board: micropython tools/picotest/test_showsync.py"""
import sys, os, json
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import hashlib, binascii
import pbmshow, showsync

D = "/tmp/showsync-test"
LIST = D + "/shows.txt"
SD = D + "/shows"
for p in (D, SD):
  try:
    os.mkdir(p)
  except OSError:
    pass
for d in (SD, D):
  for n in os.listdir(d):
    try:
      os.remove(d + "/" + n)
    except OSError:
      pass


def pbm(fill=0xFF, frames=1):
  return (b"P4\n128 64\n" + bytes([fill]) * 1024) * frames


def sha(b):
  return binascii.hexlify(hashlib.sha256(b).digest()).decode()


# the real fetch(), against a fake socket that answers like the Burrow
class Sock:
  def __init__(self, reply): self.buf, self.sent = reply, b""
  def send(self, b): self.sent += b; return len(b)
  def recv(self, n):
    out, self.buf = self.buf[:n], self.buf[n:]
    return out
  def close(self): pass


body = pbm(0x0F, 2)
dest = SD + "/x.pbm"
s = Sock(b"HTTP/1.0 200 OK\r\nContent-Type: image/x-portable-bitmap\r\n\r\n" + body)
assert showsync.fetch("10.0.0.1", 8080, "/shows/%s.pbm" % sha(body), dest, sha(body), sock=s)
assert open(dest, "rb").read() == body and b"GET /shows/" in s.sent
try:
  showsync.fetch("h", 1, "/p", dest, sha(body), sock=Sock(b"HTTP/1.0 200 OK\r\n\r\n" + body + b"x"))
  raise AssertionError("a tampered file must fail")
except OSError as e:
  assert "sha256" in str(e), e
assert open(dest, "rb").read() == body                       # the good copy stays
assert "x.pbm.part" not in os.listdir(SD)                     # no leftovers
try:
  showsync.fetch("h", 1, "/p", SD + "/y.pbm", "0" * 64, sock=Sock(b"HTTP/1.0 404 Not Found\r\n\r\n{}"))
  raise AssertionError("a 404 must fail")
except OSError as e:
  assert "404" in str(e)
os.remove(dest)

# the sync, with a fake fetcher (the "Burrow")
SERVED = {}
CALLS = []


def fetcher(host, port, path, dest, want):
  CALLS.append(path)
  data = SERVED[want]
  with open(dest, "wb") as f:
    f.write(data)
  return True


class Disp:
  shows = None


class Wormhole:
  name = "Wormhole"; frames = 1


class Party:
  name = "Worm Party"; frames = 1


files = {"a%d" % i: pbm(i + 1) for i in range(5)}
for b in files.values():
  SERVED[sha(b)] = b
with open(SD + "/usb-cat.pbm", "wb") as f:                     # put on with a cable: never touched
  f.write(pbm(0x55))

disp = Disp()
sync = showsync.ShowSync(disp, [Wormhole, Party], show_dir=SD, list_file=LIST, fetcher=fetcher)
assert sync.push_fields() == {"shows_rev": 0}
reply = {"shows": {"rev": 3, "list": ["a4", "Worm Party", "usb-cat"],
                   "files": [{"name": n, "sha256": sha(b), "size": len(b)} for n, b in sorted(files.items())]}}
assert sync.on_reply(reply, ("10.0.0.1", 8080)) is False          # 3 of 5 this push
assert len(CALLS) == showsync.FILES_PER_PUSH and sync.rev == 0
assert sync.on_reply(reply, ("10.0.0.1", 8080)) is True           # the last 2, then done
assert len(CALLS) == 5 and sync.rev == 3 and sync.push_fields() == {"shows_rev": 3}
assert sorted(os.listdir(SD)) == ["a0.pbm", "a1.pbm", "a2.pbm", "a3.pbm", "a4.pbm", "usb-cat.pbm", "web.json"], os.listdir(SD)
assert [x.name for x in disp.shows] == ["a4", "Worm Party", "usb-cat"], [x.name for x in disp.shows]
txt = open(LIST).read()
assert txt.startswith(showsync.WEB_LIST_MARK) and "a4\nWorm Party\nusb-cat\n" in txt

# the same rev again: nothing to do
assert sync.on_reply(reply, ("10.0.0.1", 8080)) is False and len(CALLS) == 5

# a reboot remembers it all
sync = showsync.ShowSync(disp, [Wormhole, Party], show_dir=SD, list_file=LIST, fetcher=fetcher)
assert sync.rev == 3 and sorted(sync.files) == ["a0", "a1", "a2", "a3", "a4"]

# the website deletes a1..a4, changes a0, and goes back to the default list
new_a0 = pbm(0x77)
SERVED[sha(new_a0)] = new_a0
reply = {"shows": {"rev": 4, "list": None, "files": [{"name": "a0", "sha256": sha(new_a0), "size": 1034}]}}
assert sync.on_reply(reply, ("10.0.0.1", 8080)) is True
assert sorted(os.listdir(SD)) == ["a0.pbm", "usb-cat.pbm", "web.json"], os.listdir(SD)
assert open(SD + "/a0.pbm", "rb").read() == new_a0
assert "shows.txt" not in os.listdir(D)                           # it wrote it, so it removes it
assert [x.name for x in disp.shows] == ["Wormhole", "Worm Party", "a0", "usb-cat"], [x.name for x in disp.shows]

# a shows.txt the team wrote by hand is left alone when the website says "default"
with open(LIST, "w") as f:
  f.write("usb-cat\n")
sync.on_reply({"shows": {"rev": 5, "list": None, "files": [{"name": "a0", "sha256": sha(new_a0)}]}}, ("h", 1))
assert open(LIST).read() == "usb-cat\n"

# a failed fetch leaves the rev alone, so the next push tries again
def broken(*a):
  raise OSError("timed out")
sync.fetcher = broken
assert sync.on_reply({"shows": {"rev": 6, "list": None, "files": [{"name": "zz", "sha256": "1" * 64}]}}, ("h", 1)) is False
assert sync.rev == 5
# no Burrow address: wait
assert sync.on_reply({"shows": {"rev": 6, "list": None, "files": [{"name": "zz", "sha256": "1" * 64}]}}) is False
print("showsync OK")
