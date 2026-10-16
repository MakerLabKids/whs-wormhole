#!/usr/bin/env python3
"""glinet.py: talk to a GL.iNet 4.x router (GL-SFT1200 Opal) over its JSON-RPC API.

  tools/routers/glinet.py [--host 192.168.8.1] status          # model, firmware, uptime
  tools/routers/glinet.py call <object> <method> ['{"json":...}']   # any ubus call, e.g. call system get_status
  tools/routers/glinet.py login                                # just check the password

The admin password is read from the environment (GLINET_PASSWORD) or from a
"key=value" line in a .env file (GLINET_PASSWORD_ENV_KEY names the key, default
"router_admin"; GLINET_ENV_FILE the file, default /workspace/.env). It is never
printed and never put in a URL.

Login is the stock 4.x handshake: "challenge" gives alg/salt/nonce, the password
is Unix-crypt'ed with "$alg$salt$", and the login hash is
md5("root:" + cipher + ":" + nonce).
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import crypt  # noqa: E402  (deprecated in 3.12, still present; see _crypt below)


class RpcError(RuntimeError):
    pass


class Router:
    def __init__(self, host="192.168.8.1", timeout=10, opener=None):
        self.url = "http://%s/rpc" % host
        self.timeout = timeout
        self.sid = ""
        self._id = 0
        self._open = opener or self._http

    def _http(self, payload):
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:          # 4.x returns JSON-RPC errors as HTTP 500 too
            body = e.read().decode("utf-8", "replace")
            try:
                return json.loads(body)
            except ValueError:
                raise RpcError("HTTP %s: %s" % (e.code, body.strip()[:200]))

    def rpc(self, method, params):
        self._id += 1
        resp = self._open({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        if "error" in resp:
            raise RpcError("%s: %s (%s)" % (method, resp["error"].get("message"), resp["error"].get("code")))
        return resp.get("result")

    def login(self, password, username="root"):
        ch = self.rpc("challenge", {"username": username})
        h = login_hash(password, ch, username)
        res = self.rpc("login", {"username": username, "hash": h})
        self.sid = res["sid"]
        return self.sid

    def call(self, obj, method, params=None):
        return self.rpc("call", [self.sid, obj, method, params or {}])


def _crypt(password, setting):
    return crypt.crypt(password, setting)


def login_hash(password, challenge, username="root"):
    """The GL.iNet 4.x login hash, pure (no network) so it can be tested:
    cipher = crypt(password, "$<alg>$<salt>$"); the hash sent to "login" is
    <hash-method>("<user>:<cipher>:<nonce>"). hash-method is sha256 on 4.x
    (older firmware used md5)."""
    cipher = _crypt(password, "$%s$%s$" % (challenge["alg"], challenge["salt"]))
    algo = {"md5": hashlib.md5, "sha256": hashlib.sha256}.get(
        challenge.get("hash-method", "sha256"), hashlib.sha256)
    return algo(("%s:%s:%s" % (username, cipher, challenge["nonce"])).encode()).hexdigest()


def password_from_env(env_file=None, key=None):
    pw = os.environ.get("GLINET_PASSWORD")
    if pw:
        return pw
    key = key or os.environ.get("GLINET_PASSWORD_ENV_KEY", "router_admin")
    env_file = env_file or os.environ.get("GLINET_ENV_FILE", "/workspace/.env")
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("GLINET_HOST", "192.168.8.1"))
    ap.add_argument("--password-key", default=None, help=".env key holding the admin password")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login")
    sub.add_parser("status")
    c = sub.add_parser("call")
    c.add_argument("object")
    c.add_argument("method")
    c.add_argument("params", nargs="?", default="{}")
    a = ap.parse_args()

    pw = password_from_env(key=a.password_key)
    if pw is None:
        sys.exit("no router password: set GLINET_PASSWORD or put router_admin=... in /workspace/.env")
    r = Router(a.host)
    try:
        r.login(pw)
    except RpcError as e:
        sys.exit("login failed: %s" % e)
    if a.cmd == "login":
        print("login ok (%s)" % a.host)
    elif a.cmd == "status":
        info = r.call("system", "get_info")
        st = r.call("system", "get_status")
        print(json.dumps({"info": info, "status": st}, indent=1))
    elif a.cmd == "call":
        try:
            print(json.dumps(r.call(a.object, a.method, json.loads(a.params)), indent=1))
        except RpcError as e:
            sys.exit(str(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
