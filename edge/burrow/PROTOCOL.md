# Wormhole telemetry: the wire protocol

One page that every piece agrees on: Bins (Pico 2 W), Burrows (Pi 5), Surface
(Cloudflare Worker). If you change a field here, change it in all three.

## Bin -> Burrow: `POST /ingest`  (port 8080, every 60 s)

Body: the same JSON the Bin serves at `/data`, which already carries its
identity (`id` = 16-hex flash serial, `name`, `ip`, `ssid`, `mode`, `net`),
plus three things the push loop adds:

| field  | type   | meaning |
| ------ | ------ | ------- |
| `bin`  | object | `{"team": "Dirt Vader", "period": 3, "bin": 7, "room": 1}` from `bin.json` (absent if the file is missing) |
| `up`   | int    | seconds since boot (dedup + "did it reboot?") |
| `rssi` | int    | station RSSI in dBm when joined |

Reply: `{"ok": true, "ts": 1760600000, "edge": "burrow1", "room": 1}`.
`ts` is the Burrow's unix time; the Bin keeps it to label its own graph.

Any Burrow accepts any Bin. The Bin tries, in order: `<own subnet>.10`,
then `192.168.80.21`, `.22`, `.23` (the Tunnels' WAN addresses, which
forward 8080 to their Burrow). Overridable with `"edges": [...]` in `bin.json`.

## Burrow -> Bin: `GET /data` (pull sweep, every 5 min, only for quiet Bins)

Same dict as above minus `bin`/`up`/`rssi` (older firmware). Rows ingested
this way carry `src: "pull"`.

## Row format (what goes into a casting)

One JSON object per line, UTF-8, newline terminated:

```json
{"ts": 1760600000, "clk": "ntp", "uid": "e66118604b7c2b2a", "name": "Dirt Vader",
 "room": 1, "edge": "burrow1", "src": "push", "d": { ...the Bin's dict... }}
```

`clk` is the Burrow's clock quality at stamping time: `ntp` (internet or a
peer that has internet), `peer` (agreed with another Burrow, no upstream),
`free` (nobody to agree with; could be off by the length of a power cut).

## Castings (immutable blocks)

Window: 15 minutes, UTC-aligned. Id: `r<room>-<YYYYMMDD>T<HHMM>` of the
window start, e.g. `r1-20261016T1415`. File: `<id>.jsonl.gz` (gzip of the
rows, sorted by ts). Sidecar: `<id>.meta.json`:

```json
{"id": "r1-20261016T1415", "room": 1, "edge": "burrow1", "t0": 1760624100,
 "t1": 1760624999, "rows": 743, "sha256": "...", "size": 19877,
 "created": 1760625020, "replicas": {"burrow2": 1760625140},
 "cloud": {"uploaded_at": null, "rollups_at": null, "verified_at": null, "by": null}}
```

The `.jsonl.gz` is never modified. The sidecar is rewritten atomically.
Reclaim (delete both files) only when `now - t1 >= 7 days` AND
`cloud.verified_at` is set.

## Burrow <-> Burrow (port 8080 via the Tunnel WAN forward)

| call | reply |
| ---- | ----- |
| `GET /castings?since=<unix>` | `{"edge": "burrow2", "castings": [meta, ...]}` for castings with `created >= since` (all, if omitted) |
| `GET /castings/<id>` | the `.jsonl.gz` bytes, `Content-Type: application/gzip`, `X-Casting-Sha256` header |
| `GET /castings/<id>/meta` | the sidecar |
| `GET /health` | `{"ok": true, "edge": "burrow2", "room": 2, "ts": ..., "clk": "peer"}` |

Pull only; a Burrow never pushes to a peer. Downloaded files are hashed
before they are stored.

## Burrow -> Surface (HTTPS, `Authorization: Bearer <per-burrow token>`)

| call | body | reply |
| ---- | ---- | ----- |
| `GET  /v1/edge/ping` | | `{"ok": true, "ts": <unix>}` (also used to set a free-running clock) |
| `POST /v1/edge/snapshot` | `{"edge","room","ts","bins":{uid: entry},"status":{...},"roster":[...]?}`; `status.tunnel` is the Opal brief `{state, checked, down_since, upstream, signal, cloud_ok, clients, reboots, wifi_fallback, last_event, last_event_at}` or null | `{"ok": true}` |
| `PUT  /v1/edge/castings/<id>` | the gz bytes; header `X-Casting-Meta: <meta json>` | `{"ok": true, "sha256": "..."}` (Worker hashes what it received) |
| `POST /v1/edge/rollups` | `{"casting": "<id>", "rows": [{"uid","step","ts","data"}]}` | `{"ok": true, "n": 150}` |
| `POST /v1/edge/verify` | `{"ids": ["r1-...", ...]}` (<= 40: the Worker reads each from R2, and free Workers get 50 subrequests) | `{"verified": [...], "rollups": [...], "missing": [...]}` |

Verification is a read-back: the Worker fetches the object from R2, hashes
it, compares with the stored sha256, and only then stamps `verified_at`.
`missing` ids get re-uploaded by whoever asked.

