# /burrow1/live -> 127.0.0.1:8213/live (streams), for the Worker's LIVE_BASE in local tests
import http.server, urllib.request, sys
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self,*a): pass
    def do_GET(self):
        if not self.path.startswith("/burrow1/"):
            self.send_response(502); self.send_header("Content-Length","0"); self.end_headers(); return
        req = urllib.request.Request("http://127.0.0.1:8213" + self.path[len("/burrow1"):], headers={k:v for k,v in self.headers.items() if k.lower() in ("x-burrow-key","cf-ray","accept")})
        try:
            r = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            self.send_response(e.code); self.send_header("Content-Length","0"); self.end_headers(); return
        self.send_response(r.status); self.send_header("Content-Type", r.headers.get("Content-Type","")); self.send_header("Transfer-Encoding","chunked"); self.end_headers()
        try:
            while True:
                chunk = r.readline()
                if not chunk: break
                self.wfile.write(("%x\r\n" % len(chunk)).encode() + chunk + b"\r\n"); self.wfile.flush()
        except Exception: pass
http.server.ThreadingHTTPServer.daemon_threads = True
http.server.ThreadingHTTPServer(("127.0.0.1", 8214), H).serve_forever()
