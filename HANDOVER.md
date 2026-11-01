# Handover: the night of 2026-10-31 (written for the next session)

Read this first, then TODO.md, then the memory directory
(`~/.claude/projects/-workspace/memory/MEMORY.md`). Everything below is as of
commit 908d1ed, about midnight 2026-10-31 (America/New_York).

## Who, what, where

- Repo: MakerLabKids/whs-wormhole (public), checked out at /workspace in the
  "wormhole" container. The human is the project owner, pushes from their laptop
  too. Commit messages: factual, no trailers.
- The system: Picos ("Bins") in worm bins push readings to a Raspberry Pi
  ("Burrow", one per room) over an Opal router ("Tunnel"; one Opal, the
  "Portal", carried the internet for the others). Burrows upload to a Cloudflare
  Worker ("Surface", whs.makerlabkids.com). Code map: lib/picolab.py (Pico
  framework), projects/worm-bin (the bin program), edge/burrow (the Pi),
  cloud/surface (the Worker), web/dash (the dashboard served by both).
- Tonight's bench: all four Opal+Pi pairs on the human's desk at home. The
  laptop (the container's host) is cabled into the Portal's LAN port with
  `nmcli ... ipv4.never-default yes` so its Wi-Fi keeps the internet. From that
  cable this container reaches: the Portal admin (192.168.80.1), burrow0 (ssh
  worm@192.168.80.10), each joined Tunnel's admin at 192.168.80.2N, and the Pi
  behind it at ssh worm@192.168.80.2N (the watchdog forwards 22 and 8080).
  Key: ~/.ssh/id_ed25519, passwordless sudo as worm. The Pis have NO git:
  ~/wormhole on a Pi is a plain copy of edge/ tools/ web/; deploy =
  `edge/burrow/tools/update-burrow.sh N` (tar over ssh + sudo install.sh), or by
  hand as in the commits tonight.
- burrow2's Pi is dead or unpowered (offline on Opal 2's cable port all night).
  The human will make it a cloned card tomorrow (see Cattle below).

## The mission the human gave, in their words

"One component failure can't affect anything else. It all has to keep working."
A dead Pi: too bad, everything else continues. A dead Opal: its Pi turns on its
own Wi-Fi, talks to another Opal, reaches the internet, gets updates. SSH into
every Pi from outside the school. No fixed Portal: any Opal can carry the
internet; the best one is elected and verified by the others; a flaky one must
not keep getting elected. Burrows are cattle: drop a new Pi in and it goes.
Updates: the human sets a version and clicks Update on one Pi at a time. NEVER
delete buffered readings, even undated ones. Stagger Picos joining after a
power cut. Say something at once when they send a message; announce anything
over 30 s with its timeout; update every 2 min on long work (this is in
~/.claude/CLAUDE.md and memory `no-silence-announce-long-work`; they had to
ask several times).

## What was built tonight (all pushed, all tests green)

Each item: where, how verified, deployed or not.

1. **Undated readings kept** (edge/burrow service.ingest_batch): rows a Burrow
   cannot date are stored under their arrival time with clk "bin-undated",
   boot number and seconds since boot, deduplicated, kept off the rollups,
   served in buffer order by `GET /api/undated?uid=` (JSON or `&csv=1`). Only
   non-rows are dropped. Tests in tests/test_backfill.py. Deployed to
   burrow0/1/3.
2. **Build stamp**: edge/burrow/BUILD (gitignored, written by the deploy tools)
   -> `build` in /api/status and on the admin page cards.
3. **Pico leaves a dead network** (lib/picolab.py `_net_dead`, `_pick_ap`,
   DEAD_NET_S=300, BAD_AP_S=1800) and **staggers its first join** 0-10 s.
   burrow0 at 192.168.80.10 is in every bin's fallback list (`_edge_candidates`).
   Verified by the board harness (tools/picotest/run.sh, 35 checks). The bench
   board (The Wrigglers, bin 38, USB /dev/host/ttyACM0) was flashed with this
   picolab; its boot after the flash was not re-read (the capture file went
   missing), worth a 60 s look: `~/venv-tools/bin/python <scratch>/cap.py
   /dev/host/ttyACM0 60 out.log` (cap.py is a 10-line pyserial reader; recreate
   it if the scratchpad is gone).
4. **Pi Wi-Fi fallback walks the full ladder** (edge/burrow/tunnel-watchdog.py
   WifiFallback: another WormHole AP first, then the Opal's upstreams by name,
   open or PSK). Armed on burrow0 (config wifi_fallback present, radio off
   until the cable path has been dead 5 min). Unit-tested; NOT yet proven on a
   real Pi with its Opal unplugged.
