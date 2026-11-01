# boot.py: the safe switch-over for code updates sent over Wi-Fi.
#
# lib/ota.py downloads a new version into .ota/new/ (every file checked against its sha256)
# and writes ota.json {"pending": {"version", "files"}}, then soft-resets. Here, before main.py:
#   pending -> move the current copies of those files to .ota/prev/, the new ones into place,
#              and start a TRIAL: main.py must call ota confirm (after a minute of running)
#   trial   -> a timer armed now: no confirm within TRIAL_MS, or a third start without one,
#              puts the previous files back, notes the version as failed (never retried),
#              and resets. A crash to the REPL is caught the same way (the timer still fires).
# Only the files of the update are touched: names, shows, messages, calibration, Wi-Fi, the
# buffered readings are other files and never move.
#
# This file imports nothing an update can change (it is the safety net) and is not itself
# updated over Wi-Fi: a reflash brings a new one.
import json
import os

STATE = "ota.json"
STAGE = ".ota/new"
PREV = ".ota/prev"
TRIAL_MS = 5 * 60 * 1000
MAX_STARTS = 2


def _load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(st):
    with open(STATE + ".tmp", "w") as f:
        json.dump(st, f)
    try:
        os.remove(STATE)
    except OSError:
        pass
    os.rename(STATE + ".tmp", STATE)


def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False


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


def _move(src, dst):
    if "/" in dst:
        _makedirs(dst.rsplit("/", 1)[0])
    try:
        os.remove(dst)
    except OSError:
        pass
    os.rename(src, dst)


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


def swap(st):
    p = st.pop("pending")
    missing = [f for f in p["files"] if not _exists(STAGE + "/" + f)]
    if missing:
        st.setdefault("failed", []).append(p["version"])
        st["last_error"] = "staged files missing: %s" % ", ".join(missing[:3])
        _save(st)
        return False
    _rmtree(PREV)
    for f in p["files"]:
        if _exists(f):
            _move(f, PREV + "/" + f)
        _move(STAGE + "/" + f, f)
    _rmtree(STAGE)
    st["trial"] = {"version": p["version"], "files": p["files"], "starts": 1, "prev": st.get("current")}
    _save(st)
    return True


def rollback(st, why):
    t = st.pop("trial")
    for f in t["files"]:
        try:
            os.remove(f)
        except OSError:
            pass
        if _exists(PREV + "/" + f):
            _move(PREV + "/" + f, f)
    _rmtree(PREV)
    st.setdefault("failed", []).append(t["version"])
    st["failed"] = st["failed"][-5:]
    st["last_error"] = "%s: %s" % (t["version"], why)
    _save(st)


def _timeout(_t):
    st = _load()
    if st.get("trial"):
        rollback(st, "not confirmed within %d min" % (TRIAL_MS // 60000))
        import machine
        machine.reset()


def boot(arm=True):
    """Returns what happened: 'swapped', 'trial', 'rolled back', 'ok'."""
    st = _load()
    what = "ok"
    if st.get("pending"):
        what = "swapped" if swap(st) else "ok"
    elif st.get("trial"):
        st["trial"]["starts"] = st["trial"].get("starts", 1) + 1
        if st["trial"]["starts"] > MAX_STARTS:
            rollback(st, "did not confirm in %d starts" % MAX_STARTS)
            return "rolled back"
        _save(st)
        what = "trial"
    if arm and _load().get("trial"):
        try:
            import machine
            global _timer
            _timer = machine.Timer(mode=machine.Timer.ONE_SHOT, period=TRIAL_MS, callback=_timeout)
        except Exception as e:
            print("boot: trial timer not armed:", e)
    return what


if __name__ == "__main__":
    try:
        r = boot()
        if r != "ok":
            print("boot: code update", r, _load().get("trial", {}).get("version", ""))
    except Exception as e:
        print("boot: update check failed:", e)
