# Mission Control

**[Open this project in Viper IDE](https://viper-ide.org/?install=github:MakerLabKids/wormhole/projects/mission-control/package.json)**: one click puts a connected Pico on the classroom network.

One wall display for every station in the room. Stations keep running
their normal demos; the only change is WHERE they serve: instead of
each Pico opening its own PicoLabN hotspot, they all join the classroom
router, and an aggregator (a Pi Zero, or any laptop) finds them, polls
them once a second, and projects everything on one page.

## The classroom network

| Setting | Value |
| ------- | ----- |
| Router | GL.iNet GL-SFT1200 (the classroom kit) |
| SSID | `WormHole` |
| Password | `supersecret` |
| Subnet | 192.168.8.x (the GL.iNet default) |

## Station side (each Pico): one file

Installing this project drops `wifi.json` onto the board:

```json
{"ssid": "WormHole", "password": "supersecret"}
```

That is the whole switch. When `picolab.WebApp` starts and finds
`wifi.json`, it JOINS a network and serves its dashboard on its DHCP
address (printed in the terminal, shown on the OLED, and reported in
`/data`). If nothing joinable is around, the station opens its own
hotspot, so a board is ALWAYS reachable one way or another. Delete
`wifi.json` to force hotspot mode.

### Board identity (so you can tell them apart)

Every board has a permanent identity from its hardware serial number
(it survives a re-flash and a wiped filesystem):

- **`board_uid`** — the full 16-hex serial, globally unique, reported
  in `/data` as `id`. Trust this when uniqueness must be absolute.
- **name** — short and friendly, default `PicoLab<n>` where `<n>` is a
  stable 0-999 number from the uid (e.g. `PicoLab742`). It is the SSID
  in hotspot mode and the label on the wall. Write a `name.txt` on the
  board (`Bin-P3-4`) to rename it everywhere.

Every `/data` response carries `id`, `name`, `ip`, `ssid`, and `mode`,
so the wall labels tiles by name and a kid can read the exact address
to browse.

### The join ladder (how a teacher intervenes)

When it joins, a station tries these in order and takes the first that
is actually on the air (it scans first, so dead names cost nothing):

1. **`wormmaster<n>`** — `<n>` is this board's number (e.g.
   `wormmaster742`, shown on its OLED). Stand up a hotspot with that
   exact name and ONLY that one board hops onto it. Single-board rescue.
2. **`wormmaster`** — a plain hotspot (your phone) that EVERY board
   hops onto. Portable all-hands mode. (Controlled settings only: this
   is 40+ devices on one phone.)
3. **`WormHole`** — the real classroom network. Normal operation.
4. **its own hotspot** — if none of the above answer.

All four use the same password from `wifi.json`. Rename or disable the
rescue tier with a `"rescue"` key in `wifi.json` (`""` turns it off).

## Wall side: one command

On the Pi Zero (or any machine on WormHole):

```
python3 server.py
```

Open `http://<that machine>:8080` and put it on the projector. The
server scans 192.168.8.x for anything answering `/data`, adds new
stations as they appear, polls each every second, and flags any tile
red when a station stops answering. Config knobs (subnet, poll rate,
static station list) are at the top of `server.py`.

Raw aggregate for your own experiments: `/all.json`.

## Testing without hardware

```
MC_NOSCAN=1 MC_STATIONS=127.0.0.1:8181,127.0.0.1:8182 python3 server.py
```

points it at fake stations (anything serving `/data` JSON).

---

Fresh board? Flash the [tested MicroPython build](https://github.com/MakerLabKids/wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2) first: hold BOOTSEL while plugging in, drop the file on the drive that appears, done. Details in [firmware/](../../firmware).