A snapshot `bins` entry is the latest row for that uid as `{"ts","clk","src","d"}`
plus `"team","period","bin","room"` lifted out of `d.bin` for convenience.

## Viewer API (same on a Burrow and on the Surface; Surface requires the cookie)

| call | meaning |
| ---- | ------- |
| `GET /api/now` | `{"ts", "edges": {edge: status}, "bins": {uid: entry}}` |
| `GET /api/bins` | roster: `{uid: {"name","team","period","bin","room","seen"}}` |
| `GET /api/history?uid=&from=&to=&step=5m\|1h` | `{"uid","step","points":[[ts, {metric:[min,avg,max,n]}], ...]}` |
| `GET /live` (Burrow) / `GET /live/<room>` (Surface) | SSE. `event: hello` on connect with `{edge, room, ts, bins, watching}` (the now-table); then `event: row` per ingest with `{"uid", "entry"}` where `entry` is that Bin's now-table entry (`ts, clk, src, edge, room, name, team, period, bin, home_room, d`). Surface replies 503 when the room's tunnel is down; the page falls back to polling |
| `GET /live?watch=<uid>[,<uid>]` | the 1 Hz live view: for as long as this client is connected the Burrow polls each listed Bin's `/data` once a second (config `watch.every_s`) and sends `event: live` with the same `{"uid", "entry"}` shape, `src: "live"`. Nothing is stored, the now-table and the cloud keep the 60 s push cadence; one poller per Bin however many viewers; unknown Bins are ignored (`hello.watching` lists the accepted ones); at most `watch.max_bins` (8) per Burrow. The Surface passes `watch` through on `/live/<room>` |
| `GET /api/status` (Burrow) | peers, cloud, disk, clock, counts, `tunnel` (the Opal watchdog's full state: repeater, cloud_ok, clients, uptime_s, reboots[], wifi_fallback, events[]) |

## Rollups

Metrics are every numeric, non-boolean top-level field of `d`; a list of
numbers becomes `<field>_<i>`. A rollup row is
`{"uid","step": "5m"|"1h","ts": <bucket start>,"data": {metric: [min, avg, max, n]}}`.
5-minute buckets are computed at seal time from the casting; hourly buckets
are computed from the 5-minute ones when the hour closes. Both are
derivable from castings and may be rebuilt at any time.

## Surface-only endpoints (the Worker; cookie `wh_session` unless noted)

| call | auth | meaning |
| ---- | ---- | ------- |
| `GET /api/teams` | none | `[{"id","name","period"}]` for the login form's dropdown |
| `POST /api/login` | none | `{"team_id","passphrase","first_name"}` -> sets cookie, `{"ok":true,"me":{...}}`; rate-limited per IP |
| `POST /api/logout` | cookie | clears the cookie |
| `GET /api/me` | cookie | `{"ok":true,"role":"team"|"teacher"|"admin","team":{...},"first_name":"..."}`; 401 `{"ok":false}` when not logged in |
| `GET /api/now` | cookie | merged snapshot of all edges, `Cache-Control: max-age=10` |
| `GET /api/bins` | cookie | roster |
| `GET /api/history?uid=&from=&to=&step=` | cookie | from D1 rollups |
| `GET /live/<room>` | cookie | SSE proxied from `https://burrow<room>.<TUNNEL_DOMAIN>/live` with header `X-Burrow-Key` |
| `GET /api/admin/edges` | admin/teacher | edges table (status, last_seen, version) |
| `GET /api/admin/teams` · `POST /api/admin/teams` · `POST /api/admin/teams/<id>/reset` · `DELETE /api/admin/teams/<id>` | admin | manage teams; create/reset return the new passphrase once |
| `POST /api/admin/teams/import` | admin | CSV body `team,period,bin,room`; returns the passphrases |
| `GET /api/admin/visits?since=&team=` | admin/teacher | recent visits + per-team counts |
| `GET /api/admin/sessions` | admin/teacher | who is logged in (last_seen within 10 min) |
| `GET /api/admin/castings?room=&day=` · `GET /api/admin/castings/<id>` | admin | list / stream a raw casting from R2 |
| `GET /api/admin/stats` | admin/teacher | D1 row counts, R2 object count estimate, writes today (if tracked) |

Roles: `team` (students; one login per team, each student types a first
name), `teacher` (read everything, see visitors), `admin` (everything). Page
views (any non-`/api` HTML request with a valid cookie) write one `visits`
row; API polls do not. `sessions.last_seen` is bumped at most every 5 min.

Secrets (wrangler secret put): `SESSION_SECRET` (HMAC for cookies),
`EDGE_TOKENS` (JSON `{"burrow1":"...","burrow2":"...","burrow3":"..."}`),
`LIVE_KEY` (sent to Burrows on /live), `ADMIN_BOOTSTRAP` (one-time password
that `POST /api/admin/bootstrap {"name","password"}` accepts to create the
first admin when the teams table has no admin yet).
Vars: `TUNNEL_DOMAIN` (e.g. `whs.makerlabkids.com`, giving burrow1.whs.makerlabkids.com).
