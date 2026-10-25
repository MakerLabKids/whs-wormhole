# Burrow: the classroom edge (Raspberry Pi 5)

The Pi 5 in each classroom. It ingests the room's worm-bin Picos ("Bins"),
keeps every reading on the microSD as immutable 15-minute **castings**,
mirrors castings with the other two Burrows, uploads to the **Surface**
(Cloudflare) whenever any internet exists, and serves the local dashboards.
Standard library only; nothing to pip install.

Design: https://makerlabkids.github.io/whs-wormhole/design/ · Build guide:
https://makerlabkids.github.io/whs-wormhole/design/burrow.html · Wire protocol:
[PROTOCOL.md](PROTOCOL.md)

```
burrow/           the service (python3 -m burrow)
  service.py      wiring + background loops (fsync, seal, peers, cloud, sweep, reclaim)
  store.py        open log -> castings (gz + sidecar meta), mirrors, retention
  rollups.py      5-minute / hourly aggregates in SQLite (derived, rebuildable)
  server.py       HTTP on :8080 (ingest, dashboards, API, SSE, peer endpoints)
  peers.py        pull replication from the other Burrows
  cloud.py        snapshot / casting / rollup upload, verify read-back, clock fix
  sweep.py        pull fallback: poll /data on quiet Bins
  state.py        the 'now' table and the SSE broadcaster
  clock.py        clock quality from chrony (ntp | peer | free)
setup-pi.sh       one-time OS preparation on a fresh Pi OS Lite (partition, chrony, static IP...)
install.sh        (re)deploy the code into /opt/burrow, systemd unit
burrow-lock.sh    make root read-only (overlay) / burrow-unlock.sh to maintain
install-cloudflared.sh <token>   the outbound-only live link
tools/simbins.py  pretend to be N Bins (no hardware needed)
tests/            unittest suite incl. a fake Surface (tests/fake_surface.py)
```

## Run it on a laptop

```
cd edge/burrow
python3 -m unittest discover -s tests -t .          # 18 tests
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
