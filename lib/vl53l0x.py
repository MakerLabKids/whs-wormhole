"""VL53L0X time-of-flight distance sensor (ST), 30 mm to ~1.2 m.

A port of Pololu's vl53l0x-arduino driver (MIT), which is itself the
essential path through ST's API: DataInit, StaticInit (reference SPADs,
tuning settings, interrupt config, timing budget) and the VHV + phase
reference calibration. Without that init the chip runs on power-up
defaults: readings tens of mm long, nothing past a metre, and 0 mm
("no measurement") at close, bright targets. With it the chip reads as
the datasheet says.

  tof = VL53L0X(i2c)                   # inits; raises OSError if absent
  mm = tof.ping()                      # one blocking shot (~budget ms)
  tof.status                           # range status of that shot: 11 = valid
  tof.set_timing_budget(200000)        # us per shot: longer = quieter (33 ms default)

  tof.start_continuous(250)            # a shot every 250 ms, no blocking:
  mm = tof.range()                     # the latest, or None if nothing new yet
  tof.stop_continuous()
"""
import time

_SYSRANGE_START = 0x00
_SYSTEM_SEQUENCE_CONFIG = 0x01
_SYSTEM_INTERMEASUREMENT_PERIOD = 0x04
_SYSTEM_INTERRUPT_CONFIG_GPIO = 0x0A
_SYSTEM_INTERRUPT_CLEAR = 0x0B
_RESULT_INTERRUPT_STATUS = 0x13
_RESULT_RANGE_STATUS = 0x14
_MSRC_CONFIG_CONTROL = 0x60
_FINAL_RANGE_CONFIG_MIN_COUNT_RATE_RTN_LIMIT = 0x44
_PRE_RANGE_CONFIG_VCSEL_PERIOD = 0x50
_PRE_RANGE_CONFIG_TIMEOUT_MACROP_HI = 0x51
_FINAL_RANGE_CONFIG_VCSEL_PERIOD = 0x70
_FINAL_RANGE_CONFIG_TIMEOUT_MACROP_HI = 0x71
_MSRC_CONFIG_TIMEOUT_MACROP = 0x46
_IDENTIFICATION_MODEL_ID = 0xC0
_OSC_CALIBRATE_VAL = 0xF8
_GLOBAL_CONFIG_SPAD_ENABLES_REF_0 = 0xB0
_GLOBAL_CONFIG_REF_EN_START_SELECT = 0xB6
_DYNAMIC_SPAD_NUM_REQUESTED_REF_SPAD = 0x4E
_DYNAMIC_SPAD_REF_EN_START_OFFSET = 0x4F
_VHV_CONFIG_PAD_SCL_SDA__EXTSUP_HV = 0x89
_GPIO_HV_MUX_ACTIVE_HIGH = 0x84

# ST's default tuning settings (vl53l0x_tuning.h), as (reg, value) pairs.
_TUNING = (
    (0xFF, 0x01), (0x00, 0x00),
    (0xFF, 0x00), (0x09, 0x00), (0x10, 0x00), (0x11, 0x00),
    (0x24, 0x01), (0x25, 0xFF), (0x75, 0x00),
    (0xFF, 0x01), (0x4E, 0x2C), (0x48, 0x00), (0x30, 0x20),
    (0xFF, 0x00), (0x30, 0x09), (0x54, 0x00), (0x31, 0x04), (0x32, 0x03), (0x40, 0x83),
    (0x46, 0x25), (0x60, 0x00), (0x27, 0x00), (0x50, 0x06), (0x51, 0x00), (0x52, 0x96),
    (0x56, 0x08), (0x57, 0x30), (0x61, 0x00), (0x62, 0x00), (0x64, 0x00), (0x65, 0x00),
    (0x66, 0xA0),
    (0xFF, 0x01), (0x22, 0x32), (0x47, 0x14), (0x49, 0xFF), (0x4A, 0x00),
    (0xFF, 0x00), (0x7A, 0x0A), (0x7B, 0x00), (0x78, 0x21),
    (0xFF, 0x01), (0x23, 0x34), (0x42, 0x00), (0x44, 0xFF), (0x45, 0x26), (0x46, 0x05),
    (0x40, 0x40), (0x0E, 0x06), (0x20, 0x1A), (0x43, 0x40),
    (0xFF, 0x00), (0x34, 0x03), (0x35, 0x44),
    (0xFF, 0x01), (0x31, 0x04), (0x4B, 0x09), (0x4C, 0x05), (0x4D, 0x04),
    (0xFF, 0x00), (0x44, 0x00), (0x45, 0x20), (0x47, 0x08), (0x48, 0x28), (0x67, 0x00),
    (0x70, 0x04), (0x71, 0x01), (0x72, 0xFE), (0x76, 0x00), (0x77, 0x00),
    (0xFF, 0x01), (0x0D, 0x01),
    (0xFF, 0x00), (0x80, 0x01), (0x01, 0xF8),
    (0xFF, 0x01), (0x8E, 0x01), (0x00, 0x01), (0xFF, 0x00), (0x80, 0x00),
)


