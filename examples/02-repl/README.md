# The REPL: talk to your Pico live

The REPL (Read, Evaluate, Print, Loop) is the `>>>` prompt in the Viper IDE
terminal. You type a line, the Pico runs it immediately, and answers. No files,
no saving, no waiting. It is the best way to poke at new hardware.

If you see no prompt, click into the terminal and press `Ctrl+C` to stop any
running program, then press `Enter`.

## Warm up

```python
>>> 2 + 2
>>> "worm" * 10
>>> name = "Ada"
>>> print("Hello,", name)
```

## Control real hardware, live

```python
>>> from machine import Pin
>>> led = Pin("LED", Pin.OUT)
>>> led.on()
>>> led.off()
>>> led.toggle()
```

That LED turned on because you told it to. Type `led.toggle()` a few times
(press the up arrow to repeat the last line instead of retyping it).

## Ask the board about itself

```python
>>> import os
>>> os.uname()
>>> import machine
>>> machine.freq()
```

## Scan the I2C bus (great for debugging wiring!)

```python
>>> from machine import I2C, Pin
>>> i2c = I2C(0, sda=Pin(0), scl=Pin(1))
>>> i2c.scan()
```

`i2c.scan()` returns the addresses of every device that answered. An OLED
shows up as 60 (0x3C) and the distance sensor as 41 (0x29). Empty list?
Check the wiring. This one line solves most "my sensor is dead" mysteries.

## Escape hatches worth memorizing

- `Ctrl+C` stops a running program and gives you the prompt back.
- `Ctrl+D` soft-reboots the board (runs `main.py` again if there is one).
- Up arrow repeats previous lines.

---

Fresh board? Flash the [tested MicroPython build](https://github.com/MakerLabKids/wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2) first: hold BOOTSEL while plugging in, drop the file on the drive that appears, done. Details in [firmware/](../firmware).
