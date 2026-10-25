# Raspberry Pi Pico 2 W Samples

MicroPython samples for the Raspberry Pi Pico 2 W, used in
[Maker Lab Kids](https://MakerLabKids.com) workshops. Everything here is
written to run from [Viper IDE](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/everything/package.json),
a MicroPython IDE that runs entirely in your browser. Nothing to
install on your computer, and that link puts every project in this
repo onto a connected Pico in one click.

## The workshop, in order

The order is the point. Every session proves one new layer works before
the next layer stacks on top of it. By the time you touch a sensor, the
IDE, the firmware, the code push, the standalone boot, the breadboard,
and your solder joints have each already been tested on their own. When
something fails (and something always fails), you know it is the thing
you just added.

| # | Session (Google Slides) | You prove | Code | One-click install |
| - | ----------------------- | --------- | ---- | ----------------- |
| 0 | [Intro](https://docs.google.com/presentation/d/1VmO9SPvXj8zbI5XZCL2dS0yMJWh22NcaxGVX-JmjQQw/edit) | Why we are here | | |
| 1 | [Microcontrollers](https://docs.google.com/presentation/d/1RxtswPo1zEJnJrIV_41OHcRE-VmT5EBSG0QASNvSTmc/edit) | IDE connects, [firmware loads](https://github.com/MakerLabKids/whs-wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2) (BOOTSEL + drop the .uf2), code pushes, board runs on wall power alone | [`01-hello-world`](examples/01-hello-world) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/examples/01-hello-world/package.json) |
| | | | [`02-repl`](examples/02-repl) | (live typing, nothing to install) |
| | | | [`03-blink`](examples/03-blink) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/examples/03-blink/package.json) |
| | | | [`04-webserver`](examples/04-webserver) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/examples/04-webserver/package.json) |
| 2 | [Electronics & Breadboarding](https://docs.google.com/presentation/d/1kIFo55Gud8giLK1EXfJmg93TvXiee9olfJTwIP6mam0/edit) | Wires between parts: breadboard an OLED, light it up with code you already know how to push | [`05-display`](examples/05-display) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/examples/05-display/package.json) |
| 3 | [Soldering](https://docs.google.com/presentation/d/11ljAAl6ed294Y0mCDvBkVQ-DEHRQteocGM60CHtX8OA/edit) | Your joints carry signal: solder headers, then re-run `05-display` through them | (re-use `05-display`) | |
| 4 | [Sensors](https://docs.google.com/presentation/d/1UwEEIvA_2MJz9nRdW57ctLzZHtoa2Pqetn40p2y5BvY/edit) | Real measurements on a bus you trust | [all projects below](#sensor-demo-projects) | per-project links below |

## Quickstart

1. **Get MicroPython on the board (one time).** Hold the BOOTSEL button while
   plugging the Pico into USB. It appears as a flash drive. Drag on the
   Pico 2 W firmware:
   [download the exact tested build from this repo](https://github.com/MakerLabKids/whs-wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2)
   (see [`firmware/`](firmware/); newer builds live at
   [micropython.org/download/RPI_PICO2_W](https://micropython.org/download/RPI_PICO2_W/)).
   The drive disappears and the board reboots into MicroPython.
2. **Open [viper-ide.org](https://viper-ide.org)** in Chrome or Edge.
3. Click the **connect** button (top right), pick **USB**, and choose the
   Pico from the list.
4. Use the file panel to create or upload files, and the terminal panel to
   run them and to use the REPL.

A file saved to the board as `main.py` runs automatically every time the
board powers up. That is how a finished project "ships."

## Use the light

Every demo drives the onboard LED as a **truth light**, so you never have
to guess whether the code is running or whether 3V3 is shorted to ground.

- **Simplest demos** (`hello.py` tier): solid ON means it is working,
  OFF means it is not. That is the whole story.
- **Framework demos** (everything built on `picolab.py`): POST blink
  codes. One blink per part, in a fixed order, then a pause, then repeat.
  Short blink = that part is OK. Long blink = that part is in trouble.
  With five probes, `. . . _ .` means probe 4 has a problem. Fix the
  loose wire and it goes back to `. . . . .`. Add a sixth probe and the
  pattern grows to six blinks.
- **No light at all** means the code is not running. Always.

The pattern lives in `picolab.StatusLight`; every project wires it in.

## What's here

| Folder | What it teaches |
| ------ | --------------- |
| `examples/01-hello-world` | Run your first program, read output in the terminal |
| `examples/02-repl` | Talk to the board live at the `>>>` prompt, scan I2C |
| `examples/03-blink` | Control real hardware: the onboard LED |
| `examples/04-webserver` | The Pico becomes a Wi-Fi hotspot serving its own website |
| `examples/05-display` | First breadboard circuit: an OLED on the I2C bus |
| `lib/` | Shared code: drivers plus `picolab.py`, the fault-tolerance framework all sensor demos use |
| `projects/` | One demo per sensor, plus the servo, plus `worm-bin`, the everything-at-once capstone. See the table below |
| `docs/` | The branded lab guide (GitHub Pages site) |

Work top to bottom. Each example is one idea bigger than the last, and the
projects use all of them at once.

## Sensor demo projects

Every project (except the original `distance-station`) comes in at least
two versions: `bench.py` (OLED + terminal, no Wi-Fi) and `main.py` +
`index.html` (adds the PicoLabN access point with a live dashboard at
http://192.168.4.1 and JSON at `/data`). All of them are fault tolerant:
they run with the sensor missing, the display missing, or both, and pick
parts up the moment they are plugged in, no restart needed. And every one
of them uses the truth light.

| Project | Sensor / actuator | Signal | Wiring | One-click install |
| ------- | ----------------- | ------ | ------ | ----------------- |
| [`everything`](projects/everything) | ALL projects on the board at once, each in its own folder, plus all drivers and a toc.txt of install links. Stop, open a file, run: never leave Viper | | | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/everything/package.json) |
| [`blink`](projects/blink) | The blink suite, 4 levels: simple, config-at-top, async, and morse-code your name | onboard LED, no wiring | | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/blink/package.json) |
| [`worm-bin`](projects/worm-bin) | THE CAPSTONE: 2 BME280s, DS18B20 array, 2 soil moistures + light on an ADS1115, mic, soil-compaction ToF, 2 servos, relay, all on one Pico with POST codes and a control dashboard | see its README | [table](projects/worm-bin#the-full-wiring) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/worm-bin/package.json) |
| [`bme280`](projects/bme280) | BME280 temperature + humidity + pressure, in four tiers up to two hot-swappable sensors at once | I2C `0x76/0x77` | [diagram](docs/wiring/bme280.svg) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/bme280/package.json) |
| [`soil-temperature`](projects/soil-temperature) | DS18B20 waterproof probes (many per wire) | GP22 (pin 29) + 4.7k pullup | [diagram](docs/wiring/soil-temperature.svg) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/soil-temperature/package.json) |
| [`soil-moisture`](projects/soil-moisture) | Capacitive soil moisture v1.2 | GP26 (pin 31, ADC0) | [diagram](docs/wiring/soil-moisture.svg) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/soil-moisture/package.json) |
| [`light-basic`](projects/light-basic) | GL5528 photoresistor divider | GP28 (pin 34, ADC2) | [diagram](docs/wiring/light-basic.svg) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/light-basic/package.json) |
| [`light-lux`](projects/light-lux) | BH1750 lux sensor | I2C `0x23` | [diagram](docs/wiring/light-lux.svg) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/light-lux/package.json) |
| [`sound`](projects/sound) | MAX9814 mic amp, sound level meter | GP27 (pin 32, ADC1) | [diagram](docs/wiring/sound.svg) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/sound/package.json) |
| [`servo`](projects/servo) | SG90 servo, driven from the web dashboard | GP16 (pin 21, PWM), VBUS power | [diagram](docs/wiring/servo.svg) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/servo/package.json) |
| [`distance-station`](projects/distance-station) | VL53L0X time-of-flight; in the bins it measures **soil compaction** (gap from lid to bedding surface) | I2C `0x29` | [diagram](docs/wiring/distance-station.svg) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/distance-station/package.json) |
| [`distance-vl53l1x`](projects/distance-vl53l1x) | VL53L1X long-range time-of-flight (to 4 m); deeper bins or lid-mounted compaction with more headroom | I2C `0x29` (not with a VL53L0X!) | [diagram](docs/wiring/distance-vl53l1x.svg) | [install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/distance-vl53l1x/package.json) |

