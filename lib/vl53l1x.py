# MicroPython VL53L1X driver (I2C, address 0x29). Long-range time of
# flight: up to ~4 m, vs ~1.2 m for the VL53L0X.
#
# Adapted from drakxtwo/vl53l1x_pico (MIT license), itself based on the
# Pololu VL53L1X Arduino library and the ST VL53L1X ultra lite driver.
# Changes for this repo: time.sleep_ms instead of machine.lightsleep
# (lightsleep disturbs the Pico W radio), a fast bus scan so a missing
# sensor fails immediately (hot-plug friendly), a boot-state wait, and
# read() also returns the range status so demos can show "no target".
#
#   from vl53l1x import VL53L1X
#   tof = VL53L1X(i2c)          # full 27 degree cone
#   tof = VL53L1X(i2c, roi=8)   # ~20 degree cone (see ROI below)
#   mm, valid = tof.read()
#
# ROI (field of view). The chip ranges over a 16x16 grid of SPADs; using
# only the centre NxN narrows the cone: 16 = ~27 deg (ST's figure),
# 8 = ~20 deg, 4 = ~15 deg (the minimum ST allows). Narrower means the
# sensor ignores things at the edge of the view (the desk under it, a
# lamp beside the target, the person watching) but it also collects
# proportionally less light, so the usable range shrinks: 16x16 reaches
# ~4 m on a white wall in the dark, 4x4 struggles past ~1.5 m. The
# minimum-signal limit is scaled with the ROI so a small region is not
# rejected for the light it never had.
#
# Crosstalk. Some light from the emitter reaches the receiver without ever
# leaving the module (cover glass, package, board). The chip subtracts a
# per-SPAD crosstalk rate if told what it is; untold, far or dim targets
# read SHORT, worse the dimmer they are (a module read 900 mm against a
# wall at 1120 mm). Calibrate once per module against a plain wall at a
# tape-measured distance, then pass the kcps figure to every init:
#   tof = VL53L1X(i2c, roi=8, xtalk=2900, offset=15)
#   mm = tof.calibrate_offset(100)      # first: wall at 100 mm
#   kcps = tof.calibrate_xtalk(1120)    # then: wall at 1120 mm, same roi

import time

MODEL_ID = 0xEACC

# ST default configuration for registers 0x2D..0x87. Includes
# "clear interrupt" (0x86=0x01) and "start ranging" (0x87=0x40), so the
# sensor free-runs as soon as this blob is written.
_DEFAULT_CONFIG = bytes([
    0x00, 0x00, 0x00, 0x01, 0x02, 0x00, 0x02, 0x08, 0x00, 0x08,
    0x10, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x0F,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x20, 0x0B, 0x00, 0x00, 0x02,
    0x0A, 0x21, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x00, 0xC8,
    0x00, 0x00, 0x38, 0xFF, 0x01, 0x00, 0x08, 0x00, 0x00, 0x01,
    0xDB, 0x0F, 0x01, 0xF1, 0x0D, 0x01, 0x68, 0x00, 0x80, 0x08,
    0xB8, 0x00, 0x00, 0x00, 0x00, 0x0F, 0x89, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x01, 0x0F, 0x0D, 0x0E, 0x0E, 0x00,
    0x00, 0x02, 0xC7, 0xFF, 0x9B, 0x00, 0x00, 0x00, 0x01, 0x01,
    0x40,
])

# Range status 9 = valid; 8 = valid but clipped at minimum range.
VALID_STATUSES = (9, 8)


