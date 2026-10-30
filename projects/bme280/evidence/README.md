# Evidence: modules sold as "BME280" are BMP280 (no humidity sensor)

Board under test: Raspberry Pi Pico 2 W, MicroPython 1.28.0, bare breadboard.
Test code: [`../identify.py`](../identify.py), run with [`../../../tools/bme-id.sh`](../../../tools/bme-id.sh).
It scans every valid Pico I2C pin pair and every address, then reads the Bosch
factory chip-ID register (0xD0) of each sensor found. Bosch assigns **0x60 to the
BME280** and **0x58 to the BMP280**. The script then takes live readings and runs a
10-second "breathe on it" humidity test.

## Result

| Unit | Address | Chip ID | Temperature | Pressure | Humidity |
| ---- | ------- | ------- | ----------- | -------- | -------- |
| Module sold as BME280 (HW-413A, "BME/BMP 280") | 0x76 | **0x58 = BMP280** | working | working | **not present**: calibration zeros, register constant, no response to breath |
| Genuine GY-BME280 (six-pin), same bus, same minute | 0x77 | 0x60 = BME280 | working | working | working: 50% to 79% when breathed on |

## Transcripts (in order)

- `20261028T131126Z-bare-board.txt`: nothing attached; every pin pair and address empty.
- `20261028T132439Z-six-pin-unwired-1.txt`, `...132551Z-...`, `...132604Z-...`: six-pin module with CSB/SDO floating, not yet on the bus.
- `20261028T132639Z-suspect-1.txt`, `20261028T132715Z-suspect-1.txt`: the suspect alone. Chip ID 0x58.
- `20261028T133837Z-six-pin-sdo-floating-bus-low.txt`: six-pin alone with SDO floating; bus held low.
- `20261028T134307Z-suspect-vs-sixpin.txt`: **the side-by-side**. Suspect at 0x76 (0x58, no humidity) next to a genuine BME280 at 0x77 (0x60, humidity responds).

## Photos

Camera metadata stripped; each photo carries a caption and the summary above in its EXIF fields.

- `20261028-photo-01-suspect-only-overview.jpg`: suspect alone, four wires to the Pico (3V3, GND, GP0, GP1).
- `20261028-photo-02-suspect-only-module-closeup.jpg`: the suspect board, HW-413A, "BME/BMP 280".
- `20261028-photo-03-suspect-only-pico-and-module.jpg`: same setup, side view.
- `20261028-photo-04-both-modules-genuine-bme280-added.jpg`: genuine six-pin BME280 added at 0x77.
- `20261028-photo-05-both-modules-suspect-side.jpg`: same, from the suspect's side.

## 2026-10-29: two more modules, a different order (not part of the seller packet)

Same test, same Pico. Both modules from a separate purchase showed the identical
signature: chip ID 0x58, humidity calibration all zeros, humidity register frozen
through the breath test, temperature and pressure working.

- `20261029T225139Z-pair2-both.txt`: both on the bus, 0x76 and 0x77. Both 0x58.
- `20261029T225431Z-pair2-sdo-low.txt`: **what an address collision looks like.** Both
  SDO pins tied low put both at 0x76; the calibration bytes read back as the bitwise
  AND of the two chips' tables (I2C is wired-AND) and temperature came out at -130 C.
- `20261029T225725Z-pair2-single-A.txt`, `20261029T225950Z-pair2-single-B.txt`: the same
  module alone, first at 0x77 then at 0x76 (identical calibration table = same die).

**Visual tell:** the metal sensor can on every BMP280 module is visibly smaller than
on a genuine BME280. That matches Bosch's packages: BMP280 is 2.0 x 2.5 mm, BME280 is
2.5 x 2.5 mm, about 25% more area.