5. **Opals rejoin by themselves**: the root cause of the evening was the
   Tunnels' repeater config `auto: false`. Set on all four Opals by hand; the
   watchdog's `ensure_auto_connect` keeps it on. `tools/routers/join-backhaul.py
   N` joins a Tunnel to the hidden backhaul and sets auto, from any laptop on it.
6. **Election, decentralised** (`backhaul_election` in the watchdog): offer
   the backhaul (`wifi set_config {"ifaces":[{"name":"default_radio1",
   "enabled":bool}]}`) after PROBATION_S=600 of clean internet on a real
   upstream; withdraw after DROP_AFTER_S=120 without; BAR_S=1800. Followers
   report `provider_bssid`; the watchdog reports `own_mac`; the Surface
   (alerts.js `sameOpal`, watchEdges) alerts when followers see no internet
   through a provider that claims clean. Unit-tested with a fake router.
   **The real `wifi set_config` call shape is a guess from `get_config`'s
   shape and has NOT been exercised on a real Opal.** The watchdog logs
   "backhaul toggle failed" if it errors. Verify on the Portal once it has had
   10 min clean (it will try to "enable" what is already enabled: no-op).
   Deployed to burrow0/1/3.
7. **Rollouts, one at a time** (cloud/surface admin.js, edge.js; web/dash
   app.js admin Devices tab; edge/burrow cloud.py `_request_update`,
   self-update.sh, systemd/burrow-update.path/.service): admin pastes a
   commit, clicks Update on one Burrow; the Worker fetches the GitHub tarball
   once, stores it in the R2 bucket (`rollouts/<build>.tgz`), hands
   `update_to {build, sha256, url}` to that Burrow in its snapshot reply; the
   service writes /data/burrow/update-request.json; the root path unit runs
   self-update.sh (download from the Surface with the Burrow's token, verify
   sha256 or refuse, unpack over ~/wormhole, install.sh, restart); closes when
   the Burrow reports the build; 30 min timeout; cancel. Surface tests in
   test/rollout.test.js (GitHub stubbed). The Pi side was exercised once
   against GitHub directly: codeload stalled the 24 MB tarball for 5 minutes
   (hence the bucket). **End-to-end through the Surface not yet run**: needs
   the human's `wrangler deploy` + schema, then click Update on burrow0.
8. **Cattle**: edge/burrow/tools/clone-card.sh (image a good card over ssh;
   write a new one with burrow-identity.json on the boot partition) and
   edge/burrow/first-boot-identity.sh + systemd/burrow-identity.service (a
   oneshot before the service: name, room, peers, cable address, hostname,
   tokens if given, wipe cloned data, reboot). Written, syntax-checked,
   installed by install.sh; NOT yet run on a real card. Enrolment via the
   Surface (identity without a file) is NOT built.
9. **Alerts**: "on its own Wi-Fi" and the election disagreement (alerts.js).
10. **Remote SSH**: documented (edge/burrow/README) + tools/ssh-burrow.sh; the
    human must add `ssh-burrowN.whs.makerlabkids.com -> ssh://localhost:22`
    on each tunnel in Cloudflare Zero Trust. Nothing on the Pi.
11. Earlier the same day (already in place): messages on the screen over
    Wi-Fi, website and Bluetooth with names and a change log; the board is
    the truth for its slots with per-slot conflict checks; the boot sequence
    with logos; the link icon and NOT CONNECTED cards (two cards, 10 s each);
    the PIN; fixed addresses; the flash buffer with backfill.

## What is deployed where

| box | code | notes |
|---|---|---|
| burrow0 | 908d1ed (verified) | Portal's Pi; on Loki tonight |
| burrow1 | 908d1ed (verified) | behind Tunnel 1: 192.168.80.21 |
| burrow3 | 908d1ed (verified) | behind Tunnel 3: 192.168.80.23 |
| burrow2 | OLD (pre-messages) | Pi dead; clone a card |
| Surface | the deploy from ~19:00 (messages + bin_messages) | **NOT** the per-slot conflict fix, rollouts, R2 tarballs, alerts, admin panel: `cd cloud/surface && npx wrangler deploy && npx wrangler d1 execute wormhole --remote --file schema.sql` |
| bench Pico | picolab with dead-network rejoin | main.py on the board is a hand-tuned copy: patch forward with `git diff <base> -- projects/worm-bin/main.py \| patch -p3` on the scratchpad copy; never overwrite (memory `wormhole-distance-cal-2026-10-31`) |
| classroom Picos (49) | ancient | fleet reflash owed (tools/fleet/flash.py), relabel lids 30-79, recalibrate |

## What is left, in order

1. Human: Surface deploy + schema; the four SSH hostnames; then the first real
   rollout from the admin page (burrow0), and verify `build` moves.
