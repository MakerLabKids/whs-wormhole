"""An in-memory stand-in for the Cloudflare Worker's /v1/edge/* API, for tests
and for running a Burrow on a laptop with no cloud. Implements PROTOCOL.md."""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time


class FakeSurface:
    def __init__(self, token="test-token", port=0, captive=False):
        self.token = token
        self.captive = captive
        self.objects = {}        # id -> bytes
        self.castings = {}       # id -> meta (+verified_at, rollups_at)
        self.rollups = {}        # (uid, step, ts) -> data
        self.snapshots = []
        self.events = []
        self.reject_events = False
        self.calls = []
        self.lock = threading.Lock()
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code, obj, ctype="application/json"):
                body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _auth(self):
                return self.headers.get("Authorization") == "Bearer " + outer.token

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def do_GET(self):
                outer.calls.append(("GET", self.path))
                if outer.captive:
                    return self._send(200, b"<html>Please log in</html>", "text/html")
                if not self._auth():
                    return self._send(401, {"error": "unauthorized"})
                if self.path == "/v1/edge/ping":
                    return self._send(200, {"ok": True, "ts": int(time.time())})
                self._send(404, {"error": "nf"})

            def do_POST(self):
                outer.calls.append(("POST", self.path))
                if not self._auth():
                    return self._send(401, {"error": "unauthorized"})
                body = json.loads(self._body() or b"{}")
                with outer.lock:
                    if self.path == "/v1/edge/snapshot":
                        outer.snapshots.append(body)
                        return self._send(200, {"ok": True})
                    if self.path == "/v1/edge/events":
                        if outer.reject_events:
                            return self._send(503, {"ok": False, "error": "try later"})
                        outer.events.extend(body.get("events") or [])
                        return self._send(200, {"ok": True, "n": len(body.get("events") or [])})
                    if self.path == "/v1/edge/rollups":
                        cid = body.get("casting")
                        for r in body.get("rows", []):
                            outer.rollups[(r["uid"], r["step"], r["ts"])] = r["data"]
                        if cid in outer.castings:
                            outer.castings[cid]["rollups_at"] = int(time.time())
                        return self._send(200, {"ok": True, "n": len(body.get("rows", []))})
                    if self.path == "/v1/edge/verify":
                        ver, rol, miss = [], [], []
                        for cid in body.get("ids", []):
                            m = outer.castings.get(cid)
                            obj = outer.objects.get(cid)
                            if not m or obj is None:
                                miss.append(cid)
                                continue
                            if hashlib.sha256(obj).hexdigest() == m["sha256"]:
                                m["verified_at"] = m.get("verified_at") or int(time.time())
                                ver.append(cid)
                            else:
                                miss.append(cid)
                            if m.get("rollups_at"):
                                rol.append(cid)
                        return self._send(200, {"verified": ver, "rollups": rol, "missing": miss})
                self._send(404, {"error": "nf"})

            def do_PUT(self):
                outer.calls.append(("PUT", self.path))
                if not self._auth():
                    return self._send(401, {"error": "unauthorized"})
                if self.path.startswith("/v1/edge/castings/"):
                    cid = self.path.rsplit("/", 1)[1]
                    meta = json.loads(self.headers.get("X-Casting-Meta") or "{}")
                    data = self._body()
                    sha = hashlib.sha256(data).hexdigest()
                    if meta.get("sha256") != sha:
                        return self._send(400, {"ok": False, "error": "hash mismatch"})
                    with outer.lock:
                        outer.objects[cid] = data
                        m = outer.castings.setdefault(cid, dict(meta))
                        m.update(meta)
                        m.setdefault("verified_at", None)
                        m.setdefault("rollups_at", None)
                    return self._send(200, {"ok": True, "sha256": sha})
                self._send(404, {"error": "nf"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.url = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    fs = FakeSurface(port=port)
    print("fake surface on", fs.url, "token: test-token")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
