import sys
sys.path.insert(0, "../stubs"); sys.path.insert(0, ".")
import faketime, sockshim
sys.modules["time"] = faketime
import time, json, socket
import picolab
picolab.PORT = 8212
import network

def data_fn():
    return {"ok": True, "in_temp_c": 21.5 + (time.ticks_ms() % 7) / 10, "moist1_pct": 40.0,
            "probe_temps_c": [20.1, None], "relay": 0, "parts": [{"name": "x", "ok": True}]}

def step(n, sec=1):
    for _ in range(n):
        app.poll(data_fn)
        faketime.advance(sec)

def http_get(path):
    # single-threaded: the server only accepts inside app.poll(), so pump it
    s = socket.socket(); s.connect(socket.getaddrinfo("127.0.0.1", 8212)[0][-1])
    s.send(("GET %s HTTP/1.0\r\n\r\n" % path).encode())
    s.settimeout(0.05)
    out = b""
    for i in range(400):
        app.poll(data_fn)
        try:
            c = s.recv(4096)
            if not c:
                break
            out += c
        except OSError:
            pass
    s.close()
    return out

checks = []
def check(name, cond):
    checks.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name)

app = picolab.WebApp()
check("boot: joined WormHole", app.joined == "WormHole" and app.ip == "192.168.81.120")
check("boot: no hotspot while joined", app.ap is None)
check("identity carries bin", app.identity().get("bin", {}).get("team") == "Dirt Vader")
step(8)                                           # first push is due 5 s after joining
check("push accepted by Burrow", app.edge_ok and app.edge == "127.0.0.1:8211" and app.edge_ts is not None)
check("now_ts derived from Burrow", app.now_ts() is not None)
d = json.loads(http_get("/data").split(b"\r\n\r\n", 1)[1])
check("/data has bin + edge + mode", d.get("bin", {}).get("bin") == 7 and d.get("edge") == "127.0.0.1:8211" and d["mode"] == "joined")
# history: three 5-minute samples
step(3, 300)
h = json.loads(http_get("/history").split(b"\r\n\r\n", 1)[1])
check("/history has samples", h["n"] >= 3 and "in_temp_c" in h["m"] and "probe_temps_c_0" in h["m"] and len(h["t"]) == h["n"])
check("/history nulls for missing", h["m"]["probe_temps_c_0"][0] is not None and "relay" not in h["m"])
# lose the network
network.WORLD["present"] = set()
step(2)
check("loss noticed", app.joined is None and app.ap is None)
step(65)
check("hotspot opened 60 s after loss (station off)", app.ap is not None and app.ip == "192.168.4.1"
      and not network.WLAN.instances[network.STA_IF].active())
check("mode is ap", app.identity()["mode"] == "ap")
scans = network.WORLD["scans"]
step(130)                                         # one rescan with nothing around: hotspot comes back
check("rescanned and put the hotspot back", network.WORLD["scans"] > scans and app.joined is None and app.ap is not None)
# a phone is on the hotspot: do not yank it
network.WORLD["stations"] = ["phone"]
scans = network.WORLD["scans"]
step(130)
check("no rescan while a phone is on the hotspot", network.WORLD["scans"] == scans and app.ap is not None)
network.WORLD["stations"] = []
network.WORLD["present"] = set(["WormHole"])
step(130)                                         # next rescan finds it and joins
check("rejoined after network returned", app.joined == "WormHole" and app.ip == "192.168.81.120")
check("hotspot closed on rejoin (rp2: one interface at a time)", app.ap is None and app.identity()["mode"] == "joined")
step(10)
check("push resumed after rejoin", app.edge_ok)
# hotspot hold has a limit: a phone on the hotspot for 10 min still gets a rescan
network.WORLD["present"] = set()
step(70)
network.WORLD["stations"] = ["phone"]
network.WORLD["present"] = set(["WormHole"])
scans = network.WORLD["scans"]
step(790)                                         # hold starts at the first deferred rescan (+120), lasts 600
check("rescan happens anyway after 10 min of hotspot use", network.WORLD["scans"] > scans and app.joined == "WormHole")
# rescue ladder: wormmaster beats WormHole when present
network.WORLD["stations"] = []
network.WORLD["present"] = set()
step(70)
network.WORLD["present"] = set(["WormHole", "wormmaster"])
step(130)
check("ladder prefers wormmaster", app.joined == "wormmaster")
app.close()
bad = [n for n, ok in checks if not ok]
print("\n%d checks, %d failed %s" % (len(checks), len(bad), bad))
sys.exit(1 if bad else 0)