## One-click installs from Viper IDE

Every example and every project has a `package.json`, so with your Pico
connected in Viper IDE, one click installs everything it needs: the
project files onto the board's root and the needed drivers into `/lib`.
Link format:

```
https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/<name>/package.json
https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/examples/<name>/package.json
```

Install links for every project are in the tables above and on the
[lab guide](https://makerlabkids.github.io/whs-wormhole/). Installing just the
drivers (no project files) is the plain repo link:
`https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole`.

## Installing the drivers

Projects need some of the files in `lib/` copied onto the board (each
project's README lists exactly which). Two ways:

- **Viper IDE:** upload the needed `lib/` files to the board alongside
  your `main.py`. All sensor demos need `picolab.py` and `ssd1306.py`,
  plus the sensor's own driver if it has one.
- **mip, from the REPL** (needs the Pico joined to a Wi-Fi network that has
  internet; our classroom access points do not, so use the upload method
  in class):

  ```python
  import mip
  mip.install("github:MakerLabKids/whs-wormhole")
  ```

## Wiring used throughout

All I2C devices share one bus on I2C0, and the wire colors are the
class convention: match them and anyone can debug your breadboard.

| Signal | Wire color | Pico pin |
| ------ | ---------- | -------- |
| SDA | green | GP0 (pin 1) |
| SCL | white | GP1 (pin 2) |
| Power | red | 3V3 (pin 36) |
| Ground | black | GND (any GND pin, e.g. 38) |

Device addresses: OLED `0x3C`, VL53L0X distance sensor `0x29`. Check your
wiring any time with two lines in the REPL:

```python
i2c = machine.I2C(0, sda=machine.Pin(0), scl=machine.Pin(1))
i2c.scan()
```

Learn. Make. Share.
