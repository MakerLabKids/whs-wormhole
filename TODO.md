# To do

Open items, newest first. Tick them off or delete them; the git log is the
record of what got done.

## Deploy (from 2026-10-31)

- [ ] **Burrow code to the four classroom Pis** (burrow0-3): `edge/burrow` now has
      `POST /ingest/batch` (backfill after an outage) and the dash shows a Bin's
      `buffered` count. Until the Pis have it, a Bin that comes back from an outage
      gets a 404 for its batches and just keeps them (nothing is lost, it retries
      every push tick).
- [ ] **Reflash the classroom Picos** with the fleet flasher (`tools/fleet/flash.py`):
      picolab 0.2.1 (flash buffer, title marquee, smoothed distance), the new
      `lib/vl53l0x.py` (full init: the old one read ~80 mm long and died at close
      range), and the worm-bin `main.py` (continuous-mode ranging, LABEL: value rows).
- [ ] **Bins are renumbered fleet-wide, 30 to 79** (`roster.csv`, 2026-10-31): the bin number
      is now the board's address on both networks and part of its PIN. Re-label the lids to
      match before the reflash (the reflash writes the new number into each board), and
      re-run `tools/fleet/flash.py --renumber` first if you want a different start than 30
      (`bin_first` in fleet.json).
- [ ] **Recalibrate every bin's distance sensor after the reflash** (the old
      calibration belongs to the old driver): on the dashboard's Surface card,
      capture the empty bin depth (lid to the paper towel, ~175 mm on the viewer
      bins) and a box/book at a measured ~64 mm, then Apply. Each module has its own
      offset and slope (the bench one: raw 120 at 64, raw 232 at 175).
- [ ] **Surface (Cloudflare) deploy + `ALERT_URL`** (carried over): `wrangler deploy`
      from your laptop, and the alert URL as `https://`.

## Bench board (The Wrigglers, now bin 38)

- [ ] **Eyeball the screen cycle** (2026-10-31 12:55, flashed): card 2 s, name 5 s,
      marquee, name 5 s, a worm show, round again with the next show. The readings
      keep updating under the shows. (The splash-demo `main.py` is gone from the board;
      `main_wormbin.py` on it is now a stale copy and can be deleted.)

- [ ] **Moisture probe reads 100 % at 0.4 V** since the wire fix. Dry in air it read
      2.7 V this morning. Check which pin the AOUT wire is on (GP26 = pin 31) and
      redo the dry/wet points on the dashboard if the probe moved.
- [ ] **DS18B20 bus on GP22 reports trouble** every cycle: no probes found, or no
      4.7k pullup to 3V3.
- [ ] **The breadboard's 3V3 rail went dead and came back without being touched**,
      and the distance sensor dropped off the I2C bus whenever its laser fired until
      the moisture wire was reseated. Both are rail/jumper flakiness. For the
      classroom bins: soldered or screw-terminal power rails, not breadboard jumpers.
- [ ] **Eyeball the title marquee** on the OLED: team name centered 5 s, then
      "Woodstock High School and Maker Lab Kids - Vermiculture PBL by:" scrolls
      through at 50 px/s, name again. (Checked off-board and in the log, not watched.)

## Ideas, not scheduled

- [ ] **Bluetooth config** (rename / PIN entry over BLE from a phone with no Wi-Fi
      switch): the Pico 2 W has BLE and MicroPython's `aioble` exists, but nothing on
      the board speaks it yet. The Wi-Fi PIN gate (2026-10-31) covers the dashboard.
- [ ] Surface alert when a Bin reports a large `buffered` count (it means every
      Burrow it can see has been dark for that many minutes).
- [ ] A battery RTC module on the Pico would turn "estimated" backfill timestamps
      (rows from a boot that never reached a Burrow) into exact ones. Only matters
      if a bin loses power *and* network for the same stretch.
- [ ] `projects/distance-station` demo: its README still describes the single-shot
      driver; the new driver's continuous mode and `status` are worth a paragraph.
