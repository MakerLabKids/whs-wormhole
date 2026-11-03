"""lib/bme280.py on a fake I2C bus, off-board:
    micropython tools/picotest/test_bme280.py
A garbled chip-ID read must not turn a BME280 into a BMP280 (humidity lost until a restart),
and a chip that lost its settings (humidity "skipped") gets them back."""
import sys
sys.path.insert(0, "tools/picotest/stubs"); sys.path.insert(0, "lib")
import faketime
sys.modules["time"] = faketime
import bme280

class Bus:
  def __init__(self, ids):
    self.ids = list(ids)              # what successive chip-ID reads return
    self.regs = {0xF2: 0, 0xF4: 0, 0xF5: 0}
    self.writes = []
    self.hum = b"\x80\x00"
  def scan(self): return [0x77]
  def readfrom_mem(self, addr, reg, n):
    if reg == 0xD0:
      v = self.ids.pop(0) if len(self.ids) > 1 else self.ids[0]
      if v is None: raise OSError(5)
      return bytes([v])
    if reg == 0xF7:
      return bytes([0x50, 0, 0, 0x80, 0, 0]) + (self.hum if self.regs[0xF2] else b"\x80\x00")
    return bytes(n)
  def writeto_mem(self, addr, reg, data):
    self.writes.append((reg, data[0])); self.regs[reg] = data[0]

# a garbled first read (0xff), then the real ID: still a BME280, humidity switched on
b = Bus([0xFF, 0x60]); s = bme280.BME280(b, 0x77)
assert s.has_humidity and (0xF2, 0x01) in b.writes, b.writes
# an unreadable / wrong ID three times: no guessing, the connect fails (the board retries it)
for ids in ([0xFF], [None], [0x00]):
  try:
    bme280.BME280(Bus(ids), 0x77); raise AssertionError("accepted chip id %r" % ids)
  except OSError as e:
    assert "chip id" in str(e), e
# a real BMP280: no humidity, no ctrl_hum write
b = Bus([0x58]); s = bme280.BME280(b, 0x77)
assert not s.has_humidity and not any(r == 0xF2 for r, v in b.writes)
assert s.read()[2] is None
# the chip lost its settings: humidity reads "skipped" -> settings sent again, next read has it
b = Bus([0x60]); s = bme280.BME280(b, 0x77)
b.regs[0xF2] = 0; b.hum = b"\x60\x00"; n = len(b.writes)
assert s.read()[2] is None
assert (0xF2, 0x01) in b.writes[n:] and (0xF4, 0x27) in b.writes[n:], b.writes[n:]
assert s.read()[2] is not None, "humidity back on the next reading"
print("bme280 OK")
