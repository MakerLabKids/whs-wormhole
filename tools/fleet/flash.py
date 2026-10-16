#!/usr/bin/env python3
"""flash.py: hand every new Pico its firmware, the worm-bin project, and a team card.

  tools/fleet/flash.py --init            # build roster.csv from names.txt + fleet.json (once)
  tools/fleet/flash.py                   # the desk loop: plug a board in, it gets flashed, next
  tools/fleet/flash.py --check           # show what a plugged-in board thinks it is
  tools/fleet/flash.py --dry-run         # walk the loop without touching any board

Per board: wait for it (BOOTSEL drive or a MicroPython serial port), copy the
.uf2 if it is in BOOTSEL, wipe the filesystem (tools/wipe.py), copy the
project files listed in the project's package.json, write wifi.json /
bin.json / name.txt from the next free roster line, record the board's uid
in roster.csv, reset, print the team name. A board whose uid is already in
the roster keeps its team (re-flash of a test unit).

Needs: python3, mpremote on PATH (pipx install mpremote). The Wi-Fi password
is NOT in the repo: it is asked once and kept in ~/.config/wormhole/.
"""
import argparse
import csv
import datetime
import getpass
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ROSTER = os.path.join(HERE, "roster.csv")
FIELDS = ["team", "period", "bin", "room", "uid", "flashed_at", "version", "notes"]


# ---------------------------------------------------------------- config ----
def load_fleet():
    with open(os.path.join(HERE, "fleet.json")) as f:
        return json.load(f)


