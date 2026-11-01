# MicroPython Firmware for the Pico 2 W

Brand-new boards ship empty. This is the exact MicroPython build all the
demos in this repo are tested against, kept here so nobody has to hunt
for the right file on a workshop morning.

| File | Version | Source |
| ---- | ------- | ------ |
| `RPI_PICO2_W-20260824-v1.29.0.uf2` | **v1.29.0 (2026-08-24), use this** | [micropython.org/download/RPI_PICO2_W](https://micropython.org/download/RPI_PICO2_W/) |
| `RPI_PICO2_W-20260406-v1.28.0.uf2` | v1.28.0 (2026-04-06), the previous build, kept to roll back | same |

SHA-256 v1.29.0: `c49c7ed93eb7eeaaa78436b17bd4329e5d4ccbaebc1e79503ad75e0a29c4530e`
SHA-256 v1.28.0: `686f0d0bd427ca68d149016808f95765df7921c5845d22ff8ebaec287300fce4`
(both byte-identical to the official micropython.org releases; MicroPython is
MIT licensed). v1.29.0 was tried on the bench board on 2026-11-01 (Wi-Fi, pushes
to the Burrows, sensors, the screen and shows): no changes needed in our code.

## Flashing (about 15 seconds per board)

1. Hold the **BOOTSEL** button on the Pico while plugging it into USB.
2. It appears as a flash drive named `RP2350`.
3. Drag `RPI_PICO2_W-20260824-v1.29.0.uf2` onto the drive.
4. The drive disappears and the board reboots into MicroPython. Done:
   from here on, everything is Viper IDE and one-click installs.

Doing a classroom set? Leave the file on the desktop and do the boards
assembly-line style: hold, plug, drag, unplug, next.

This step is the one thing a browser cannot do: the bootloader is a
plain USB flash drive, so the file has to be copied on by hand (once per
board, ever).
