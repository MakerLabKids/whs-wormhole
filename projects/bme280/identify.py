# identify.py - Is this REALLY a BME280? Ask the chip itself.
#
# Evidence script for a sensor return / dispute. It is self-contained (no
# lib/ needed), touches nothing on the board, and prints a report that a
# seller can read without knowing anything about Picos:
#
#   1. Full I2C enumeration: every valid Pico I2C pin pair, every address
#      0x08-0x77. Whatever is wired up is found, wherever it is wired.
#   2. For every Bosch-style device (0x76 / 0x77): the CHIP ID register
#      (0xD0). Bosch burns the part number in at the factory:
#         0x60 = BME280 (temperature + pressure + HUMIDITY)
#         0x58 = BMP280 (temperature + pressure, NO humidity sensor)
#   3. Raw register dump (calibration + data) so the claim is checkable.
#   4. Live readings: temperature and pressure (should be sane on both
#      parts), humidity (only a BME280 has the hardware), and a 10 second
#      "breathe on it" test: a real humidity sensor jumps 10-40 points
#      when you breathe on it; a BMP280 cannot move at all.
#
# Wiring (one sensor at a time is clearest): VCC->3V3, GND->GND,
# SDA->GP0, SCL->GP1. Any other valid pair also works; the scan finds it.
#
# Run from a laptop with the Pico on USB:
#     mpremote run projects/bme280/identify.py
# or copy it to the board as main.py.

import struct
import time

from machine import Pin, SoftI2C, unique_id

BREATH_SECONDS = 10

# Every (controller, SDA, SCL) pairing the RP2040/RP2350 datasheet allows.
PAIRS = [(0, 0, 1), (0, 4, 5), (0, 8, 9), (0, 12, 13), (0, 16, 17), (0, 20, 21),
         (1, 2, 3), (1, 6, 7), (1, 10, 11), (1, 14, 15), (1, 18, 19), (1, 26, 27)]

CHIP_IDS = {0x60: "BME280 (temp + pressure + humidity)",
            0x58: "BMP280 (temp + pressure, NO humidity sensor)",
            0x56: "BMP280 engineering sample (no humidity)",
            0x57: "BMP280 engineering sample (no humidity)",
            0x61: "BME680", 0x55: "BMP180 / BMP085"}

KNOWN = {0x3C: "SSD1306 OLED", 0x48: "ADS1115", 0x29: "VL53L0X", 0x23: "BH1750",
         0x76: "Bosch BMx280 (SDO low)", 0x77: "Bosch BMx280 (SDO high)"}


def hexs(b):
  return " ".join("%02X" % x for x in b)


