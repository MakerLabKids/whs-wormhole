# To do

Open items, newest first. Tick them off or delete them; the git log is the
record of what got done.

## Next steps (2026-11-01 evening) - start here

**No Bins are in the field.** The Picos the kids soldered and tested (distance sensor + display,
Oct 20) went back in the pile; every Pico gets flashed fresh before it is used, so nothing old is
out there and nothing needs migrating. A Pico is set up once by cable and updated over Wi-Fi after.

1. **Leaked passwords: rotated 2026-11-01.**
   - 17:17: new `router_admin` = `backhaul_key` (from .env) on all four Opals, the Portal's WormHole-Core,
     each Tunnel's saved entry and each Pi's tunnel.json; the old value is refused everywhere.
     (Procedure: notes/CLAUDE-RUNBOOK.md 4.9.)
   - Then the Surface admin login: the same new value (the human's choice), set with the admin reset; old
     login refused (401), admin sessions dropped. ~/.config/wormhole/pi-password line 1 updated to match.
   - Still the old value: the Pis' `worm` user password. Low risk (sshd is keys-only, sudo needs no
     password), change only if the human asks.
   - Kept on purpose (the human's call): the WormHole/Pico key, which equals guess_psk and qtastic_psk.
   - Purging public history: optional, only with the human's go-ahead.
1b. **Fans (arrived 2026-11-01).** Code is in (1db189d), wiring in 8fb2120: a 2N2222 on GP15 (pin 20), 470 ohm base, diode
   across the fan (docs/wiring/fan.svg). Bench run with the human: 2026-11-02. Every
   15 min, inside humidity over 80% runs it 1 min; at power-on it toggles with each boot screen while
   `FAN_BOOT_DEMO = True`. After the demo period: set `FAN_BOOT_DEMO = False` (3 s at power-on). Not yet
   run on a real board with a fan. The Surface is deployed (11-01: the navbar's GitHub link goes to the
   Pages lab guide, checked live); the Burrows pick up the same page with their next update.
2. **Set up the Picos for the bins** (first one, then the rest): fleet flasher
   `tools/fleet/flash.py` (MicroPython 1.29, the worm-bin code, boot.py + lib/ota.py, wifi.json,
   bin.json with the bin number 30-79). Label the lids to match. Do ONE first: Claude checks its
   pushes and sends it a Wi-Fi code update before the rest. Recalibrate distance once mounted.
3. **Golden image refreshed 2026-11-03 00:30** from burrow3 (496ff1b: current router password and
   backhaul key, the 0640 cloud-token fix); validated (gzip -t, 6987710464 bytes, p3 at 13647872). The
   old one is burrow-golden-7c69e0c.img.gz: its cards need tunnel.json + token mode fixed by hand.
   The old burrow3 Pi/card (silent since 11-01 18:54) is retired: re-burn its card before reuse.
   **Re-burn the spare Pi cards** from /workspace/burrow-golden.img.gz with the current
   `sudo edge/burrow/tools/clone-card.sh write burrow-golden.img.gz /dev/sdX` (it now adds the
   enrolment secret; cards burned before 2026-11-01 14:30 lack it and cannot enrol).
4. **Watch a real standby takeover**: a spare Pi on a room's Opal (shows up as burrowN-sb-xxxx on
   the Devices page), then unplug the room's Pi: it should take over in ~10 min.
5. **Try "Make your own show" with one team**, especially the Viper IDE upload steps (not yet
   clicked through), and the website's "Shows on the screen" card.
6. **Fault-test evening** (with Claude, a clock): pull a Pi, a Tunnel, the internet, power in
   random order; swap an Opal; swap a Pi from a cloned card; a spare left plugged in; two rollouts
   in a row; a Pico code update to every bin.
7. **Built 2026-11-01 evening, not yet on hardware:** (a) the watchdog restarts a room's 2.4 GHz
   WormHole when every Bin heard in the last 2 h has been silent 10 min (hourly at most), then reboots
   the Opal if still silent 10 min later (6-hourly at most) (ed3887d): on burrow0/1/2; **burrow3 was
   offline (silent since 18:54); on 2026-11-03 00:00 a fresh card (serial e53556f0) enrolled as burrow3 in its place and is on 496ff1b**. (b) Bin settings in
   settings.json, edited on the bin's page (Settings card; lib/settings.py): checked off-board and in a
   browser against the real module, not yet on a board; try it on the bench board with the fan.

