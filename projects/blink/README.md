# Blink: a real project, in levels

**[Open this project in Viper IDE](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/blink/package.json)**: one click installs everything it needs onto a connected Pico.

Blink is not a toy, it is the smallest honest program: hardware you can
see obeying code you wrote. So it gets the full project treatment,
levels and all, and every level runs on a bare Pico with zero wiring.

| File | Level | What it teaches |
| ---- | ----- | --------------- |
| `01_blink.py` | 1 | The simplest possible blink. Blinking = code running: the truth light at its most basic. |
| `02_blink_config.py` | 2 | The house rule: tunable numbers live AT THE TOP in CAPS. Change a knob, hit run. |
| `03_blink_async.py` | 3 | asyncio: blink perfectly WHILE doing other work. The gateway to every fault-tolerant station in this repo. |
| `advanced/04_morse_name.py` | 4 | Blink your name in real international morse code. Name goes in a config variable (at the top, obviously). |

## Moving on without leaving Viper

`toc.txt` (installed with this project) lists one-click install links
for every other project in the repo, including the EVERYTHING install
that puts all projects on the board at once. Open it in the Viper file
panel, copy a link into your browser, done.

---

Fresh board? Flash the [tested MicroPython build](https://github.com/MakerLabKids/whs-wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2) first: hold BOOTSEL while plugging in, drop the file on the drive that appears, done. Details in [firmware/](../../firmware).