class Bosch:
  """Minimal BME280/BMP280 reader, float compensation per the datasheet."""

  def __init__(self, i2c, addr):
    self.i2c, self.addr = i2c, addr
    self.chip_id = self.r(0xD0, 1)[0]
    self.is_bme = self.chip_id == 0x60
    c = self.r(0x88, 26)
    (self.T1, self.T2, self.T3, self.P1, self.P2, self.P3, self.P4, self.P5,
     self.P6, self.P7, self.P8, self.P9) = struct.unpack("<HhhHhhhhhhhh", c[:24])
    self.cal_pt = c
    self.cal_h = bytes([c[25]]) + self.r(0xE1, 7)
    e = self.cal_h
    self.H1, self.H2, self.H3 = e[0], struct.unpack("<h", e[1:3])[0], e[3]
    h4 = (e[4] << 4) | (e[5] & 0x0F)
    h5 = (e[6] << 4) | (e[5] >> 4)
    self.H4 = h4 - 4096 if h4 > 2047 else h4
    self.H5 = h5 - 4096 if h5 > 2047 else h5
    self.H6 = struct.unpack("b", bytes([e[7]]))[0]
    # Ask for humidity x1, temp x1, pressure x1, normal mode. On a BMP280
    # the 0xF2 (ctrl_hum) register does not exist, so this is harmless.
    self.w(0xF2, 0x01)
    self.w(0xF4, 0x27)
    self.w(0xF5, 0x00)
    time.sleep_ms(100)

  def r(self, reg, n):
    return self.i2c.readfrom_mem(self.addr, reg, n)

  def w(self, reg, v):
    self.i2c.writeto_mem(self.addr, reg, bytes([v]))

  def read(self):
    d = self.r(0xF7, 8)
    adc_p = (d[0] << 12) | (d[1] << 4) | (d[2] >> 4)
    adc_t = (d[3] << 12) | (d[4] << 4) | (d[5] >> 4)
    adc_h = (d[6] << 8) | d[7]
    var1 = (adc_t / 16384.0 - self.T1 / 1024.0) * self.T2
    var2 = ((adc_t / 131072.0 - self.T1 / 8192.0) ** 2) * self.T3
    t_fine = var1 + var2
    temp_c = t_fine / 5120.0
    var1 = t_fine / 2.0 - 64000.0
    var2 = var1 * var1 * self.P6 / 32768.0 + var1 * self.P5 * 2.0
    var2 = var2 / 4.0 + self.P4 * 65536.0
    var1 = (self.P3 * var1 * var1 / 524288.0 + self.P2 * var1) / 524288.0
    var1 = (1.0 + var1 / 32768.0) * self.P1
    if var1 == 0:
      press = 0.0
    else:
      p = 1048576.0 - adc_p
      p = (p - var2 / 4096.0) * 6250.0 / var1
      press = (p + (self.P9 * p * p / 2147483648.0 + p * self.P8 / 32768.0
                    + self.P7) / 16.0) / 100.0
    h = t_fine - 76800.0
    h = (adc_h - (self.H4 * 64.0 + self.H5 / 16384.0 * h)) * (
        self.H2 / 65536.0 * (1.0 + self.H6 / 67108864.0 * h *
                             (1.0 + self.H3 / 67108864.0 * h)))
    h = h * (1.0 - self.H1 * h / 524288.0)
    hum = max(0.0, min(100.0, h))
    return temp_c, press, hum, adc_h, d