Where things are: private notes/runbook/detailed architecture in MakerLabKids/whs-wormhole-private
(notes/ here); teacher overview in the lab guide (How Wormhole Works).

## Deploy (from 2026-10-31; updated 2026-11-01 morning)
- [ ] **Two-step rename (05fa2c8)**: try it first on one of the user's home test bins (NOT The Wrigglers, bin 38: that is
      Audra's demo bin; leave it as it is, the demo sheet matches it). Then roll the Pico code out; the website's
      Bluetooth page goes live with the next `wrangler deploy`.
- [x] **5267724 on all four Pis (2026-11-03 08:48)**: peer list written as {"url"} dicts (broke the peer watch on
      freshly enrolled cards) and roles.py's enrol request had no User-Agent, so Cloudflare answered 403 / error 1010:
      a refused Pi could never re-ask and a standby could never take over. burrow3 recovered at 08:46 by re-asking.
- [ ] **Refresh the golden image** from a Pi on 5267724 (cards burned from the old image carry both bugs until updated).
- [ ] The spare card from 2026-11-03 holds a revoked burrow3 pass: in a different Pi it is refused, re-asks after
      10 min and should come up as a standby. Watch that once (first real test of the fixed re-ask).

- [ ] **User: `npx wrangler deploy` in cloud/surface** for 0a1f923 + the skins dropdown + the admin People screens (add a teacher/admin; a class from a CSV with printable slips, 2026-11-03) (2026-11-02; the Pis pick the dashboard up on their next update-burrow.sh): anyone can view the
  wall, bins, charts and live feed; a login only for messages, shows, admin, the signal meter and
  the Bluetooth page. The wrangler.jsonc routing changed too (.html pages go through the Worker).
- [ ] e2e rig (tools/e2e/run.sh): no Bins reach the test Worker ("bins 0"), already broken before
  0a1f923; and cloud/surface test alerts.test.js "a re-sent batch is stored and alerted once"
  fails ([5,3] vs [5,2]) on the old code too. Both need a look.

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
- [x] ~~Reflash the classroom Picos~~: none are in the field (see Next steps 2).
- [x] **mkrlbs.com/whsbt -> whs.makerlabkids.com/bluetooth** works (2026-11-01; case-insensitive,
      HTTP://MKRLBS.COM/WHSBT for a smaller QR). The NOT CONNECTED card said mrklabs.com (a typo,
      fixed in worm-bin main.py; the classroom boards get it with the reflash).
- [x] Surface deployed with the alert re-send fix (f411615) and everything after, 2026-11-01.
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
- [x] Phase 2 live since the 2026-11-01 deploy; proven on the bench board.
- [ ] Try the tutorial with one team, especially the Viper IDE folder/upload steps (written
      from memory of Viper's file panel, not re-checked click by click).

## Bench board (The Wrigglers, now bin 38)

- 2026-11-02 fan bench: fan on GP15 through a 2N2222 works (full on / full off). The first transistor
  was damaged (leaked: the fan twitched all the time), most likely by the diode in backwards; the
  replacement is good, diode goes stripe-to-red. The board still runs 58939f0 (the 509f0e1 OTA was
  rolled back); its main.py got a 5-line patch: fan full on 10 s at power-on (one-shot Timer).
  Backup of the unpatched file: scratchpad only, so re-read from the board before any rewrite.
  Later the same evening: the board was updated over USB to 0a93670 (carry_config kept its settings;
  ota.json current 0a93670; full backup of the old files in ~/bench-backups/, holds wifi.json, not
  in git). Fan ran its 10 s, pushes to burrow0 fine. Its screen (0x3C) is gone from the I2C bus (the
  BME280 0x77 and VL53L0X 0x29 answer): a loose OLED wire, check its VCC/GND/SDA/SCL. This board has
  only the outside BME280, so the humidity fan rule never fires here (it reads the inside one).
  Then (32dfd53, 01c5491): power-on sequence plays during the Wi-Fi join; BME280 driver no longer
  loses humidity on a garbled chip-ID read. Its OLED froze after four quick Pico resets (writes still
  ACKed, no "OLED lost"); a USB power cycle fixed it. If it freezes on its own, add a stuck-screen
  re-init (the screen keeps power through machine.reset()). ota.json: write it with a closed file
  before a reset, or the write is lost.

- [ ] It plays only "hello" then Wormhole (a website playlist from the 2026-11-01 test): "Play
      everything" on its page restores all shows. It runs code 58939f0 over Wi-Fi, MicroPython 1.29.

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
