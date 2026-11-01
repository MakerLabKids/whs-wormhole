# Burrow: the classroom edge (Raspberry Pi 5)

The Pi 5 in each classroom. It ingests the room's worm-bin Picos ("Bins"),
keeps every reading on the microSD as immutable 15-minute **castings**,
mirrors castings with the other two Burrows, uploads to the **Surface**
(Cloudflare) whenever any internet exists, and serves the local dashboards.
Standard library only; nothing to pip install.

If every Burrow is dark (a Pi down, a router out, spring break with
nobody to fix it) the Bins do not lose anything: each keeps its rows
on its own flash (months' worth at one a minute) and hands them over
in batches, oldest first, to the first Burrow that answers again
(`POST /ingest/batch`, see PROTOCOL.md). Backfilled rows keep their
own timestamps and seal into the castings of their own windows.

Design: https://makerlabkids.github.io/whs-wormhole/design/ · Build guide:
https://makerlabkids.github.io/whs-wormhole/design/burrow.html · Wire protocol:
[PROTOCOL.md](PROTOCOL.md)

```
burrow/           the service (python3 -m burrow)
  service.py      wiring + background loops (fsync, seal, peers, cloud, sweep, reclaim)
  store.py        open log -> castings (gz + sidecar meta), mirrors, retention
  rollups.py      5-minute / hourly aggregates in SQLite (derived, rebuildable)
  server.py       HTTP on :8080 (ingest + backfill, dashboards, API, SSE, peer endpoints)
  peers.py        pull replication from the other Burrows
  cloud.py        snapshot / casting / rollup upload, verify read-back, clock fix
  sweep.py        pull fallback: poll /data on quiet Bins
  state.py        the 'now' table and the SSE broadcaster
  netstat.py      measured throughput to the other Burrows: iperf3 3 s up + 3 s down against
                  burrow0 (192.168.80.10) and the other Tunnels' WAN (192.168.80.2N, where each
                  Tunnel forwards 5201 to its Pi) every 15 min, staggered by room. Latest
                  numbers in the status brief -> cloud snapshot -> admin Devices page. The same
                  run times an 8 MB download / 2 MB upload + latency to speed.cloudflare.com
                  ("internet" row; net.internet_bytes_* = 0 turns it off)
  watch.py        the 1 Hz live view: while a viewer's stream carries ?watch=<uid> the Burrow
                  polls that Bin's /data every second and fans it out as `event: live`
                  (not stored: the archive stays at the Bins' 60 s push). One poller per
                  Bin, stops with the last viewer. Button on the bin page; /api/status "watch"
  clock.py        clock quality from chrony (ntp | peer | free)
setup-pi.sh       one-time OS preparation on a fresh Pi OS Lite (partition, chrony, static IP...)
install.sh        (re)deploy the code into /opt/burrow, systemd unit
tools/update-burrow.sh N  from a machine on the LAN: copy edge/ tools/ web/ into ~/wormhole on
                  the Pi (no git there), install.sh, unlocking/locking around it if the root
                  was read-only; `update-burrow.sh 0 1` does two
iperf3              server always on (port 5201, ~4 MB idle). Real throughput from any Pi,
                  laptop or Bin on the LAN: `iperf3 -c 192.168.8N.10 -t 5` (Portal's Pi: .80.10).
                  2026-10-28: laptop cable -> Portal -> burrow0 710 Mbit/s; burrow1 -> Tunnel 1 ->
                  5 GHz WPA3 backhaul -> Portal -> burrow0 195 Mbit/s.
tunnel-watchdog.py  every 2 min: keep this room's Opal on its best upstream (and keep the
                  Opal's own "auto-connect to saved networks" on, so it rejoins by itself
                  after a power cycle; tools/routers/join-backhaul.py N does both by hand) (the Portal's
                  backhaul while it carries internet, else the shared failover list: phone
                  hotspot, school net, home nets), reboot it over RPC after 15 min down
                  (then hourly x3, then daily, forever), raise the Pi's own Wi-Fi to another
                  Opal meanwhile, and report it all under "tunnel" in /api/status and the
                  cloud snapshot. Config: etc/tunnel.json.example -> /etc/burrow/tunnel.json
burrow-lock.sh    make root read-only (overlay) / burrow-unlock.sh to maintain
install-cloudflared.sh <token>   the outbound-only live link
tools/simbins.py  pretend to be N Bins (no hardware needed)
tests/            unittest suite incl. a fake Surface (tests/fake_surface.py)
```

## Run it on a laptop

```
cd edge/burrow
python3 -m unittest discover -s tests -t .          # 54 tests
mkdir -p /tmp/b1/www && cp -r ../../web/dash/* /tmp/b1/www/ 2>/dev/null || echo '<h1>dash</h1>' > /tmp/b1/www/index.html
cat > /tmp/b1/burrow.json <<'J'
{"edge":"burrow1","room":1,"port":8080,"data_dir":"/tmp/b1/data","www_dir":"/tmp/b1/www",
 "peers":{},"cloud":{"url":"http://127.0.0.1:8787","token_file":"/tmp/b1/token"},"sweep":{"enabled":false}}
J
echo test-token > /tmp/b1/token
python3 tests/fake_surface.py 8787 &                  # a stand-in cloud
BURROW_CONFIG=/tmp/b1/burrow.json python3 -m burrow & # the Burrow
python3 tools/simbins.py --n 17 --every 10            # 17 fake Bins
```

Then open http://127.0.0.1:8080/ and http://127.0.0.1:8080/api/status.
Castings seal on the next quarter hour; `/tmp/b1/data/castings/` fills up,
and the fake Surface "verifies" them.

## Data on disk

```
/data/burrow/open/r1.jsonl                       the current 15-minute window (fsync every 30 s)
/data/burrow/castings/r1/2026-10-16/r1-20261016T1415.jsonl.gz   immutable
/data/burrow/castings/r1/2026-10-16/r1-20261016T1415.meta.json  hash, rows, replicas, cloud state
/data/burrow/castings/r2/...                      mirrors of the other rooms
/data/burrow/rollups.sqlite                       derived; `python3 -m burrow --rebuild-rollups`
/data/burrow/reclaimed.log                        what was deleted, when, and the verified hash
```

A casting is deleted only when it is at least `retain_days` (7) old **and**
the cloud has confirmed it by hashing the stored object. Nothing else deletes.

## Reaching a Pi from anywhere: SSH through its Cloudflare tunnel

Each Burrow's cloudflared tunnel is outbound-only and dashboard-managed, so SSH
goes over it with no port opened on the Pi and no change on the Pi at all:

1. In Cloudflare Zero Trust: Networks -> Tunnels -> the tunnel named for burrowN -> Edit (or
   Configure) -> Public Hostname -> Add a public hostname. The same place the existing
   `burrowN.whs.makerlabkids.com` entry lives; add a second one next to it:

   | field     | value                                   |
   |-----------|-----------------------------------------|
   | Subdomain | `ssh-burrowN.whs` (e.g. `ssh-burrow0.whs`) |
   | Domain    | `makerlabkids.com`                      |
   | Path      | empty                                   |
   | Type      | `SSH`                                   |
   | URL       | `localhost:22`                          |

   Do it on all four tunnels (burrow0..3); burrow2's works once its Pi is back. Cloudflare makes
   the DNS record itself. Check: `getent hosts ssh-burrow0.whs.makerlabkids.com` answers.
   Strongly suggested: a login wall, so the Pi's sshd is not open to the whole internet. Zero
   Trust -> Access -> Applications -> Add -> Self-hosted, application domain
   `ssh-burrow*.whs.makerlabkids.com` (or the four names), policy Allow, include your email. Then
   the first `cloudflared access ssh` opens a browser to log in once.
2. On the laptop, install `cloudflared` once, then
   `tools/ssh-burrow.sh N` (or by hand:
   `ssh -o ProxyCommand="cloudflared access ssh --hostname %h" worm@ssh-burrowN.whs.makerlabkids.com`).

It works through whatever path the Pi has at that moment: its Opal, its own
Wi-Fi, a phone hotspot. From the Pi you have its Opal too (the admin API on the
cable), so a Tunnel can be joined, rebooted or reconfigured without a cable from
anywhere with internet. `update-burrow.sh` takes `BURROW_SSH="ssh -o ProxyCommand=..."`
to deploy the same way.

## Every box stands alone (2026-10-31)

The rule: one failure never takes anything else down, and every box has two
ways out.

**A Pi dies.** Its Picos notice within five minutes (no accepted push), leave
that WormHole, avoid that access point for half an hour, and join another.
The other Pis, the Opals and the Surface are untouched. The Surface alerts.

**A Tunnel Opal dies.** Its Pi brings up its own Wi-Fi two to four minutes
after the cable path dies: another WormHole access point first, else the same
ladder the Opal uses (phone hotspot, school net, home nets), keeps
uploading, stays reachable by SSH through its tunnel, and the Surface alerts
"on its own Wi-Fi". It also nurses the Opal: reboots it over the admin API,
keeps its auto-connect on. The Picos on that Tunnel rejoin elsewhere.

**The provider dies.** Today each Tunnel falls back to its own ladder (a
VISIBLE saved network: Loki at home, BYLD at school) and carries on with its
own internet; the Pis follow their Opal. The election
(`backhaul_election`) runs but only REPORTS who would qualify
(`backhaul_candidate`): switching a follower's backhaul AP off left Tunnel 1
unable to rejoin WormHole-Core after its next drop (2026-11-01), and the
Tunnels are pinned to the Portal's BSSID, so a new provider could not be
followed anyway. It switches a disabled backhaul AP back on. A real handover
needs followers that join WormHole-Core by name (not BSSID) and a test that
a provider can drop its AP safely; `ELECTION_ACTS` turns the acting path on.

**Power cycles.** An Opal's own auto-connect only walks its SAVED list, and
GL.iNet saves a network only when the join says `remember: true`; until
2026-11-01 none of ours did, so every saved list was empty. Every join now
remembers, and the watchdog reports `saved_networks`. Proven 2026-11-01: with the
Portal's 5 GHz off for 60 s and every Tunnel Pi's watchdog paused, all three Tunnels
were back on the (hidden) WormHole-Core 35 s after it returned, by their own
auto-connect. After repeated failed joins GL.iNet backs off to 5-min retries.
`tools/routers/teach-fallback.py HOST SSID [key_env]` saves a second network
(Loki at home, BYLD at school) for when the Portal itself is gone.

**One failed check no longer moves a Tunnel; a Tunnel on a fallback comes home.**
2026-11-01 10:00: one failed 8 s cloud check on burrow1 (rooms 2 and 3 were fine)
made its watchdog move Tunnel 1 from a healthy backhaul to Loki, and nothing ever
moved it back while Loki worked. Now "connected but no cloud" first holds (the
outage clock starts) and switches only if the next run, at least 100 s later, still
fails. And rooms 1-3 that have spent 15 min on a fallback with good internet rejoin
WormHole-Core, at most every 30 min, then 1 h, 2 h, 4 h (reset once home). The
Opal's scan leaves hidden networks out, so the watchdog checks for the Portal by
its BSSID prefix (its visible 2.4 GHz WormHole) before trying. Proven on burrow1
2026-11-01: Tunnel 1 left on Loki at 10:29, back on WormHole-Core at 10:45. A failed
try falls back by the usual path (the hidden-miss rule moves on to Loki next run).

**The Portal's backhaul AP stops taking new Tunnels.** 2026-11-01: after burrow0
moved the Portal's upstream (Loki -> Guess), WormHole-Core kept the Tunnel already
on it but refused every new association for an hour (Tunnels 1 and 3 fell back
to Loki; a rebooted Tunnel 2 stayed dark). Restarting that AP fixed it at once.
burrow0's watchdog now does that by itself: no Tunnel's Pi reachable over the
Portal LAN for 10 min -> backhaul AP off and on, at most hourly.

**A Tunnel's 2.4 GHz WormHole can wedge too.** Tunnel 2's refused every client
(right key, WPA2, enabled) until the Opal was rebooted. Not yet detected
automatically; a Pi can probe it with its own Wi-Fi.

**Cloning (proven 2026-11-01 on burrow2, with fixes).** Image a room 1-3 Pi
(`clone-card.sh image 3 ...`; burrow0's tunnel.json has no backhaul entry), write
with `clone-card.sh write IMG /dev/sdX` (boot + root only, about 4 min), boot it
on the room's Opal: it takes DHCP, reads its room from 192.168.8N.x, enrols with
the Surface (name, upload token, tunnel token), reboots as burrowN on .10. Its
watchdog stays idle until then (the donor's settings point at the donor's Opal).

**Proven live (2026-11-01).** Cutting a Pi's cable (`tools/fault-test.sh`):
its own Wi-Fi took over and its uploads continued (burrow3, through Tunnel 2,
for over an hour); a WormHole whose Opal has no internet is now rejected and
the next one tried; the watchdog drops the Wi-Fi when the cable is healthy;
the cable path is judged through eth0 only.

**Updates, one at a time.** `/opt/burrow/BUILD` says which commit runs
(`build` in /api/status, on the admin page). The admin pastes a commit and
clicks Update on one Burrow: the Surface fetches that commit's tarball from
GitHub once, keeps it in its bucket, and hands the Burrow `{build, sha256,
url}` in its next snapshot reply; the service writes
`/data/burrow/update-request.json`; `burrow-update.path` (root) runs
`self-update.sh`: download from the Surface with the Burrow's token, verify
the sha256 or refuse, unpack over `~/wormhole`, `install.sh`, restart, report
the build. The other buttons stay off until it reports or 30 minutes pass.

**Cattle, not pets.** A card written by `clone-card.sh write golden.img.gz /dev/sdX` (no number)
carries no donor secrets and is marked `/etc/burrow/needs-identity`: on first boot the Pi takes a
DHCP address from whatever Opal it is cabled to, reads its room from the subnet, enrols with the
Surface (`/etc/burrow/enrol.secret`, the fleet secret), and becomes burrow<room> with its own
tokens. `clone-card.sh image 0 golden.img.gz` reads a
good card over ssh; `clone-card.sh write golden.img.gz /dev/sdX 2` writes a
card for burrow2 with one JSON line on its boot partition
(`burrow-identity.json`); `first-boot-identity.sh` (a oneshot before the
service) becomes that Burrow: name, room, peers, cable address, hostname,
tokens if given, wipes the cloned data, reboots. No flasher, no setup script.

**Readings are never thrown away.** See `/api/undated` above: rows the Burrow
cannot date are stored in buffer order, not dropped.
