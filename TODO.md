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
- [x] **BYLD saved on the Portal and Tunnels 1-3** (2026-11-01, from home): written straight into
      the Opal's saved list (`uci add repeater network`, ssid=BYLD, network=wwan, auto_portal=0,
      disguise=0; no key, it is open), so no school visit is needed. Every Tunnel: WormHole-Core
      selected (the one it returns to), Loki and BYLD as fallbacks. GL's daemon may load the new
      entry only at its next restart; the move to school power-cycles them anyway.
- [x] **Golden image** /workspace/burrow-golden.img.gz is burrow3's card at 73219d5 (2026-11-01 12:54,
      951 MB, boot + root only; the previous one is burrow-golden-0514253.img.gz, delete once the new
      one has made a card). Write: `sudo edge/burrow/tools/clone-card.sh write burrow-golden.img.gz
      /dev/sdX` (about 4 min). A spare Pi: never booted, swap means unplug the old one first (the new
      one enrols as that room's Burrow and the old one's token stops); keep the old card (its data).
- [ ] **Burrow2's buffered data** before 2026-10-29: its old card was binned (a laptop could not
      read it). Most of it had already reached the Surface.
- [ ] **First real rollout** (the Surface deploy is live): admin page -> Devices -> paste a commit,
      Update burrow0, watch it report the build; then the others one by one. (The Pi side was
      exercised tonight against GitHub directly: codeload stalled a 24 MB download, hence the
      bucket.)
- [x] **Surface deployed 2026-11-01 ~14:50** (standby enrolment + Pico code releases). First live code
      update: bench board (bin 38) 58939f0 over Wi-Fi, 17 files in 4 pushes, swapped, confirmed after a
      minute; name, bin.json, messages, calibration, shows + website playlist, and its main.py settings
      (pins, Roswell elevation, 3 unfitted parts) all kept. Golden image is 7c69e0c (standby-aware);
      burrow-golden-0514253 / -73219d5 can be deleted.
- [x] **Bad-update rollback proven on hardware** (2026-11-01 15:42-15:51): a throwaway commit whose main.py
      crashes at start (509f0e1, branch deleted) was released to the bench board: it took all 17 files,
      switched over, crashed, and exactly 5 min later boot.py's timer put 58939f0 back and reset; it reports
      "509f0e1: not confirmed within 5 min" and never fetched it again; shows and settings intact.
- [ ] Watch a real standby takeover once (a spare Pi on a room's Opal, then unplug the room's Pi):
      built and tested in code, not yet seen on hardware.
- [x] **Extra Pis never break a room** and **Pico code over Wi-Fi**: built and tested 2026-11-01
      (roles.py + Surface enrol; lib/ota.py + boot.py + Burrow relay + Devices panel; e2e 11/11
      against real GitHub). On all four Pis; on the bench board.
- [x] **MicroPython 1.29.0**: the default since 2026-11-01 (firmware/, all links, fleet flasher).
- [ ] **Reflash the classroom Picos** with the fleet flasher (`tools/fleet/flash.py`): everything
      since picolab 0.2.1 (marquee, shows, boot sequence, buffer + backfill, fixed addresses +
      PINs, messages over Wi-Fi/website/Bluetooth, link icon, NOT CONNECTED cards, dead-network
      rejoin, join stagger). Bins renumbered 30-79: relabel lids first. Recalibrate distance after.
- [x] **mkrlbs.com/whsbt -> whs.makerlabkids.com/bluetooth** works (2026-11-01; case-insensitive,
      HTTP://MKRLBS.COM/WHSBT for a smaller QR). The NOT CONNECTED card said mrklabs.com (a typo,
      fixed in worm-bin main.py; the classroom boards get it with the reflash).
- [ ] **`wrangler deploy` the Surface** (f411615): alerts stopped reaching the phone on 2026-11-01
      because of our own re-send loop (burrow1's event batches timed out while the Surface
      notified; each re-send called ntfy again). Fixed: reply first, notify after, re-sent
      batches deduplicated. After the deploy, burrow1's queue (48 events) drains in one go.
- [ ] **Physical fault tests** (an evening, with the clock): pull a Pi; pull a Tunnel; pull the
      provider; pull the internet; power everything off and on in random order; swap an Opal;
      swap a Pi (cloned card); two rollouts in a row. Pass times in the plan of 2026-10-31.

## Shows (kids' pictures and videos)

Phase 1 done 2026-11-01: lib/pbmshow.py (shows/*.pbm + shows.txt), docs/shows.html (tutorial +
converter), proven on the bench board. Classroom boards get it with the Pico reflash.
- [x] **Phase 2 built 2026-11-01** (946ccb6 Surface, 855a7cd Burrow, cfcdc18 Pico, b05c666 website):
      the bin's page has "Shows on the screen" (add a .pbm, delete, pick/order what plays, "On the
      bin"); the Burrow fetches files by sha256 and hands them over on a push; lib/showsync.py on the
      Pico fetches, checks, removes only the website's own files, writes shows.txt, reloads.
      tools/e2e/shows-e2e.sh: 15 checks, all pass. Burrows 0-2 run it; bench board runs it.
- [ ] **To go live (yours):** in cloud/surface, `npx wrangler d1 execute wormhole --remote --file
      schema.sql` (adds show_files/show_lists; safe to re-run), then `npx wrangler deploy`. Then try
      it on the bench board (bin 38, The Wrigglers) from its page. Classroom boards get it with the reflash.
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
