# Worm Bin Command Center

**[Open this project in Viper IDE](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/worm-bin/package.json)**: one click installs everything it needs onto a connected Pico.

The capstone: every sensor in the toolbox, and the actuators, running
off ONE Pico at the same time. Everything is optional, hot-pluggable,
and reported honestly by the truth light, the OLED, and a live web
dashboard with controls.

## The full wiring

All I2C devices share the standard bus (SDA=GP0, SCL=GP1, 3V3, GND).

| Part | Where | Notes |
| ---- | ----- | ----- |
| OLED | I2C `0x3C` | one screen of whatever is reporting; pages only if that overflows |
| BME280 "in" | I2C `0x76` | inside the bin (SDO to GND) |
| BME280 "out" | I2C `0x77` | outside the bin (SDO to 3V3) |
| ADS1115 | I2C `0x48` | ADDR to GND; adds 4 analog channels |
| Soil moisture 1 | ADS1115 A0 | capacitive v1.2, VCC 3V3 |
| Soil moisture 2 | ADS1115 A1 | second probe, other end of the bin |
| Soil moisture, direct | GP26 (pin 31, ADC0) | no ADS1115: probe AOUT straight into the Pico, set `MOIST_PIN = 26` |
| GL5528 light divider | ADS1115 A2 | LDR to 3V3, 10k to GND, junction to A2 |
| MAX9814 mic | GP27 (pin 32, ADC1) | native ADC: needs the fast 25 ms sampling |
| DS18B20 probes | GP22 (pin 29) | one wire, many probes, 4.7k pullup to 3V3 |
| VL53L0X compaction | I2C `0x29` | lid-mounted, aimed down: gap to the bedding surface (settling/compaction) |
| Big servo (MG995) | GP16 (pin 21) | own 5V supply, grounds joined, NOT VBUS |
| Small servo (SG90) | GP17 (pin 22) | power from VBUS (pin 40) |
| Relay module | GP15 (pin 20) | module VCC per its spec (most take VBUS 5V) |

Free for expansion: GP26 (ADC0), GP28 (ADC2), ADS1115 A3, and the whole
second I2C bus (I2C1).

## The truth light

POST codes: one blink per part, in the order of the `PARTS` list in
`main.py`, then one slot per DS18B20 probe (always last, so adding a
probe grows the tail of the pattern without renumbering anything).
Short blink = OK, long blink = trouble, dark = code not running.

Default slot order: 1 BME in, 2 BME out, 3 ADS1115 bank, 4 mic, 5 light,
6 compaction, 7 lux, then the probes. Comment a part out of `PARTS` and its
slot disappears; the pattern only ever shows what you claim to have wired.
The mic and the light divider sit on bare ADC pins and cannot tell
"unplugged" from "quiet", so for a bin without them set `MIC_PIN = None`
or `LIGHT_PIN = None` in the config block: that drops them from the slots,
the screen, and the dashboard.

## Pressure

Weather reports quote pressure corrected to sea level; a BME280 reads the
real pressure where it sits, a few percent lower at our altitude. Set
`ELEVATION_M` in the config block (Woodstock High School is about 305 m)
and `press_hpa` on the screen, the JSON and the dashboard matches the
weather app, while `press_raw_hpa` keeps the uncorrected reading. Set it
to 0 to show the raw reading everywhere.

## The screen

The OLED shows one row per part that is reporting, nothing for parts that
are absent. A lean bin (one BME280, a probe, a moisture bank, the distance
sensor) fits on a single screen and never pages. Only when more rows exist
than fit (six under the title) does it page, and then only through rows
that exist, lingering on a page with a light sensor so you can shine a
torch at it. Servo and relay get a row only once something has been
commanded.

A lean bin recipe, for a board with one BME280, a probe, a moisture sensor
on GP26, the distance sensor and the OLED: in the config block set
`MOIST_PIN = 26`, `MIC_PIN = None`, `LIGHT_PIN = None`, and comment
`bme("in", 0x76)`, `analog_bank()` and `lux_meter()` out of `PARTS`. The
result is a single screen and a truth light with four short blinks.

## Dashboard

Join the PicoLabN network, browse to http://192.168.4.1: live cards
for both airs, both moistures, light, sound, compaction, and every probe,
plus sliders for both servos and a relay button. JSON at `/data`,
actuator control at `/set?big=90`, `/set?small=45`, `/set?relay=1`.

## Calibration

`MOIST_DRY_V` / `MOIST_WET_V` at the top of `main.py` are in VOLTS
(the ADS1115 reads volts, not Pico counts). Watch `moist1_v` on the
dashboard with the probe dry in air, then in a cup of water up to the
marked line, and edit the two numbers.

## Power rules

- The MG995 gets its OWN 5V supply, grounds joined to the Pico. VBUS
  cannot feed a stalled MG995.
- The SG90 drinks from VBUS (pin 40), never 3V3.
- Everything else runs on 3V3.

Files needed on the board: `main.py`, `index.html`, and from `lib/`:
`picolab.py`, `ssd1306.py`, `bme280.py`, `ads1115.py`, `vl53l0x.py`.
Or use the one-click install link in the repo README.

---

Fresh board? Flash the [tested MicroPython build](https://github.com/MakerLabKids/whs-wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2) first: hold BOOTSEL while plugging in, drop the file on the drive that appears, done. Details in [firmware/](../../firmware).
