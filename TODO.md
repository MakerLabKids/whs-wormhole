# To do

Open items, newest first. Tick them off or delete them; the git log is the
record of what got done.

## Deploy (from 2026-10-31; updated 2026-11-01 morning)

Done 2026-11-01: Surface deploy + schema + ENROL_SECRET + TUNNEL_TOKENS; the four ssh-burrowN
hostnames (SSH through Cloudflare works on all four); burrow2 rebuilt from a cloned card and
enrolled; all four Pis on the same build; every Tunnel has WormHole-Core saved (`remember`) and
is on the backhaul; the Portal's backhaul AP watch on burrow0.

- [ ] **Decide: unhide the backhaul?** Back on the table. 2026-11-01 08:01-08:07: Tunnel 2, with
      WormHole-Core SAVED, auto-connect on and its Pi's watchdog paused, did NOT rejoin the
      (freshly restarted, working) backhaul by itself in 6 min; one explicit join from its Pi got
      it in 20 s. Tunnel 3's auto-connect DID fall back to Loki (visible, saved). Not conclusive:
      Tunnel 2 had just failed several joins against the broken AP and GL backs off to 5-min
      retries. Clean retest: Portal 5 GHz off 60 s / on, Tunnel watchdogs paused, watch 15 min.
      Today the Pis' watchdogs do the rejoin, so this only matters for a Tunnel whose Pi is down.
- [ ] **Save the Portal's own upstreams** (it is on Guess with only Guess saved): its Pi's
      watchdog now joins with remember, so this fills in as it switches; or rejoin Loki once.
- [ ] **Teach each Tunnel a fallback at school**: `tools/routers/teach-fallback.py
      192.168.80.2N BYLD` for N = 1..3 (from the Portal's LAN, or on the Pi). At home they know Loki
      (Tunnel 3 saved it 2026-11-01; Tunnels 1 and 2 have only the backhaul saved).
- [ ] **New golden image** from burrow3 (room 3: its tunnel.json has the backhaul entry; all clone
      fixes): /workspace/burrow-golden.img.gz. A clone from burrow0's card lacks the backhaul upstream.
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
- [ ] **Make mrklabs.com/whsbt redirect to whs.makerlabkids.com/bluetooth** (on the NOT CONNECTED card).
- [ ] **`ALERT_URL`** for the Surface (carried over).
- [ ] **Physical fault tests** (an evening, with the clock): pull a Pi; pull a Tunnel; pull the
      provider; pull the internet; power everything off and on in random order; swap an Opal;
      swap a Pi (cloned card); two rollouts in a row. Pass times in the plan of 2026-10-31.

## Bench board (The Wrigglers, now bin 38)

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
- [ ] Surface alert when a Bin reports a large `buffered` count (it means every
      Burrow it can see has been dark for that many minutes).
- [ ] A battery RTC module on the Pico would turn "estimated" backfill timestamps
      (rows from a boot that never reached a Burrow) into exact ones. Only matters
      if a bin loses power *and* network for the same stretch.
- [ ] `projects/distance-station` demo: its README still describes the single-shot
      driver; the new driver's continuous mode and `status` are worth a paragraph.
