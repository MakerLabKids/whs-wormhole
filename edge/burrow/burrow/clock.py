"""Clock quality: how much to trust time.time() right now.

  ntp   chrony is synchronised to a source that is not another Burrow
        (internet NTP), or to a Burrow that itself has internet (stratum <= 4).
  peer  chrony agrees with another Burrow, but nobody has an upstream.
  free  no agreement with anyone: time is whatever the RTC / fake-hwclock said.
"""
import ipaddress
import subprocess
import time

from .util import log

_cache = {"at": 0, "clk": "free", "detail": {}}


def _chronyc():
    out = subprocess.run(["chronyc", "-c", "tracking"], capture_output=True, text=True, timeout=3)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    f = out.stdout.strip().split(",")
    # ref id, ref ip, stratum, ref time, offset, ...
    return {"ref": f[1], "stratum": int(f[2]), "offset": float(f[4]) if len(f) > 4 else 0.0,
            "leap": f[-1] if f else ""}


def quality(force=False):
    now = time.monotonic()
    if not force and now - _cache["at"] < 20:
        return _cache["clk"]
    clk = "free"
    detail = {}
    try:
        t = _chronyc()
        detail = t
        ref = t["ref"]
        stratum = t["stratum"]
        if stratum == 0 or stratum >= 16 or ref in ("0.0.0.0", "", "127.127.1.1"):
            clk = "free"
        else:
            private = False
            try:
                private = ipaddress.ip_address(ref).is_private
            except ValueError:
                private = False
            if private and stratum >= 5:
                clk = "peer"              # a Burrow serving its local clock
            else:
                clk = "ntp"
    except Exception as e:
        detail = {"error": str(e)}
    _cache.update(at=now, clk=clk, detail=detail)
    return clk


def detail():
    quality()
    return dict(_cache["detail"], clk=_cache["clk"])


def step_to(unix_ts, reason=""):
    """Hard-set the system clock (used only when we are 'free' and the
    cloud tells us the real time). Needs a sudoers rule for /bin/date."""
    try:
        subprocess.run(["sudo", "-n", "/bin/date", "-u", "-s", "@%d" % int(unix_ts)],
                       capture_output=True, timeout=3, check=True)
        log("clock: stepped to %d (%s)" % (unix_ts, reason))
        quality(force=True)
        return True
    except Exception as e:
        log("clock: step failed:", e)
        return False
