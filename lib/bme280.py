# MicroPython BME280 driver (I2C), float compensation per the Bosch
# datasheet. Also tolerates a BMP280 (same registers, no humidity).
#
#   from bme280 import BME280
#   s = BME280(i2c)          # finds 0x76 or 0x77 automatically
#   temp_c, press_hpa, hum_pct = s.read()   # hum_pct is None on BMP280

import struct
import time

REG_CHIP_ID = 0xD0
REG_RESET = 0xE0
REG_CTRL_HUM = 0xF2
REG_CTRL_MEAS = 0xF4
REG_CONFIG = 0xF5
REG_DATA = 0xF7


class BME280:
  def __init__(self, i2c, address=None):
    self.i2c = i2c
    if address is None:
      found = [a for a in (0x76, 0x77) if a in i2c.scan()]
      if not found:
        raise OSError("BME280 not found at 0x76/0x77")
      address = found[0]
    self.address = address

    # The chip ID decides whether humidity exists (0x60 BME280, 0x58 BMP280). One garbled read on a
    # shaky bus used to make a BME280 look like a BMP280 for good (humidity "--" until a restart),
    # so read it up to three times and refuse anything else: the caller retries the connect.
    cid = None
    for _ in range(3):
      try:
        cid = self._read(REG_CHIP_ID, 1)[0]
      except OSError:
        cid = None
      if cid in (0x60, 0x58):
        break
      time.sleep_ms(5)
    if cid not in (0x60, 0x58):
      raise OSError("BME280 chip id %s, not 0x60/0x58" % (hex(cid) if cid is not None else "unreadable"))
    self.chip_id = cid
    self.has_humidity = cid == 0x60

    self._load_calibration()
    self._configure()
    time.sleep_ms(50)

  def _configure(self):
    # humidity x1 (ctrl_hum only takes effect after a ctrl_meas write), temp x1, pressure x1,
    # normal mode, 0.5ms standby
    if self.has_humidity:
      self._write(REG_CTRL_HUM, 0x01)
    self._write(REG_CTRL_MEAS, 0x27)
    self._write(REG_CONFIG, 0x00)

  def _read(self, reg, n):
    return self.i2c.readfrom_mem(self.address, reg, n)

  def _write(self, reg, value):
    self.i2c.writeto_mem(self.address, reg, bytes([value]))

  def _load_calibration(self):
    c = self._read(0x88, 26)
    (self.T1, self.T2, self.T3,
     self.P1, self.P2, self.P3, self.P4, self.P5,
     self.P6, self.P7, self.P8, self.P9) = struct.unpack("<HhhHhhhhhhhh", c[:24])
    if self.has_humidity:
      self.H1 = c[25]
      e = self._read(0xE1, 7)
      self.H2 = struct.unpack("<h", e[0:2])[0]
      self.H3 = e[2]
      h4 = (e[3] << 4) | (e[4] & 0x0F)
      h5 = (e[5] << 4) | (e[4] >> 4)
      self.H4 = h4 - 4096 if h4 > 2047 else h4
      self.H5 = h5 - 4096 if h5 > 2047 else h5
      self.H6 = struct.unpack("b", bytes([e[6]]))[0]

  def read(self):
    """Returns (temp_c, pressure_hpa, humidity_pct_or_None)."""
    d = self._read(REG_DATA, 8)
    adc_p = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
    adc_t = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)
    adc_h = (d[6] << 8) | d[7]

    # Temperature
    var1 = (adc_t / 16384.0 - self.T1 / 1024.0) * self.T2
    var2 = ((adc_t / 131072.0 - self.T1 / 8192.0) ** 2) * self.T3
    t_fine = var1 + var2
    temp_c = t_fine / 5120.0

    # Pressure
    var1 = t_fine / 2.0 - 64000.0
    var2 = var1 * var1 * self.P6 / 32768.0
    var2 = var2 + var1 * self.P5 * 2.0
    var2 = var2 / 4.0 + self.P4 * 65536.0
    var1 = (self.P3 * var1 * var1 / 524288.0 + self.P2 * var1) / 524288.0
    var1 = (1.0 + var1 / 32768.0) * self.P1
    if var1 == 0:
      press_hpa = 0.0
    else:
      p = 1048576.0 - adc_p
      p = (p - var2 / 4096.0) * 6250.0 / var1
      var1 = self.P9 * p * p / 2147483648.0
      var2 = p * self.P8 / 32768.0
      press_hpa = (p + (var1 + var2 + self.P7) / 16.0) / 100.0

    # Humidity. 0x8000 = "skipped": the chip lost its settings (a power blip resets it to
    # humidity off), so send them again; the next reading has humidity back.
    hum_pct = None
    if self.has_humidity and adc_h == 0x8000:
      self._configure()
    elif self.has_humidity:
      h = t_fine - 76800.0
      h = (adc_h - (self.H4 * 64.0 + self.H5 / 16384.0 * h)) * (
          self.H2 / 65536.0 * (1.0 + self.H6 / 67108864.0 * h *
                               (1.0 + self.H3 / 67108864.0 * h)))
      h = h * (1.0 - self.H1 * h / 524288.0)
      hum_pct = max(0.0, min(100.0, h))

    return temp_c, press_hpa, hum_pct