def _decode_timeout(reg_val):
    return ((reg_val & 0x00FF) << ((reg_val & 0xFF00) >> 8)) + 1


def _encode_timeout(mclks):
    if mclks <= 0:
        return 0
    ls, ms = mclks - 1, 0
    while ls & 0xFFFFFF00:
        ls >>= 1
        ms += 1
    return (ms << 8) | (ls & 0xFF)


def _macro_period_ns(vcsel_pclks):
    return ((2304 * vcsel_pclks * 1655) + 500) // 1000


def _mclks_to_us(mclks, vcsel_pclks):
    return (mclks * _macro_period_ns(vcsel_pclks) + 500) // 1000


def _us_to_mclks(us, vcsel_pclks):
    p = _macro_period_ns(vcsel_pclks)
    return (us * 1000 + p // 2) // p


class VL53L0X:
    def __init__(self, i2c, address=0x29, timing_budget_us=None, io_2v8=True):
        self.i2c = i2c
        self.address = address
        self.timeout_ms = 500
        self.status = 0
        self.budget_us = 0
        self._stop = 0
        self._continuous = False
        self._buf1 = bytearray(1)
        self.init_sensor(io_2v8)
        if timing_budget_us:
            self.set_timing_budget(timing_budget_us)

    # ---- register access -----------------------------------------------
    def _w(self, reg, val):
        self._buf1[0] = val
        self.i2c.writeto_mem(self.address, reg, self._buf1)

    def _r(self, reg):
        return self.i2c.readfrom_mem(self.address, reg, 1)[0]

    def _w16(self, reg, val):
        self.i2c.writeto_mem(self.address, reg, bytes(((val >> 8) & 0xFF, val & 0xFF)))

    def _r16(self, reg):
        b = self.i2c.readfrom_mem(self.address, reg, 2)
        return (b[0] << 8) | b[1]

    def _wait(self, reg, mask, want_set):
        """Poll until (reg & mask) is nonzero (want_set) or zero."""
        t0 = time.ticks_ms()
        while bool(self._r(reg) & mask) != want_set:
            if time.ticks_diff(time.ticks_ms(), t0) > self.timeout_ms:
                raise OSError("VL53L0X timeout")
            time.sleep_ms(1)

    # ---- init (VL53L0X_DataInit + StaticInit + PerformRefCalibration) ----
    def init_sensor(self, io_2v8=True):
        if self._r(_IDENTIFICATION_MODEL_ID) != 0xEE:
            raise OSError("VL53L0X not found (model id)")
        if io_2v8:
            self._w(_VHV_CONFIG_PAD_SCL_SDA__EXTSUP_HV, self._r(_VHV_CONFIG_PAD_SCL_SDA__EXTSUP_HV) | 0x01)
        self._w(0x88, 0x00)                       # I2C standard mode
        self._w(0x80, 0x01); self._w(0xFF, 0x01); self._w(0x00, 0x00)
        self._stop = self._r(0x91)
        self._w(0x00, 0x01); self._w(0xFF, 0x00); self._w(0x80, 0x00)
        # disable SIGNAL_RATE_MSRC and SIGNAL_RATE_PRE_RANGE limit checks
        self._w(_MSRC_CONFIG_CONTROL, self._r(_MSRC_CONFIG_CONTROL) | 0x12)
        self.set_signal_rate_limit(0.25)
        self._w(_SYSTEM_SEQUENCE_CONFIG, 0xFF)
        # reference SPADs
        count, is_aperture = self._spad_info()
        ref = bytearray(self.i2c.readfrom_mem(self.address, _GLOBAL_CONFIG_SPAD_ENABLES_REF_0, 6))
        self._w(0xFF, 0x01)
        self._w(_DYNAMIC_SPAD_REF_EN_START_OFFSET, 0x00)
        self._w(_DYNAMIC_SPAD_NUM_REQUESTED_REF_SPAD, 0x2C)
        self._w(0xFF, 0x00)
        self._w(_GLOBAL_CONFIG_REF_EN_START_SELECT, 0xB4)
        first = 12 if is_aperture else 0
        enabled = 0
        for i in range(48):
            if i < first or enabled == count:
                ref[i // 8] &= ~(1 << (i % 8))
            elif (ref[i // 8] >> (i % 8)) & 1:
                enabled += 1
        self.i2c.writeto_mem(self.address, _GLOBAL_CONFIG_SPAD_ENABLES_REF_0, ref)
        for reg, val in _TUNING:
            self._w(reg, val)
        # interrupt on new sample ready, active low
        self._w(_SYSTEM_INTERRUPT_CONFIG_GPIO, 0x04)
        self._w(_GPIO_HV_MUX_ACTIVE_HIGH, self._r(_GPIO_HV_MUX_ACTIVE_HIGH) & ~0x10)
        self._w(_SYSTEM_INTERRUPT_CLEAR, 0x01)
        self.budget_us = self.get_timing_budget()
        self._w(_SYSTEM_SEQUENCE_CONFIG, 0xE8)      # MSRC and TCC off
        self.set_timing_budget(self.budget_us)
        # reference calibration: VHV, then phase
        self._w(_SYSTEM_SEQUENCE_CONFIG, 0x01)
        self._ref_calibration(0x40)
        self._w(_SYSTEM_SEQUENCE_CONFIG, 0x02)
        self._ref_calibration(0x00)
        self._w(_SYSTEM_SEQUENCE_CONFIG, 0xE8)
        self._continuous = False

    def _spad_info(self):
        self._w(0x80, 0x01); self._w(0xFF, 0x01); self._w(0x00, 0x00)
        self._w(0xFF, 0x06)
        self._w(0x83, self._r(0x83) | 0x04)
        self._w(0xFF, 0x07); self._w(0x81, 0x01); self._w(0x80, 0x01)
        self._w(0x94, 0x6B); self._w(0x83, 0x00)
        self._wait(0x83, 0xFF, True)
        self._w(0x83, 0x01)
        tmp = self._r(0x92)
        self._w(0x81, 0x00); self._w(0xFF, 0x06)
        self._w(0x83, self._r(0x83) & ~0x04)
        self._w(0xFF, 0x01); self._w(0x00, 0x01); self._w(0xFF, 0x00); self._w(0x80, 0x00)
        return tmp & 0x7F, bool((tmp >> 7) & 1)

    def _ref_calibration(self, vhv_init_byte):
        self._w(_SYSRANGE_START, 0x01 | vhv_init_byte)
        self._wait(_RESULT_INTERRUPT_STATUS, 0x07, True)
        self._w(_SYSTEM_INTERRUPT_CLEAR, 0x01)
        self._w(_SYSRANGE_START, 0x00)

    # ---- configuration ---------------------------------------------------
    def set_signal_rate_limit(self, mcps):
        """Minimum return signal rate (MCPS) for a valid reading; 0.25 default."""
        self._w16(_FINAL_RANGE_CONFIG_MIN_COUNT_RATE_RTN_LIMIT, int(mcps * (1 << 7)))

    def _vcsel_pclks(self, reg):
        return (self._r(reg) + 1) << 1

    def _sequence(self):
        cfg = self._r(_SYSTEM_SEQUENCE_CONFIG)
        en = {"tcc": (cfg >> 4) & 1, "dss": (cfg >> 3) & 1, "msrc": (cfg >> 2) & 1,
              "pre": (cfg >> 6) & 1, "final": (cfg >> 7) & 1}
        pre_pclks = self._vcsel_pclks(_PRE_RANGE_CONFIG_VCSEL_PERIOD)
        msrc_mclks = self._r(_MSRC_CONFIG_TIMEOUT_MACROP) + 1
        pre_mclks = _decode_timeout(self._r16(_PRE_RANGE_CONFIG_TIMEOUT_MACROP_HI))
        final_pclks = self._vcsel_pclks(_FINAL_RANGE_CONFIG_VCSEL_PERIOD)
        final_mclks = _decode_timeout(self._r16(_FINAL_RANGE_CONFIG_TIMEOUT_MACROP_HI))
        if en["pre"]:
            final_mclks -= pre_mclks
        to = {"msrc_us": _mclks_to_us(msrc_mclks, pre_pclks), "pre_mclks": pre_mclks,
              "pre_us": _mclks_to_us(pre_mclks, pre_pclks), "final_pclks": final_pclks,
              "final_us": _mclks_to_us(final_mclks, final_pclks)}
        return en, to

    def get_timing_budget(self):
        en, to = self._sequence()
        us = 1910 + 960
        if en["tcc"]:
            us += to["msrc_us"] + 590
        if en["dss"]:
            us += 2 * (to["msrc_us"] + 690)
        elif en["msrc"]:
            us += to["msrc_us"] + 660
        if en["pre"]:
            us += to["pre_us"] + 660
        if en["final"]:
            us += to["final_us"] + 550
        self.budget_us = us
        return us

    def set_timing_budget(self, budget_us):
        """Time per measurement, us (20 ms min, ~33 ms default). Noise
        drops with the square root of the budget; 200 ms is ST's "high
        accuracy" profile."""
        en, to = self._sequence()
        used = 1910 + 960
        if en["tcc"]:
            used += to["msrc_us"] + 590
        if en["dss"]:
            used += 2 * (to["msrc_us"] + 690)
        elif en["msrc"]:
            used += to["msrc_us"] + 660
        if en["pre"]:
            used += to["pre_us"] + 660
        if en["final"]:
            used += 550
            if used > budget_us:
                raise ValueError("timing budget too small")
            final_mclks = _us_to_mclks(budget_us - used, to["final_pclks"])
            if en["pre"]:
                final_mclks += to["pre_mclks"]
            self._w16(_FINAL_RANGE_CONFIG_TIMEOUT_MACROP_HI, _encode_timeout(final_mclks))
            self.budget_us = budget_us

    # ---- ranging ---------------------------------------------------------
    def _preamble(self):
        self._w(0x80, 0x01); self._w(0xFF, 0x01); self._w(0x00, 0x00)
        self._w(0x91, self._stop)
        self._w(0x00, 0x01); self._w(0xFF, 0x00); self._w(0x80, 0x00)

    def _result(self):
        self.status = self._r(_RESULT_RANGE_STATUS) >> 3     # 11 = valid
        mm = self._r16(_RESULT_RANGE_STATUS + 10)
        self._w(_SYSTEM_INTERRUPT_CLEAR, 0x01)
        return mm

    def ping(self):
        """One blocking shot: mm (8190+ = nothing in range). self.status
        says whether the chip trusted it (11); 0 mm never comes back from
        an initialised chip, so treat 0 as 'no measurement'."""
        if self._continuous:
            self.stop_continuous()
        self._preamble()
        self._w(_SYSRANGE_START, 0x01)
        self._wait(_SYSRANGE_START, 0x01, False)
        self._wait(_RESULT_INTERRUPT_STATUS, 0x07, True)
        return self._result()

    def start_continuous(self, period_ms=0):
        """Measure on the chip's own clock: back-to-back (0) or every
        period_ms (must exceed the timing budget). range() then never
        blocks the caller's loop."""
        self._preamble()
        if period_ms:
            cal = self._r16(_OSC_CALIBRATE_VAL)
            if cal:
                period_ms *= cal
            self.i2c.writeto_mem(self.address, _SYSTEM_INTERMEASUREMENT_PERIOD,
                                 bytes(((period_ms >> 24) & 0xFF, (period_ms >> 16) & 0xFF,
                                        (period_ms >> 8) & 0xFF, period_ms & 0xFF)))
            self._w(_SYSRANGE_START, 0x04)
        else:
            self._w(_SYSRANGE_START, 0x02)
        self._continuous = True

    def stop_continuous(self):
        self._w(_SYSRANGE_START, 0x01)
        self._w(0xFF, 0x01); self._w(0x00, 0x00); self._w(0x91, 0x00)
        self._w(0x00, 0x01); self._w(0xFF, 0x00)
        self._continuous = False

    def range(self):
        """In continuous mode: the newest reading in mm, or None if the
        chip has not finished one since the last call."""
        if not (self._r(_RESULT_INTERRUPT_STATUS) & 0x07):
            return None
        return self._result()
