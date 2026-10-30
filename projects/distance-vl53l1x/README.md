# VL53L1X: Long-Range Laser Distance (4 meters)

**[Open this project in Viper IDE](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/distance-vl53l1x/package.json)**: one click installs everything it needs onto a connected Pico.

The VL53L0X's big sibling. Same time-of-flight idea, but it reaches to
about 4 meters instead of 1.2. Great for room-scale experiments:
people-counters, parking sensors, how-tall-is-it rigs.

## Wiring

| VL53L1X pin | Pico |
| ----------- | ---- |
| VIN | 3V3 (pin 36) |
| GND | GND (any GND pin, e.g. 38) |
| SDA | GP0 (pin 1) |
| SCL | GP1 (pin 2) |

**Address clash warning:** the VL53L1X and VL53L0X BOTH use I2C address
`0x29`. Only one of the two can be on the bus at a time. The driver
checks the chip's model id, so if you plug in the wrong one the demo
just reports "no sensor" instead of reading garbage.


## Wiring diagram

![distance-vl53l1x wiring](../../docs/wiring/distance-vl53l1x.svg)

Also in the [lab guide](https://makerlabkids.github.io/whs-wormhole/#wire-distance-vl53l1x). Red = 3V3, dark grey = GND (shared rails), green = SDA, white = SCL, yellow = signal, orange = VBUS 5V (alternate voltage). Numbers outside the board are physical header pins.

## Two versions

| File | What it does |
| ---- | ------------ |
| `bench.py` | OLED + terminal only. No Wi-Fi. |
| `main.py` + `index.html` | Everything above plus the PicoLabN access point with a live dashboard at http://192.168.4.1 (0 to 4 m bar, min/max) and JSON at `/data`. |

Files needed on the board: the version you chose, plus `index.html` (web
version only), plus from `lib/`: `picolab.py`, `vl53l1x.py`, `ssd1306.py`.

## Field of view (the `ROI` knob)

The chip sees a cone about 27 degrees wide. At 1 m that is a patch half a
metre across, and it reports the nearest strong thing anywhere in it: the
desk it is sitting on, a lamp beside the target, or the person leaning
over to watch. Both demos have an `ROI` constant at the top that narrows
the cone by using only the centre of the sensor's 16x16 pixel grid:

| `ROI` | Cone | Reach (white wall, dim room) | Use it for |
| ----- | ---- | ---------------------------- | ---------- |
| 16 | ~27 deg | ~4 m | room-scale, the longest reach |
| 8 | ~20 deg | ~2.5 m | the default here: forgiving of clutter |
| 4 | ~15 deg | ~1.5 m | a bin or a shelf, when only the middle matters |

Narrower collects less light, so reach drops. The driver scales the
sensor's minimum-signal limit with the ROI so a small region is not
rejected for light it never had. `tof.set_roi(n)` switches it live.

## Crosstalk: why a wall at 112 cm read 90 cm

Some emitter light reaches the receiver without leaving the module. The
chip can subtract it, but only if told how much, and these boards ship
with that number at zero. Untold, far and dim targets read short, and the
dimmer the target the shorter: one module read a plain wall at 1120 mm as
900 mm with the full cone, 929 mm with `ROI = 8`, 1023 mm with `ROI = 4`,
while a book at 500 mm was only 22 mm short. A hand in front looks fine,
which is why it goes unnoticed.

Calibrate once per module, with the ROI you will use, against a plain
wall at a tape-measured distance with nothing else in the cone and the
person well out of it:

    tools/laser-probe.sh 8 8 mywall 0 1120     # seconds, ROI, label, xtalk 0, wall at 1120 mm

It prints `XTALK = <n> kcps`; paste `n` into `XTALK` in the demo (and keep
`ROI` the same). Measured on that module against the 1120 mm wall after
calibration: full cone 1129 mm (3357 kcps), `ROI = 8` 1128 mm (3226 kcps),
`ROI = 4` 1095 mm (1570 kcps). The crosstalk is stronger at the edges of the
pixel grid, so the full-cone figure over-corrects a 4x4 centre by 13%:
calibrate per ROI, do not reuse. Driver calls: `tof.calibrate_xtalk(mm)`
returns the kcps, `VL53L1X(i2c, roi=8, xtalk=n)` applies it.

## Bench probe with a signal light

`probe.py` is a diagnostic, not a demo. It prints every measurement with
the chip's own health numbers (range status, return signal, ambient light,
sigma) and drives the Pico LED so the person holding a target, or staying
out of the beam, does not need to see a terminal: five slow flashes mean
get ready, a fast flicker means measuring, one long ON means done. Run it
with `tools/laser-probe.sh <seconds> <roi> <label> [xtalk_kcps] [calibrate_mm]`;
transcripts land in `~/.cache/wormhole-bench/`.

Things the probe found on the bench (October 2026):

- **No device anywhere, but SDA and SCL both idle high:** the two data
  wires are swapped. The chip answers only with SDA on GP0 and SCL on GP1.
- **Six-pin boards (VIN GND SCL SDA GPIO1 XSHUT):** leave GPIO1 and XSHUT
  unconnected. XSHUT pulled low puts the chip to sleep and it vanishes
  from the bus. GPIO1 is the chip's interrupt output; never drive it.
- **Readings far too short and jumpy:** something closer is inside the
  cone. The usual suspects, in the order we hit them: the person watching
  (30 to 40 cm away, leaning over the desk), a ceiling lamp, the desk
  surface under a board lying a few centimetres above it.
- **Ambient above about 1 MCPS** in the probe output means a light source
  is in the cone. A lit fixture close by read 6 MCPS and made one sample
  in four fail as wraparound.
- **A hand-held target under-reads** unless it is square to the sensor and
  fills the cone. Use a wall for accuracy checks.

## Notes

- The sensor free-runs at roughly 10 readings per second in long-range
  mode (the default here).
- "No target" is a real answer: beyond ~4 m, or nothing reflective in
  view, the range status goes invalid and the demo says so instead of
  showing a junk number.
- Driver: `lib/vl53l1x.py`, adapted from the MIT-licensed
  drakxtwo/vl53l1x_pico port of the ST ultra lite driver.
- Fault tolerance is the same as every demo: sensor and display are both
  optional and hot-pluggable, no restarts needed.

---

Fresh board? Flash the [tested MicroPython build](https://github.com/MakerLabKids/whs-wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2) first: hold BOOTSEL while plugging in, drop the file on the drive that appears, done. Details in [firmware/](../../firmware).