class VL53L1X:
  def __init__(self, i2c, address=0x29, roi=16, xtalk=0, offset=0):
    self.i2c = i2c
    self.address = address
    self.roi = 16
    self.xtalk = 0
    self.offset = 0
    if address not in i2c.scan():
      raise OSError("VL53L1X not found at 0x29")

    self._reset()
    time.sleep_ms(1)
    if self._read16(0x010F) != MODEL_ID:
      raise OSError("not a VL53L1X (bad model id)")

    # Wait for firmware boot (FIRMWARE__SYSTEM_STATUS bit 0). The chip
    # may not ACK at all for a few ms after a reset, so a bus error here
    # is "not yet", not "gone".
    deadline = time.ticks_add(time.ticks_ms(), 1000)
    while True:
      try:
        if self._read8(0x00E5) & 0x01:
          break
      except OSError:
        pass
      if time.ticks_diff(time.ticks_ms(), deadline) > 0:
        raise OSError("VL53L1X boot timeout")
      time.sleep_ms(10)

    self.i2c.writeto_mem(self.address, 0x2D, _DEFAULT_CONFIG, addrsize=16)

    # The ST API applies this once ranging starts (MM1/MM2 disabled):
    # outer offset = inner offset * 4
    self._write16(0x001E, self._read16(0x0022) * 4)
    time.sleep_ms(200)
    if offset:
      self.set_offset(offset)
    if xtalk:
      self.set_xtalk(xtalk)
    if roi != 16:
      self.set_roi(roi)

  def set_offset(self, mm):
    """Zero offset in mm, added to every reading (ST VL53L1X_SetOffset).
    Replaces the factory part-to-part value the init copied in."""
    mm = int(mm)
    self._write8(0x0087, 0x00)
    time.sleep_ms(30)
    self._write16(0x001E, (mm * 4) & 0xFFFF)   # ALGO__PART_TO_PART_RANGE_OFFSET_MM
    self._write16(0x0020, 0)                   # MM_CONFIG__INNER_OFFSET_MM
    self._write16(0x0022, 0)                   # MM_CONFIG__OUTER_OFFSET_MM
    self._write8(0x0086, 0x01)
    self._write8(0x0087, 0x40)
    self.offset = mm

  def _average_range(self, samples, timeout_ms=30000):
    n = total = 0
    prev = None
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while n < samples and time.ticks_diff(time.ticks_ms(), deadline) < 0:
      d = self.i2c.readfrom_mem(self.address, 0x0089, 17, addrsize=16)
      k = bytes(d)
      if k != prev:
        prev = k
        if d[0] & 0x1F == 9:
          n += 1
          total += (d[13] << 8) | d[14]
      time.sleep_ms(20)
    if n < 10:
      raise OSError("only %d valid samples" % n)
    return total / n

  def calibrate_offset(self, target_mm, samples=50):
    """ST VL53L1X_CalibrateOffset: plain target square to the sensor at a
    known SHORT distance (ST uses 140 mm) where crosstalk cannot matter.
    Do this BEFORE calibrate_xtalk. Applies and returns the offset in mm
    for VL53L1X(..., offset=mm)."""
    self.set_offset(0)
    time.sleep_ms(300)
    mm = int(round(target_mm - self._average_range(samples)))
    self.set_offset(mm)
    return mm

  def set_xtalk(self, kcps):
    """Crosstalk compensation in kcps (ST VL53L1X_SetXtalk). 0 disables."""
    self._write8(0x0087, 0x00)
    time.sleep_ms(30)
    self._write16(0x0018, 0)              # x gradient
    self._write16(0x001A, 0)              # y gradient
    self._write16(0x0016, (int(kcps) << 9) // 1000)   # plane offset, 9.7 kcps
    self._write8(0x0086, 0x01)
    self._write8(0x0087, 0x40)
    self.xtalk = int(kcps)

  def calibrate_xtalk(self, target_mm, samples=50):
    """ST VL53L1X_CalibrateXtalk: with a plain target square to the sensor
    at a known distance (compensation off), average the reported distance,
    signal rate and SPAD count, derive the crosstalk, apply it, and return
    it in kcps for VL53L1X(..., xtalk=kcps). Calibrate with the ROI you
    will use: crosstalk is stronger at the edges of the grid, so the
    full-array figure over-corrects a 4x4 centre by ~13%."""
    self.set_xtalk(0)
    time.sleep_ms(300)
    n = d_sum = sr_sum = sp_sum = 0
    prev = None
    deadline = time.ticks_add(time.ticks_ms(), 30000)
    while n < samples and time.ticks_diff(time.ticks_ms(), deadline) < 0:
      d = self.i2c.readfrom_mem(self.address, 0x0089, 17, addrsize=16)
      k = bytes(d)
      if k != prev:
        prev = k
        if d[0] & 0x1F == 9:
          n += 1
          d_sum += (d[13] << 8) | d[14]
          sr_sum += ((d[15] << 8) | d[16]) * 8          # kcps
          sp_sum += ((d[3] << 8) | d[4]) >> 8           # effective SPADs
      time.sleep_ms(20)
    if n < 10:
      raise OSError("calibrate_xtalk: only %d valid samples" % n)
    avg_d, avg_sr, avg_sp = d_sum / n, sr_sum / n, sp_sum / n
    cal = int(512 * (avg_sr * (1 - avg_d / target_mm)) / avg_sp)
    cal = max(0, min(cal, 0xFFFF))
    kcps = (cal * 1000) >> 9
    self.set_xtalk(kcps)
    return kcps

  def set_roi(self, size):
    """Range over only the centre size x size SPADs (4..16). Restarts
    ranging; the next read() is valid after ~200 ms."""
    size = max(4, min(16, int(size)))
    self._write8(0x0087, 0x00)            # stop ranging
    time.sleep_ms(30)
    self._write8(0x007F, 199)             # ROI centre = array centre
    self._write8(0x0080, ((size - 1) << 4) | (size - 1))
    # Min count rate limit, 9.7 fixed point MCPS. ST default 1.0 MCPS for
    # 256 SPADs; scale by the SPAD count, floor 0.125 MCPS.
    limit = max(16, (128 * size * size) // 256)
    self._write16(0x0066, limit)
    self._write8(0x0086, 0x01)            # clear interrupt
    self._write8(0x0087, 0x40)            # start ranging
    self.roi = size

  def _write8(self, reg, value):
    self.i2c.writeto_mem(self.address, reg, bytes([value]), addrsize=16)

  def _write16(self, reg, value):
    self.i2c.writeto_mem(
        self.address, reg, bytes([(value >> 8) & 0xFF, value & 0xFF]),
        addrsize=16)

  def _read8(self, reg):
    return self.i2c.readfrom_mem(self.address, reg, 1, addrsize=16)[0]

  def _read16(self, reg):
    d = self.i2c.readfrom_mem(self.address, reg, 2, addrsize=16)
    return (d[0] << 8) | d[1]

  def _reset(self):
    self._write8(0x0000, 0x00)
    time.sleep_ms(100)
    self._write8(0x0000, 0x01)

  def read(self):
    """Returns (distance_mm, valid). Sensor free-runs at ~10 Hz."""
    d = self.i2c.readfrom_mem(self.address, 0x0089, 17, addrsize=16)
    status = d[0] & 0x1F
    mm = (d[13] << 8) | d[14]
    return mm, status in VALID_STATUSES
