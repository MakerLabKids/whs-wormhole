# BME280: Temperature, Humidity, Pressure

**[Open this project in Viper IDE](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/bme280/package.json)**: one click installs everything it needs onto a connected Pico.

The environment sensor. Reads air temperature, relative humidity, and
barometric pressure over I2C. Also works with a BMP280 (its humidity-free
sibling; the demo reports humidity as n/a).

## Wiring

| BME280 pin | Pico |
| ---------- | ---- |
| VIN / VCC | 3V3 (pin 36) |
| GND | GND (any GND pin, e.g. 38) |
| SDA | GP0 (pin 1) |
| SCL | GP1 (pin 2) |

I2C address `0x76` or `0x77` (the demo finds either automatically).


## Wiring diagram

![bme280 wiring](../../docs/wiring/bme280.svg)

Also in the [lab guide](https://makerlabkids.github.io/whs-wormhole/#wire-bme280). Red = 3V3, dark grey = GND (shared rails), green = SDA, white = SCL, yellow = signal, orange = VBUS 5V (alternate voltage). Numbers outside the board are physical header pins.

## Four tiers, from bare to mack daddy

| File | What it does | Truth light |
| ---- | ------------ | ----------- |
| `hello.py` | The fewest lines that prove the sensor works. Terminal only, no framework. | Solid ON while readings are good, OFF when not |
| `bench.py` | OLED + terminal, fault tolerant, hot-pluggable. No Wi-Fi. | Short blink = OK, long blink = trouble |
| `main.py` + `index.html` | Everything above plus the PicoLabN access point with a live dashboard at http://192.168.4.1 and JSON at `/data`. | Same as bench |
| `multi.py` | TWO hot-swappable BME280s (0x76 inside the bin, 0x77 outside), both on the OLED plus the temperature difference. | POST codes: one blink per sensor in order. `. .` = both happy, `_ .` = sensor 1 unhappy |

Files needed on the board: the tier you chose, plus `index.html` (web
version only), plus from `lib/`: `bme280.py` (all tiers), and
`picolab.py` + `ssd1306.py` (every tier except `hello.py`).

Note for `multi.py`: a BME280 board's address is set by its SDO pad or
pin (SDO to GND = `0x76`, SDO to 3V3 = `0x77`). Two sensors on one bus
need one of each.

## Known boards and their quirks

- **HW-413A, silkscreen "BME/BMP 280", 4 pins (VIN GND SCL SDA).** Sold as
  BME280, but a batch bought in October 2026 carried BMP280 chips (chip ID
  `0x58`, no humidity sensor). Run `identify.py` before trusting any new
  batch; it asks the chip what it is. These boards also answer the Pico's
  *hardware* I2C address probe and then fail every data byte (`OSError 5`),
  while bit-banged `machine.SoftI2C` talks to them fine. `lib/picolab.py`
  uses the hardware controller, so if a demo finds the sensor in the scan
  but every read fails, this board is the first suspect.
- **GY-BME280 / "GY-BM ME/PM 280", 6 pins (VCC GND SCL SDA CSB SDO).**
  Genuine BME280 in the batch tested. CSB **must** be tied to 3V3 or the
  chip wakes in SPI mode and ignores I2C. SDO picks the address (GND =
  `0x76`, 3V3 = `0x77`); left floating it dragged SDA and SCL low and
  silenced every other device on the bus.

Evidence runs and photos for the October 2026 return are in [`evidence/`](evidence/).

## Fault tolerance (all demos work this way)

- Boots and runs fine with no sensor, no display, or neither.
- Plug the sensor in mid-run: readings appear within ~2 seconds.
- Plug the display in mid-run: it lights up within ~3 seconds.
- Terminal shows a startup banner and first readings immediately, then a
  heartbeat line every 5 seconds.
- The onboard LED never lies: if it is dark, the code is not running; if
  it is blinking, the blink pattern says exactly which part is unhappy.

---

Fresh board? Flash the [tested MicroPython build](https://github.com/MakerLabKids/whs-wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2) first: hold BOOTSEL while plugging in, drop the file on the drive that appears, done. Details in [firmware/](../../firmware).

## Wiring two at once

The SDO pad picks the address (GND = 0x76, 3V3 = 0x77), so two share the bus:

![two BME280s](../../docs/wiring/bme280-multi.svg)
