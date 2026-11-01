# To do

Open items, newest first. Tick them off or delete them; the git log is the
record of what got done.

## Deploy (from 2026-10-31)

- [ ] **burrow3: reboot it** (power cycle, or `sudo reboot` once SSH through its tunnel works).
      Since a fault test at 00:12 on 2026-11-01 its Ethernet is "disconnected by user" in
      NetworkManager; it has been running on its own Wi-Fi through Tunnel 2 since, uploading
      fine, on code 354b8b3. After the reboot: `edge/burrow/tools/update-burrow.sh 3`.
- [ ] **Teach each Tunnel a visible fallback at school**: `tools/routers/teach-fallback.py
      192.168.80.2N BYLD` for N = 1..3 (from the Portal's LAN). At home they know Loki.
- [ ] **Decide: unhide the backhaul?** A visible WormHole-Core (still WPA3) would let every
      Opal rejoin it by itself after any power cut, with no Pi involved. The cost is the SSID
      showing in phone Wi-Fi lists. Changing it restarts the Portal's 5 GHz radio once.
- [ ] **Secrets for the Surface**: `npx wrangler secret put ENROL_SECRET` (value: enrol_secret in
      /workspace/.env) and `npx wrangler secret put TUNNEL_TOKENS` ({"burrow0": "...", ...}).

- [ ] **Surface `wrangler deploy` + schema** (the night of 2026-10-31): rollouts, R2-backed
      tarballs, the undated/board-state tables, the Wi-Fi and election alerts, the admin
      Update panel. `npx wrangler deploy && npx wrangler d1 execute wormhole --remote --file schema.sql`.
- [ ] **Cloudflare: SSH hostnames** `ssh-burrowN.whs.makerlabkids.com -> ssh://localhost:22` on each
      tunnel (N = 0..3); then `tools/ssh-burrow.sh N` from anywhere.
- [ ] **First real rollout**: after the Surface deploy, admin page -> Devices -> paste a commit,
      Update burrow0, watch it report the build; then the others one by one. (The Pi side was
      exercised tonight against GitHub directly: codeload stalled a 24 MB download, hence the
      bucket.)
- [ ] **burrow2**: `clone-card.sh image 0 golden.img.gz`, `clone-card.sh write ... /dev/sdX 2`, boot
      it on Opal 2. Then Tunnel 2 is nursed by it.
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
