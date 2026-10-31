"""The Burrow's HTTP face on :8080. Standard-library ThreadingHTTPServer.

  Bins      POST /ingest
  Viewers   GET  /  (dashboard files)  /api/now  /api/bins  /api/history  /api/status  /live (SSE)
            GET  /live?watch=<uid>[,<uid>]  the same stream plus `event: live` once a second
                 for those Bins (the Burrow polls their /data while this client is connected)
  Peers     GET  /castings  /castings/<id>  /castings/<id>/meta  /health
  Local     GET  /api/events (recent)   POST /api/event (the Opal watchdog reports in; LAN only)
            GET  /api/signal  this Opal's upstream link right now (for the walk-around meter)
"""
import json
import mimetypes
import os
import queue
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import util
from .util import log

PRIVATE_PREFIXES = ("10.", "192.168.", "127.", "172.16.", "172.17.", "172.18.", "172.19.",
                    "172.2", "172.30.", "172.31.")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Burrow/0.1"

    @property
    def svc(self):
        return self.server.svc        # the Service this server belongs to

    # ---- plumbing -------------------------------------------------------
    def log_message(self, fmt, *args):      # quiet; we log what matters ourselves
        pass

    def _json(self, obj, code=200, extra=None):
        body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, data, ctype, code=200, extra=None, cache=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if cache:
            self.send_header("Cache-Control", cache)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > int(self.svc.cfg["max_body"]):
            return None
        return self.rfile.read(n)

    def _via_tunnel(self):
        """Requests arriving through cloudflared carry CF-* headers and must
        present the shared live key. LAN requests carry neither and are open."""
        if not (self.headers.get("CF-Ray") or self.headers.get("CF-Connecting-IP")):
            return False
        return True

    def _authorized(self):
        if not self._via_tunnel():
            return True
        key = self.svc.live_key
        return bool(key) and self.headers.get("X-Burrow-Key") == key

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- routes ---------------------------------------------------------
    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/ingest":
            return self._ingest()
        if path == "/ingest/batch":
            return self._ingest_batch()
        if path == "/api/event":
            return self._event()
        self._json({"error": "not found"}, 404)

    def do_GET(self):
        if not self._authorized():
            return self._json({"error": "forbidden"}, 403)
        u = urllib.parse.urlsplit(self.path)
        path = u.path
        q = urllib.parse.parse_qs(u.query)
        svc = self.svc
        try:
            if path == "/health":
                return self._json({"ok": True, "edge": svc.cfg["edge"], "room": svc.cfg["room"],
                                   "ts": util.now(), "clk": svc.clk(), "version": svc.version})
            if path == "/api/now":
                return self._json(svc.api_now())
            if path == "/api/bins":
                return self._json(svc.api_bins())
            if path == "/api/status":
                return self._json(svc.api_status())
            if path == "/api/history":
                return self._json(svc.api_history(q))
            if path == "/api/signal":
                return self._json(svc.opal.signal())
            if path == "/api/events":
                return self._json({"edge": svc.cfg["edge"], "events": svc.events.recent[-100:], "state": svc.events.state})
            if path == "/api/me":
                return self._json({"ok": True, "role": "local", "name": "classroom", "team": None, "local": True})
            if path == "/live":
                return self._live(q)
            if path == "/castings":
                since = q.get("since", [None])[0]
                since = int(since) if since else None
                return self._json({"edge": svc.cfg["edge"], "castings": svc.store.list_metas(since)})
            if path.startswith("/castings/"):
                rest = path[len("/castings/"):]
                if rest.endswith("/meta"):
                    cid = rest[:-5]
                    m = svc.store.metas.get(cid)
                    return self._json(m) if m else self._json({"error": "unknown casting"}, 404)
                cid = rest
                if not svc.store.has(cid):
                    return self._json({"error": "unknown casting"}, 404)
                data = svc.store.gz_bytes(cid)
                return self._bytes(data, "application/gzip",
                                   extra={"X-Casting-Sha256": svc.store.metas[cid]["sha256"]})
            return self._static(path)
        except BrokenPipeError:
            pass
        except Exception as e:
            log("server: %s %s failed: %r" % (self.command, self.path, e))
            try:
                self._json({"error": str(e)}, 500)
            except Exception:
                pass

    # ---- handlers -------------------------------------------------------
    def _ingest(self):
        body = self._read_body()
        if body is None:
            return self._json({"ok": False, "error": "bad length"}, 400)
        try:
            d = json.loads(body.decode("utf-8"))
            if not isinstance(d, dict):
                raise ValueError("not an object")
        except Exception as e:
            return self._json({"ok": False, "error": "bad json: %s" % e}, 400)
        ip = self.client_address[0]
        row = self.svc.ingest(d, src="push", ip=ip)
        if row is None:
            return self._json({"ok": False, "error": "no id"}, 400)
        self._json({"ok": True, "ts": row["ts"], "edge": self.svc.cfg["edge"],
                    "room": self.svc.cfg["room"]})

    def _ingest_batch(self):
        body = self._read_body()
        if body is None:
            return self._json({"ok": False, "error": "bad length"}, 400)
        try:
            d = json.loads(body.decode("utf-8"))
            if not isinstance(d, dict):
                raise ValueError("not an object")
        except Exception as e:
            return self._json({"ok": False, "error": "bad json: %s" % e}, 400)
        reply = self.svc.ingest_batch(d, ip=self.client_address[0])
        if reply is None:
            return self._json({"ok": False, "error": "need id and rows"}, 400)
        self._json(reply)

    def _event(self):
        """The tunnel watchdog (a separate root process on this Pi) hands its events in here."""
        if self._via_tunnel() or not self.client_address[0].startswith("127."):
            return self._json({"ok": False, "error": "local only"}, 403)
        body = self._read_body()
        try:
            d = json.loads((body or b"{}").decode("utf-8"))
            kind, text = str(d.get("kind") or "opal"), str(d.get("text") or "")
            level = d.get("level") if d.get("level") in ("info", "warn", "alert") else "info"
        except Exception as e:
            return self._json({"ok": False, "error": "bad json: %s" % e}, 400)
        if not text:
            return self._json({"ok": False, "error": "text required"}, 400)
        self.svc.events.emit(kind, text, level, d.get("data") if isinstance(d.get("data"), dict) else None)
        self._json({"ok": True})

    def _live(self, params=None):
        svc = self.svc
        q = svc.bus.subscribe()
        watched = []
        for uid in ",".join((params or {}).get("watch") or []).split(","):
            uid = uid.strip()
            if uid and uid not in watched and svc.watch.add(uid):
                watched.append(uid)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            hello = {"edge": svc.cfg["edge"], "room": svc.cfg["room"], "ts": util.now(),
                     "bins": svc.now.snapshot(), "watching": watched}
            self.wfile.write(("event: hello\ndata: %s\n\n" % json.dumps(hello, separators=(",", ":"))).encode())
            self.wfile.flush()
            last = time.monotonic()
            while True:
                try:
                    # a watching client is polled for every few seconds so a closed tab
                    # releases its Bin's poller quickly (the write fails once it is gone)
                    msg = q.get(timeout=3 if watched else 15)
                    self.wfile.write(msg.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                if time.monotonic() - last > 6 * 3600:
                    break           # make very long clients reconnect
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            pass
        finally:
            svc.bus.unsubscribe(q)
            for uid in watched:
                svc.watch.remove(uid)
            try:
                self.close_connection = True
            except Exception:
                pass

    def _static(self, path):
        www = self.svc.cfg["www_dir"]
        if path in ("", "/"):
            path = "/index.html"
        safe = os.path.normpath(path).lstrip("/")
        if ".." in safe.split(os.sep):
            return self._json({"error": "bad path"}, 400)
        full = os.path.join(www, safe)
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            # single-page fallbacks: /bin/<uid>, /team/<name> are handled by index.html
            full = os.path.join(www, "index.html")
            if not os.path.isfile(full):
                return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        self._bytes(data, ctype, cache="max-age=60")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, addr, svc):
        self.svc = svc
        super().__init__(addr, Handler)


def serve(svc):
    httpd = Server((svc.cfg["listen"], int(svc.cfg["port"])), svc)
    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.5},
                         name="http", daemon=True)
    t.start()
    log("server: listening on %s:%s" % (svc.cfg["listen"], svc.cfg["port"]))
    return httpd