def wifi_password(fleet, ask=True):
    path = os.path.expanduser(fleet.get("password_file", "~/.config/wormhole/wifi-password"))
    env = os.environ.get("WORMHOLE_WIFI_PASSWORD")
    if env:
        return env
    try:
        with open(path) as f:
            pw = f.read().strip()
            if pw:
                return pw
    except OSError:
        pass
    if not ask:
        return None
    pw = getpass.getpass("WormHole Wi-Fi password (saved to %s): " % path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(pw + "\n")
    os.chmod(path, 0o600)
    return pw


def names():
    out = []
    with open(os.path.join(HERE, "names.txt")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


# ---------------------------------------------------------------- roster ----
def read_roster():
    if not os.path.exists(ROSTER):
        return []
    with open(ROSTER, newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_roster(rows):
    tmp = ROSTER + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    os.replace(tmp, ROSTER)


def init_roster(fleet, force=False):
    if os.path.exists(ROSTER) and not force:
        sys.exit("roster.csv exists; use --init --force to rebuild it (uids would be lost)")
    pool = names()
    rows = []
    i = 0
    for room, spec in sorted(fleet["rooms"].items(), key=lambda kv: int(kv[0])):
        periods = spec["periods"]
        per_period = [spec["bins"] // len(periods) + (1 if k < spec["bins"] % len(periods) else 0)
                      for k in range(len(periods))]
        for period, n in zip(periods, per_period):
            for b in range(1, n + 1):
                if i >= len(pool):
                    sys.exit("names.txt has only %d names; add more" % len(pool))
                rows.append({"team": pool[i], "period": period, "bin": b, "room": int(room),
                             "uid": "", "flashed_at": "", "version": "", "notes": ""})
                i += 1
    write_roster(rows)
    print("roster.csv: %d bins across %d rooms, %d names unused" % (len(rows), len(fleet["rooms"]), len(pool) - i))
    return rows


def pick_row(rows, uid):
    for r in rows:
        if r.get("uid") == uid:
            return r, False
    for r in rows:
        if not r.get("uid"):
            return r, True
    return None, False


# -------------------------------------------------------------- the board ----
class Runner:
    """Shells out to mpremote. --dry-run replaces this with a FakeRunner."""

    def __init__(self, mp="mpremote"):
        self.mp = mp

    def run(self, *args, timeout=60, check=True):
        cmd = [self.mp] + list(args)
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if check and p.returncode != 0:
            raise RuntimeError("%s failed: %s" % (" ".join(cmd[:4]), (p.stderr or p.stdout).strip()[-300:]))
        return p.stdout

    def ports(self):
        """Serial ports that look like a Pico (VID 2e8a)."""
        try:
            out = self.run("connect", "list", timeout=15, check=False)
        except Exception:
            return []
        ports = []
        for line in out.splitlines():
            parts = line.split()
            if parts and ("2e8a" in line.lower() or "micropython" in line.lower()):
                ports.append(parts[0])
        return ports


def bootsel_mounts():
    cands = []
    user = os.environ.get("USER") or os.environ.get("USERNAME") or "*"
    for pat in ("/media/%s/RP2350" % user, "/media/*/RP2350", "/run/media/*/RP2350", "/media/*/RPI-RP2",
                "/run/media/*/RPI-RP2", "/Volumes/RP2350", "/Volumes/RPI-RP2"):
        cands.extend(glob.glob(pat))
    if os.name == "nt":
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            cands.append(letter + ":\\")
    return [c for c in cands if os.path.exists(os.path.join(c, "INFO_UF2.TXT"))]


def project_files(fleet):
    """(local path, remote path) pairs from the project's package.json
    ("fs:lib/picolab.py" <- "github:MakerLabKids/wormhole/lib/picolab.py")."""
    pkg = os.path.join(REPO, fleet["project"], "package.json")
    with open(pkg) as f:
        spec = json.load(f)
    pairs = []
    for remote, src in spec["urls"]:
        remote = remote.split("fs:", 1)[1]
        m = re.match(r"github:[^/]+/[^/]+/(.*)", src)
        local = os.path.join(REPO, m.group(1)) if m else os.path.join(REPO, fleet["project"], src)
        pairs.append((local, remote))
    return pairs


def read_uid(rn, port):
    out = rn.run("connect", port, "exec",
                 "import machine; print(''.join('%02x' % b for b in machine.unique_id()))", timeout=20)
    uid = out.strip().splitlines()[-1].strip()
    if not re.fullmatch(r"[0-9a-f]{16}", uid):
        raise RuntimeError("could not read uid: %r" % out[-200:])
    return uid


def read_version(rn, port):
    try:
        out = rn.run("connect", port, "exec", "import picolab; print(picolab.VERSION)", timeout=20, check=False)
        v = out.strip().splitlines()[-1].strip()
        return v if re.fullmatch(r"\d+\.\d+\.\d+", v) else ""
    except Exception:
        return ""


def put_text(rn, port, remote, text, tmpdir):
    local = os.path.join(tmpdir, os.path.basename(remote))
    with open(local, "w") as f:
        f.write(text)
    rn.run("connect", port, "fs", "cp", local, ":" + remote, timeout=60)


def flash_one(rn, port, fleet, rows, password, dry=False):
    uid = read_uid(rn, port)
    row, is_new = pick_row(rows, uid)
    if row is None:
        raise RuntimeError("roster is full: every line has a uid. Add names/bins and re-run.")
    team = row["team"]
    print("  board %s -> %s (period %s, bin %s, room %s)%s" % (
        uid, team, row["period"], row["bin"], row["room"], "" if is_new else "  [already in roster: re-flash]"))

    if fleet.get("wipe_first", True):
        rn.run("connect", port, "run", os.path.join(REPO, "tools", "wipe.py"), timeout=120)
        print("  wiped")
    # make sure /lib exists, then the project files
    rn.run("connect", port, "exec", "import os\ntry:\n os.mkdir('lib')\nexcept OSError:\n pass", timeout=20)
    for local, remote in project_files(fleet):
        if not os.path.exists(local):
            print("  !! missing %s (skipped)" % local)
            continue
        rn.run("connect", port, "fs", "cp", local, ":" + remote, timeout=120)
    print("  project files copied")

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        put_text(rn, port, "wifi.json", json.dumps({"ssid": fleet["ssid"], "password": password,
                                                    "rescue": fleet.get("rescue", "wormmaster")}) + "\n", td)
        put_text(rn, port, "bin.json", json.dumps({"team": team, "period": int(row["period"]),
                                                   "bin": int(row["bin"]), "room": int(row["room"])}) + "\n", td)
        put_text(rn, port, "name.txt", team + "\n", td)
    version = read_version(rn, port)
    row.update(uid=uid, flashed_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), version=version)
    write_roster(rows)
    try:
        rn.run("connect", port, "reset", timeout=20, check=False)
    except Exception:
        pass
    print("  ✔ %s ready  (picolab v%s)" % (team, version or "?"))
    return row


def check_board(rn, port):
    uid = read_uid(rn, port)
    out = rn.run("connect", port, "exec",
                 "import os, json\n"
                 "def rd(n):\n"
                 "  try:\n    return open(n).read().strip()\n  except Exception:\n    return None\n"
                 "print(json.dumps({'files': os.listdir(), 'name': rd('name.txt'), 'bin': rd('bin.json'), "
                 "'wifi': 'present' if rd('wifi.json') else None}))", timeout=20)
    info = json.loads(out.strip().splitlines()[-1])
    print("uid     %s" % uid)
    print("name    %s" % info["name"])
    print("bin     %s" % info["bin"])
    print("wifi    %s" % info["wifi"])
    print("version %s" % (read_version(rn, port) or "?"))
    print("files   %s" % ", ".join(sorted(info["files"])))


def wait_for_board(rn, fleet, seen_ports, dry=False):
    """Block until a new board shows up. Handles BOOTSEL drives by copying the
    uf2 first. Returns the serial port."""
    uf2 = os.path.join(REPO, fleet["firmware"])
    spinner = "|/-\\"
    i = 0
    while True:
        for m in bootsel_mounts():
            print("\n  BOOTSEL drive at %s: copying %s" % (m, os.path.basename(uf2)))
            if not dry:
                shutil.copy(uf2, os.path.join(m, os.path.basename(uf2)))
            print("  waiting for MicroPython to come up...")
            time.sleep(4)
        ports = [p for p in rn.ports() if p not in seen_ports]
        if ports:
            return ports[0]
        sys.stdout.write("\r  waiting for a board %s " % spinner[i % 4])
        sys.stdout.flush()
        i += 1
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--init", action="store_true", help="create roster.csv from names.txt and fleet.json")
    ap.add_argument("--force", action="store_true", help="with --init: overwrite an existing roster")
    ap.add_argument("--check", action="store_true", help="print what a connected board is")
    ap.add_argument("--port", help="serial port (default: first Pico found)")
    ap.add_argument("--once", action="store_true", help="flash one board and exit")
    ap.add_argument("--dry-run", action="store_true", help="simulate: no mpremote, no files written to a board")
    ap.add_argument("--mp", default=os.environ.get("MP", "mpremote"), help="mpremote executable")
    a = ap.parse_args()
    fleet = load_fleet()

    if a.init:
        init_roster(fleet, force=a.force)
        return 0
    rows = read_roster()
    if not rows:
        sys.exit("no roster.csv yet: run with --init first")

    rn = FakeRunner() if a.dry_run else Runner(a.mp)
    if not a.dry_run and not shutil.which(a.mp):
        sys.exit("mpremote not found. Install: pipx install mpremote  (or pip install --user mpremote)")

    if a.check:
        port = a.port or (rn.ports() or [None])[0]
        if not port:
            sys.exit("no Pico serial port found")
        check_board(rn, port)
        return 0

    password = "dry-run-password" if a.dry_run else wifi_password(fleet)
    done = sum(1 for r in rows if r.get("uid"))
    print("fleet: %d of %d bins flashed so far. Plug in a board (hold BOOTSEL if it is brand new)." % (done, len(rows)))
    seen = set()
    while True:
        port = a.port or wait_for_board(rn, fleet, seen, dry=a.dry_run)
        print("\n  found %s" % port)
        try:
            flash_one(rn, port, fleet, rows, password, dry=a.dry_run)
        except Exception as e:
            print("  !! %s" % e)
            print("  unplug it, try again (BOOTSEL + replug if it will not talk).")
        seen.add(port)
        if a.once or a.port:
            return 0
        print("  unplug it; plug in the next board.")
        # wait until this port goes away so we do not flash it twice
        while port in rn.ports():
            time.sleep(1)
        seen.discard(port)


class FakeRunner(Runner):
    """--dry-run: pretends to be mpremote talking to one imaginary board."""

    def __init__(self):
        super().__init__("mpremote")
        self.calls = []
        self.uid = "e66118604b7c%04x" % int(time.time() % 65536)
        self._present = True

    def run(self, *args, timeout=60, check=True):
        self.calls.append(args)
        joined = " ".join(args)
        if "unique_id" in joined:
            return self.uid + "\n"
        if "picolab.VERSION" in joined:
            return "0.2.0\n"
        if "os.listdir" in joined:
            return json.dumps({"files": ["main.py", "lib"], "name": "Dirt Vader", "bin": "{}", "wifi": "present"}) + "\n"
        if args[:1] == ("connect",) and args[1:2] == ("list",):
            return "/dev/ttyFAKE0 2e8a:0005 MicroPython Board in FS mode\n" if self._present else ""
        if "reset" in args:
            self._present = False
        return ""

    def ports(self):
        return ["/dev/ttyFAKE0"] if self._present else []


if __name__ == "__main__":
    sys.exit(main())
