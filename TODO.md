# To do

Open items, newest first. Tick them off or delete them; the git log is the
record of what got done.

## Deploy (from 2026-10-31; updated 2026-11-01 morning)

Done 2026-11-01: Surface deploy + schema + ENROL_SECRET + TUNNEL_TOKENS; the four ssh-burrowN
hostnames (SSH through Cloudflare works on all four); burrow2 rebuilt from a cloned card and
enrolled; all four Pis on the same build; every Tunnel has WormHole-Core saved (`remember`) and
is on the backhaul; the Portal's backhaul AP watch on burrow0.

- [x] **Unhide the backhaul? No need.** Proven 2026-11-01 08:27-08:29: Portal 5 GHz off 60 s and on,
      all three Tunnels' Pis' watchdogs paused; all three Tunnels (two with ONLY the hidden backhaul
      saved) were back on WormHole-Core 35 s after the radio returned, by their own auto-connect.
      The fix was `remember`. (Tunnel 2's 6-min miss earlier that morning followed repeated failed
      joins against the wedged AP: GL.iNet backs off to 5-min retries.)
- [x] **Save the Portal's own upstreams**: done by itself 2026-11-01 08:59 (Guess failed, the
      Portal moved to Loki with remember; saved: Guess, Loki). The backhaul AP did NOT wedge
      this time (Tunnel 1 rejoined it in 6 s at 10:14), but hostapd logs "Failed to set beacon
      parameters" every 6 s since that switch: watch for it after the next upstream switch.
- [x] **Watchdog hold-before-switch + return-home** on all four Pis (2026-11-01 11:05: burrow1
      7223efa, the rest 9c5ba9c, same code). Repeat rejoin trials 10:16-10:57: 60 s outage ->
      back in 18-19 s, 5 min -> 42 s; an Opal returns to the network it was last told to join.
- [ ] **Portal hostapd "Failed to set beacon parameters"** every 6 s since its 08:59 switch to
      Loki (2.4 GHz AP dragged to ch 11). Harmless so far (11:20: burrow0's Wi-Fi joined that AP
      fine); if a Bin in room 0 can't join the
      Portal's WormHole, `wifi up radio0` on the Portal (or reboot it) is the first thing to try.
- [ ] **Teach each Tunnel a fallback at school**: `tools/routers/teach-fallback.py
      192.168.80.2N BYLD` for N = 1..3 (from the Portal's LAN, or on the Pi). At home all three
      know Loki (2026-11-01), with the `manual` flag on WormHole-Core; teach-fallback now checks that.
- [x] **Golden image** /workspace/burrow-golden.img.gz is burrow3's card (2026-11-01 08:20, build
      0514253, room 3 so its tunnel.json has the backhaul entry). Write: `sudo
      edge/burrow/tools/clone-card.sh write burrow-golden.img.gz /dev/sdX` (about 4 min).
- [ ] **Burrow2's buffered data** before 2026-10-29: its old card was binned (a laptop could not
      read it). Most of it had already reached the Surface.
- [ ] **First real rollout** (the Surface deploy is live): admin page -> Devices -> paste a commit,
      Update burrow0, watch it report the build; then the others one by one. (The Pi side was
      exercised tonight against GitHub directly: codeload stalled a 24 MB download, hence the
      bucket.)
- [ ] **Reflash the classroom Picos** with the fleet flasher (`tools/fleet/flash.py`): everything
      since picolab 0.2.1 (marquee, shows, boot sequence, buffer + backfill, fixed addresses +
      PINs, messages over Wi-Fi/website/Bluetooth, link icon, NOT CONNECTED cards, dead-network
      rejoin, join stagger). Bins renumbered 30-79: relabel lids first. Recalibrate distance after.
- [ ] **mrklabs.com/whsbt -> whs.makerlabkids.com/bluetooth** (on the NOT CONNECTED card): set up
      2026-11-01 but not working: every form lands on https://www.mrklabs.com/whsbt/ and IONOS says
      404 (the apex forwards to www first). The rule must be on www.mrklabs.com (IONOS builder).
- [ ] **Alerts reach no phone**: ALERT_URL is set (ntfy.sh), but every notify gets 429 "daily
      message quota" (ntfy.sh meters free posts per IP; Cloudflare's egress is shared, see
      2026-10-29). Pick: ntfy Supporter + ALERT_TOKEN, or a Discord webhook / Telegram bot URL in
      ALERT_URL (both supported), then the Devices page's test button.
- [ ] **Physical fault tests** (an evening, with the clock): pull a Pi; pull a Tunnel; pull the
      provider; pull the internet; power everything off and on in random order; swap an Opal;
      swap a Pi (cloned card); two rollouts in a row. Pass times in the plan of 2026-10-31.

## Shows (kids' pictures and videos)

Phase 1 done 2026-11-01: lib/pbmshow.py (shows/*.pbm + shows.txt), docs/shows.html (tutorial +
converter), proven on the bench board. Classroom boards get it with the Pico reflash.
- [ ] **Phase 2: send a show from the website over Wi-Fi** (no cable): upload on the Bin's
      website page (converter built in) -> Surface stores it (R2 or D1, per bin, size cap) ->
      the Burrow's snapshot reply names it -> the Bin GETs it from its Burrow, checks the hash,
      saves shows/NAME.pbm; plus picking/reordering the playlist from the website and the Bin's
      own dashboard (shows.txt written by the board).
- [ ] Try the tutorial with one team, especially the Viper IDE folder/upload steps (written
      from memory of Viper's file panel, not re-checked click by click).

## Bench board (The Wrigglers, now bin 38)

- [ ] It has a test `shows.txt` (wiggle, bar, Wormhole) and shows/wiggle.pbm + bar.pbm from
      2026-11-01: delete shows.txt to get every show back.

- [ ] **Eyeball the screen cycle** (flashed 2026-10-31 afternoon): card 2 s, name 5 s,
      marquee, name 5 s, a show (the wolverine zoom, the Maker Lab gear, then the ten
      worms, in order), then a message card, round again. The bench board has a test
      `msg.json` on it (slot 1 "Go Worms!" forever, slot 3 "Test slot 3" twice): clear
      them from the dashboard's MESSAGES card (Open, Clear) or `mpremote rm :msg.json`.

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

- [x] Bluetooth config: done 2026-10-31 (lib/blelink.py, the Nordic UART service; the
      website's /bluetooth.html page and any BLE terminal app).
- [x] Surface alert when a Bin reports a large `buffered` count: done 2026-11-01 (alerts.js
      watchBuffers, >= 60 rows, closes at 0). Also catches a Tunnel's wedged 2.4 GHz WormHole
      (the Bins buffer while their Burrow reports fine). Needs the `wrangler deploy` below.
- [ ] A battery RTC module on the Pico would turn "estimated" backfill timestamps
      (rows from a boot that never reached a Burrow) into exact ones. Only matters
      if a bin loses power *and* network for the same stretch.
- [x] `projects/distance-station` README: continuous mode + `status` paragraph (2026-11-01).
- [ ] `projects/distance-station/main.py` CALIBRATION_MAP predates the full VL53L0X driver:
      re-measure with a tape (needs a board on the bench).
