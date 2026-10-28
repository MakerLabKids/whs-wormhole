class Pin:
    OUT = 1; IN = 0
    def __init__(self, *a, **k): self.v = 0
    def value(self, v=None):
        if v is None: return self.v
        self.v = v
    def on(self): self.v = 1
    def off(self): self.v = 0
class I2C:
    def __init__(self, *a, **k): pass
    def scan(self): return []
class PWM:
    def __init__(self, *a, **k): pass
    def freq(self, f): pass
    def duty_u16(self, d): pass
class ADC:
    def __init__(self, *a, **k): pass
    def read_u16(self): return 30000
def unique_id(): return b"\xe6\x61\x18\x60\x4b\x7c\x2b\x2a"
class WDT:
    """Stub hardware watchdog: counts feeds so the harness can see it is fed."""
    armed = None
    def __init__(self, id=0, timeout=5000):
        self.timeout = timeout; self.feeds = 0; WDT.armed = self
    def feed(self): self.feeds += 1
class _Mem:
    """mem32 stub: USB SIE_STATUS reads 0 (no host attached) so the watchdog arms."""
    def __getitem__(self, addr): return 0
mem32 = _Mem()