def examine(label, i2c, addr):
  print()
  print("=" * 64)
  print("DEVICE at 0x%02X on %s" % (addr, label))
  print("=" * 64)
  s = Bosch(i2c, addr)
  print("chip ID register 0xD0 = 0x%02X  ->  %s"
        % (s.chip_id, CHIP_IDS.get(s.chip_id, "unknown Bosch ID")))
  print("ctrl_hum 0xF2 after writing 0x01 = 0x%02X   (reads back 0x01 on a BME280;"
        " 0xF2 is not a documented register on a BMP280)" % s.r(0xF2, 1)[0])
  print("ctrl_meas 0xF4 = 0x%02X   config 0xF5 = 0x%02X"
        % (s.r(0xF4, 1)[0], s.r(0xF5, 1)[0]))
  print("T/P calibration 0x88-0xA1:", hexs(s.cal_pt))
  print("humidity calibration 0xA1,0xE1-0xE7:", hexs(s.cal_h),
        "  (BME280: real numbers; BMP280: zeros/garbage)")
  print()
  print("   #   temp_C  press_hPa   hum_%   raw humidity 0xFD-0xFE")
  for n in range(5):
    t, p, h, adc_h, d = s.read()
    print("  %2d   %6.2f   %8.2f  %6s   0x%04X" %
          (n + 1, t, p, "%.2f" % h if s.is_bme else "n/a", adc_h))
    time.sleep_ms(400)
  if not s.is_bme:
    print("  (0xFD-0xFE are not documented registers on a BMP280; the value is"
          " a constant, not a measurement)")
  print()
  print("BREATH TEST: breathe on the sensor for the next %d seconds..." % BREATH_SECONDS)
  lo, hi, start = 101.0, -1.0, time.ticks_ms()
  raw_lo, raw_hi = 0xFFFF, 0
  while time.ticks_diff(time.ticks_ms(), start) < BREATH_SECONDS * 1000:
    t, p, h, adc_h, d = s.read()
    lo, hi = min(lo, h), max(hi, h)
    raw_lo, raw_hi = min(raw_lo, adc_h), max(raw_hi, adc_h)
    print("  t=%4.1fs  temp %5.2f C  press %7.2f hPa  humidity %6s %%  raw 0x%04X"
          % (time.ticks_diff(time.ticks_ms(), start) / 1000, t, p,
             "%.2f" % h if s.is_bme else "n/a", adc_h))
    time.sleep_ms(500)
  swing = hi - lo
  if s.is_bme:
    print("  humidity range during breath test: %.2f .. %.2f  (swing %.2f points)"
          % (lo, hi, swing))
  else:
    print("  raw humidity register during breath test: 0x%04X .. 0x%04X  (%s)"
          % (raw_lo, raw_hi, "never changed" if raw_lo == raw_hi else "changed"))
  print()
  t_ok = -10 < t < 60
  p_ok = 300 < p < 1100
  h_ok = s.is_bme and 0 < h < 100 and swing > 2
  print("VERDICT for 0x%02X:" % addr)
  print("  temperature sensor : %s  (%.2f C)" % ("WORKING" if t_ok else "BAD", t))
  print("  pressure sensor    : %s  (%.2f hPa)" % ("WORKING" if p_ok else "BAD", p))
  if s.is_bme:
    print("  humidity sensor    : %s  (%.2f %%, moved %.2f points when breathed on)"
          % ("WORKING" if h_ok else "NOT RESPONDING", h, swing))
    print("  chip identifies itself as a BME280.")
  else:
    print("  humidity sensor    : NOT PRESENT. Chip ID 0x%02X is a %s." %
          (s.chip_id, CHIP_IDS.get(s.chip_id, "non-BME280 part")))
    print("  Humidity data register reads 0x%04X and %s during the breath test;"
          " the chip has no humidity hardware."
          % (adc_h, "never changed" if raw_lo == raw_hi else "CHANGED"))
    print("  This part is NOT a BME280.")


def main():
  print("Bosch BMx280 identifier  |  board unique id %s  |  MicroPython %s"
        % (hexs(unique_id()), ".".join(str(x) for x in __import__("sys").implementation.version[:3])))
  print("Scanning all 12 valid Pico I2C pin pairs, addresses 0x08-0x77:")
  found = []
  for ctl, sda, scl in PAIRS:
    try:
      i2c = SoftI2C(sda=Pin(sda), scl=Pin(scl), freq=50000)
      addrs = i2c.scan()
    except Exception as e:
      print("  I2C%d SDA=GP%-2d SCL=GP%-2d : error %s" % (ctl, sda, scl, e))
      continue
    label = "I2C%d SDA=GP%d SCL=GP%d" % (ctl, sda, scl)
    desc = ", ".join("0x%02X %s" % (a, KNOWN.get(a, "?")) for a in addrs) or "(nothing)"
    print("  %-26s: %s" % (label, desc))
    for a in addrs:
      if a in (0x76, 0x77):
        found.append((label, (ctl, sda, scl), a))
  if not found:
    print()
    print("No Bosch sensor found on any pin pair / any address.")
    return
  for label, (ctl, sda, scl), a in found:
    # Bit-banged I2C: tolerant of weak pull-ups, and it does not tie up
    # the Pico's two hardware controllers while we walk all 12 pin pairs.
    i2c = SoftI2C(sda=Pin(sda), scl=Pin(scl), freq=50000)
    try:
      examine(label, i2c, a)
    except Exception as e:
      print("  ERROR talking to 0x%02X: %r" % (a, e))
  print()
  print("done.")


main()
