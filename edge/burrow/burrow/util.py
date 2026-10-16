"""Small shared helpers: atomic writes, hashing, time, logging."""
import hashlib
import json
import os
import sys
import threading
import time

_log_lock = threading.Lock()


def log(*parts):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(p) for p in parts)
    with _log_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def now():
    return int(time.time())


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def atomic_write(path, data, mode="wb"):
    """Write a whole file so that a power cut leaves either the old file or
    the new one, never a torn one: temp file, fsync, rename, fsync dir."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, "." + os.path.basename(path) + ".tmp")
    if isinstance(data, str):
        data = data.encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(d)


def atomic_write_json(path, obj):
    atomic_write(path, json.dumps(obj, separators=(",", ":"), sort_keys=True) + "\n")


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def utc_id(ts):
    """'20261016T1415' for a unix time (UTC)."""
    return time.strftime("%Y%m%dT%H%M", time.gmtime(ts))


def utc_day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def metrics(d):
    """Flatten a Bin's dict into {metric: number}: numeric top-level fields,
    lists of numbers as field_i. Booleans, strings, dicts are skipped."""
    out = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        if k in ("ok", "ts"):
            continue
        if is_number(v):
            out[k] = v
        elif isinstance(v, list):
            for i, x in enumerate(v):
                if is_number(x):
                    out["%s_%d" % (k, i)] = x
    return out


class Every:
    """Call-site timer: ready() is True once per period."""

    def __init__(self, period_s, first_now=True):
        self.period = period_s
        self._next = 0 if first_now else time.monotonic() + period_s

    def ready(self):
        t = time.monotonic()
        if t >= self._next:
            self._next = t + self.period
            return True
        return False
