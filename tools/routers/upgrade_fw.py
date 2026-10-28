#!/usr/bin/env python3
"""upgrade_fw.py: flash a local GL.iNet firmware .tar onto an Opal and wait for it to come back.

  tools/routers/upgrade_fw.py --host 192.168.8.1 [--file firmware/routers/sft1200-4.8.3.tar] [--check-only]

The flow is the panel's (tools/routers/README.md, "Firmware upgrade"): multipart POST to
/upload (sid, size, path=/tmp/firmware.img, file), then `upgrade check_firmware_local`,
then `upgrade upgrade_local {keep_config:true}` and a ~4 min reboot. --check-only stops
after the box has verified the file. keep_config keeps the admin password and Wi-Fi.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glinet  # noqa: E402

DEFAULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "firmware", "routers", "sft1200-4.8.3.tar")


def upload(host, sid, path, remote="/tmp/firmware.img", timeout=180):
    data = open(path, "rb").read()
    boundary = "----wormhole%s" % uuid.uuid4().hex
    parts = []
    for name, value in (("sid", sid), ("size", str(len(data))), ("path", remote)):
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, name, value)).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  "Content-Type: application/octet-stream\r\n\r\n" % (boundary, os.path.basename(path))).encode())
    parts.append(data)
    parts.append(("\r\n--%s--\r\n" % boundary).encode())
    body = b"".join(parts)
    req = urllib.request.Request("http://%s/upload" % host, data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")[:300]


def wait_back(host, pw, timeout=420):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(10)
        try:
            r = glinet.Router(host, timeout=5)
            r.login(pw)
            return (r.call("system", "get_info") or {}).get("firmware_version")
        except Exception:
            continue
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="192.168.8.1")
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args()
    pw = glinet.password_from_env(key="router_admin")
    if not pw:
        sys.exit("missing router_admin in .env")
    r = glinet.Router(a.host, timeout=10)
    r.login(pw)
    before = (r.call("system", "get_info") or {}).get("firmware_version")
    print("box %s fw %s; uploading %s (%d bytes)" % (a.host, before, os.path.basename(a.file), os.path.getsize(a.file)))
    print("upload:", upload(a.host, r.sid, a.file))
    r.timeout = 60
    chk = r.call("upgrade", "check_firmware_local", {})
    print("check_firmware_local:", json.dumps(chk)[:300])
    if a.check_only or not chk or not chk.get("version"):
        return 0 if chk and chk.get("version") else 1
    print("upgrade_local:", r.call("upgrade", "upgrade_local", {"keep_config": True, "keep_package": True}))
    print("rebooting; waiting for the box to come back (up to 7 min)")
    after = wait_back(a.host, pw)
    print("box back, fw", after)
    return 0 if after == chk.get("version") else 1


if __name__ == "__main__":
    sys.exit(main())
