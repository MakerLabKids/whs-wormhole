# EVERYTHING: all projects on the board at once

One install, no more reloading. Every program from every project lands
on the board in its own folder, with all the drivers, so switching
activities is: **Stop** (Ctrl+C or the Stop button in Viper), open a
different file in the file panel, **Run**. You never leave Viper.

[One-click install](https://viper-ide.org/?install=github:MakerLabKids/whs-wormhole/projects/everything/package.json)

## What lands on the board

```
main.py, index.html      worm-bin, the capstone: runs at every boot
toc.txt                  install links to everything (read it in Viper)
lib/                     ALL drivers, as readable .py source
blink/                   the 4-level blink suite (01 simple ... morse)
bme280-demos/            hello / bench / main / multi tiers (named so the
                         folder cannot shadow the lib/bme280.py driver)
soil-temperature/        probe-array demos     soil-moisture/
light-basic/  light-lux/  sound/  servo/
distance-vl53l1x/  distance-station/
examples/                workshop examples 01, 03, 04, 05
```

So yes: run the worm-bin with a probe array and moisture bank, hit
Stop, open `blink/01_blink.py`, and run the simplest blink there is.
Same board, same minute.

## Notes

- `main.py` at the root is the worm-bin, so a bare power-up boots the
  capstone (POST codes and all). Running any other file from Viper
  temporarily replaces it until the next reboot.
- Each project's web tier serves its own dashboard from its folder
  (`picolab.WebApp(index="<project>/index.html")`).
- `distance-station` is the preserved original; under this layout its
  dashboard serves the root (worm-bin) page, so run it standalone if
  you want its own dashboard.
- Regenerate this package after adding files: `node tools/gen-packages.js`.

---

Fresh board? Flash the [tested MicroPython build](https://github.com/MakerLabKids/whs-wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2) first: hold BOOTSEL while plugging in, drop the file on the drive that appears, done. Details in [firmware/](../../firmware).
