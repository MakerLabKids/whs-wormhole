STA_IF = 0; AP_IF = 1
WORLD = {"present": set(["WormHole"]), "ip": "192.168.81.120", "connect_ticks": 2}
class WLAN:
    instances = {}
    def __init__(self, kind):
        self.kind = kind; self._active = False; self._ssid = None; self._pending = 0
        self._essid = None; self.ifcfg = ("0.0.0.0", "255.255.255.0", "0.0.0.0", "0.0.0.0")
        WLAN.instances[kind] = self
    def active(self, v=None):
        if v is None: return self._active
        self._active = bool(v)
        if not v: self._ssid = None
    def scan(self):
        return [(n.encode(), b"\x00"*6, 6, -60, 3, False) for n in WORLD["present"]]
    def connect(self, ssid, pw):
        self._ssid = ssid; self._pending = WORLD["connect_ticks"]
    def disconnect(self): self._ssid = None
    def isconnected(self):
        if self.kind == AP_IF: return False
        if not self._ssid or self._ssid not in WORLD["present"]: return False
        if self._pending > 0:
            self._pending -= 1; return False
        return True
    def ifconfig(self, cfg=None):
        if cfg: self.ifcfg = cfg; return
        if self.kind == STA_IF: return (WORLD["ip"], "255.255.255.0", "192.168.81.1", "192.168.81.1")
        return self.ifcfg
    def config(self, *a, **k):
        if "essid" in k: self._essid = k["essid"]
    def status(self, what=None):
        return -61 if what == "rssi" else 3