2. Verify on real hardware: the Wi-Fi fallback (unplug a Tunnel's cable from
   its Pi for 6 min, watch /api/status `tunnel.wifi_fallback` and the Surface
   alert); the election toggle (watch the watchdog's events for "backhaul
   offered"/"toggle failed"); the clone-card path for burrow2.
3. Enrolment: a fresh Pi registers with the Surface using a fleet enrolment
   secret and receives name/room/tokens (replaces burrow-identity.json).
   Design in the human's words: Opals and Pis identical; room is where it
   stands; the Surface or the other Pis tell a new box who it is.
4. Opal nursing beyond auto-connect: the watchdog already reboots a dead-but-
   reachable Opal over RPC after 15 min; nothing can revive one with no power.
5. The physical fault-test evening (TODO.md lists the eight pulls with pass
   times from the plan given to the human on 2026-10-31: 5 min for a Pi or a
   Tunnel, 10 min for a full power cycle).
6. Picos: the fleet reflash at school; the Surface-side view of undated rows
   (today only the Burrow's /api/undated and CSV).

## Progress after the handover (2026-11-01, 00:00-, Opus 5.5 session)

- **Election toggle proven** (b130c3c, 354b8b3): `wifi set_config {"iface_name", "enabled"}`; the
  nested form 500s. Tunnel 1 switched its own backhaul off as a follower while staying on the
  Portal's. The call takes >8 s: 60 s limit plus read-back.
- **Pi Wi-Fi was disabled in firmware on burrow1 and burrow3** (`dtoverlay=disable-wifi`, no wlan0
  at all). Removed and rebooted both; install.sh now removes it on every deploy and the watchdog
  raises an event when wlan0 is missing. The fallback scan now waits for the radio, and skips the
  Pi's own Opal by station MAC (`same_opal`), since `own_bssids` held random addresses.
- **Live fault test, burrow3, started 00:12:20**: `nmcli device disconnect eth0` with a timer
  (`faulttest-undo2`, +14 min) that reconnects it. Result: see the line below once known.
- **Undated readings on the website**: `/api/edge/<room>/undated?uid=&csv=1` pass-through and a
  button on the bin page (3e63cf6).
- **Enrolment** (36aa6e3): `POST /v1/edge/enrol` on the Surface (ENROL_SECRET, TUNNEL_TOKENS,
  table `enrolled`); Pi side in first-boot-identity.sh for cards marked `needs-identity`;
  clone-card.sh strips donor secrets. The fleet secret is `enrol_secret` in /workspace/.env and at
  /etc/burrow/enrol.secret on burrow0 and burrow1. Unverified on a real fresh card.
- The bench Pico is unpowered (USB gone, not heard for 95 min at 00:13).
- Human now also owes: `wrangler secret put ENROL_SECRET` (value from .env) and
  `wrangler secret put TUNNEL_TOKENS` (JSON of the four cloudflared tokens).

## How to work here (hard-won)

- Never `pkill -f <pattern>` where the pattern matches your own shell (it kills
  the tool call: exit 144). Kill by pid, excluding `$$` and `$PPID`.
- The serial port: only one reader. Kill the capture (by pid) before mpremote.
- `edge/burrow/BUILD` must be regenerated (`git log -1 --format='%h %cI'`)
  before each manual tar deploy or the Pi reports a stale build.
- Opal API facts (tools/routers/glinet.py, password from /workspace/.env
  router_admin): `repeater get_config` has `auto`; `wifi get_config` has
  ifaces by name (`default_radio1` = WormHole-Core, hidden, sae) but NO
  BSSIDs; `system get_status` dumps Wi-Fi passwords, do not print it; the
  backhaul is hidden so scans never show it, join by BSSID
  94:83:c4:84:d2:0c with the key from .env backhaul_key.
- The laptop loses this session if its wired connection takes the default
  route; the never-default setting is on the human's laptop now.
- Tests: `micropython tools/picotest/test_*.py`; `tools/picotest/run.sh`
  (kill stale `python3 -m burrow` by pid first; ~3 min; 35 checks);
  `cd edge/burrow && python3 -m unittest discover -s tests -t .` (104);
  `cd cloud/surface && npx vitest run` (47). All green at 908d1ed.
- The human reads only the final message of a turn: first line = what you
  understood and are doing; long steps announced with their timeout.

## Things I am not sure about

- `wifi set_config`: RESOLVED 2026-11-01, `{"iface_name": "default_radio1", "enabled": bool}`; the nested form 500s. Proven on Tunnel 1 (guest5g on/off, repeater stayed up).
- `sameOpal` MAC heuristic: verified on the Portal only (92:83:c4:84:d2:0b ->
  94:83:c4:84:d2:0b/0c).
- first-boot-identity.sh assumes the Pi's wired connection name is on eth0 and
  that /boot/firmware is the boot partition (Pi OS Bookworm); untested.
- The Pi updater's download through the Surface's bucket: the route and token
  check are tested in vitest; a real Pi has not pulled from it yet.
