# Worm Mission Control: the dashboard

The web front end for the worm-bin telemetry. Plain HTML/CSS/JS, no build
step, no external resources: a classroom Burrow serves it from the Pi with no
internet for weeks at a time, and the Surface (the Cloudflare Worker at
whs.makerlabkids.com) serves the identical files behind a cookie login.

## Files

| file | what |
| ---- | ---- |
| `index.html` | the one page: header (counts, edge badges, live dot, clock, sign-in), `<main id="view">`, footer. Loads `/charts.js` then `/app.js`. Favicon is an inline data URI. All asset paths are absolute so the page works at `/bin/<uid>` too. |
| `style.css` | the whole look; the guide's palette (`docs/guide.css`) as CSS variables, a `prefers-color-scheme: dark` variant, projector mode, print rules for team cards. |
| `charts.js` | `LineChart(box, opts)` (canvas line of bucket averages with a min..max band, axes, hover tooltip, retina-aware, resizes with its box, breaks lines at gaps) and `sparkline(canvas, values, color)`. |
| `app.js` | router, host detection, data layer (polling + SSE), and one `view*` function per route. |
| `favicon.svg` | the same icon as a file, in case a host wants `/favicon.svg`. |

## Routing

Path-based, with `history.pushState`. Both hosts serve `index.html` for any
unknown path, so a reload or a shared link on `/bin/<uid>` works. Clicks on
same-origin `<a href="/...">` links are intercepted; `/api/...` links and
`download` links pass through.

| route | view |
| ----- | ---- |
| `/` | status wall: one tile per bin, grouped by room then period, sorted by bin number |
| `/bin/<uid>` | deep history for one bin (6h / 24h / 3d / 7d / 30d) |
| `/feed` | live ticker + sparklines (`/live` is **not** a page: on a Burrow `GET /live` is the SSE stream itself) |
| `/login` | Surface only; on a Burrow it just says there is nothing to sign in to |
| `/admin`, `/admin/<tab>` | Surface only, role teacher/admin; tabs `edges`, `sessions`, `visits`, `teams` (admin), `castings` (admin), `stats` |
| `/about` | what the colors mean, where the data goes |

**Host detection.** The first request is `GET /api/me`. `{"local": true}` means
a Burrow: no login, no admin link, SSE on `/live`. Anything else is the
Surface: a 401 from `/api/me` (or from any later API call) swaps the current
view for the login form without changing the URL, so a reload after signing
in lands on the page the student wanted. SSE on the Surface opens `/live/1`,
`/live/2`, `/live/3`; each is optional (a dark room just stays disconnected).

## Status thresholds (same as the demo wall, `docs/demos/mission-control.html`)

Evaluated per tile from the entry's `d` dict, in this order:

| status | color | rule |
| ------ | ----- | ---- |
| STALE | grey, striped | `entry.stale` or `now - ts > 180 s` (a reading from an hour ago says nothing about the bin now) |
| ALARM | red | `in_temp_c > 30` or `< 10`, or any of `moist1_pct`, `moist2_pct` `< 15` |
| WARN | orange | `in_temp_c > 27` or `< 15`, or any moisture `< 25`, or a `parts[]` entry with `ok: false` |
| NOMINAL | green | everything else |

Every metric is optional; a missing field never trips a rule. Counts in the
header, the lamp on each tile and the legend on `/about` all use these.
Status is never color alone: the tile carries the word (NOMINAL / WARN /
ALARM / STALE) next to the lamp.

Edge badges (header) come from `/api/now`'s `edges` map: up = its `ts` is
under 5 minutes old; the badge shows room, clock quality (`ntp` / `peer` /
`free`, the latter in yellow), `cloud ok`, and `castings/unverified`.

## Data flow in the page

- `/api/now` every 15 s, always (the header lives on every page). Tiles are
  keyed by uid and updated in place; a tile only re-renders when its `ts` or
  status changed, and only moves when its room/period changed, so the wall
  never jumps under a projector.
- SSE `row` events are applied immediately (a brief blue flash on the tile).
  The page accepts both `{"uid","entry"}` (what the Burrow sends today) and
  the bare row JSON that PROTOCOL.md describes. `hello` seeds the table.
- After repeated SSE failures the sources are closed and reopened with
  exponential backoff (2 s .. 60 s). The live page shows "edge offline,
  polling instead" and feeds the ticker from `/api/now` diffs meanwhile.
- `/api/history?uid=&from=&to=` with no `step`: the server picks 5m or 1h and
  the page shows which came back. Points are pivoted into per-metric series;
  a hole longer than 1.5 steps breaks the line.
- Live sparklines keep the last 60 values per metric per bin in memory only.
- Projector mode (`localStorage["dash.projector"]`) and the last history
  range (`dash.range`) are remembered per browser.

## Chart series colors

Lines within one chart use, in order: blue `#2E7DBC`, orange `#D9641F`,
violet `#6A5ACD`, green `#5F9E2E` in light mode and `#3A86CC`, `#D9641F`,
`#8578DC`, `#6AA536` on the dark card surface. Both sets pass the dataviz
validator (lightness band, chroma, CVD separation, contrast); "room" and "probe"
series are also dashed and every line ends in a direct label, so identity is
never color alone.

## Test it locally

```
cd edge/burrow
python3 tests/fake_surface.py 8787 &                  # stand-in cloud for the Burrow's uploads
mkdir -p /tmp/b1 && echo test-token > /tmp/b1/token
cat > /tmp/b1/burrow.json <<'J'
{"edge":"burrow1","room":1,"port":8080,"data_dir":"/tmp/b1/data","www_dir":"/workspace/web/dash",
 "peers":{},"cloud":{"url":"http://127.0.0.1:8787","token_file":"/tmp/b1/token"},"sweep":{"enabled":false},"seal_minutes":1}
J
BURROW_CONFIG=/tmp/b1/burrow.json python3 -m burrow &
python3 tools/simbins.py --n 17 --every 10            # 17 fake Bins
```

Open http://127.0.0.1:8080/ (change `port` if 8080 is taken). `seal_minutes: 1`
makes castings seal every minute so `/bin/<uid>` has history within a couple
of minutes instead of a quarter hour.

Syntax check: `node --check app.js && node --check charts.js`. For a headless
render check, Playwright's Chromium works in a container where the snap
`chromium` does not: `npm i playwright && npx playwright install chromium`,
then a short script that loads `/`, `/bin/<uid>`, `/feed` and asserts no
`pageerror` / console errors (the session's scratch scripts did exactly that).

The Surface-only paths (login, admin, `/live/<room>`) need a stand-in Worker;
the Worker itself is not in this repo. A small Python fake that serves these
files, proxies the viewer API to a Burrow and fakes `/api/me`, `/api/teams`,
`/api/login`, `/api/logout` and `/api/admin/*` was used for the checks.
