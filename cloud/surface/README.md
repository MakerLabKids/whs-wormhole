# Surface: the Wormhole cloud tier

A single Cloudflare Worker (`src/index.js`, plain ES modules, no runtime
dependencies) with D1 (`DB`), R2 (`CASTINGS`) and the dashboard served as
static assets from `../../web/dash`. The wire protocol is
[`edge/burrow/PROTOCOL.md`](../../edge/burrow/PROTOCOL.md); the design is
the design pages (private repo MakerLabKids/whs-wormhole-private, design/index.html). Free tier only: no Durable Objects, KV or Queues.

```
src/index.js   router, page views (visits), /live/<room> proxy
src/edge.js    /v1/edge/*  ping, snapshot, castings PUT, rollups, verify
src/auth.js    PBKDF2 passwords, HMAC cookie sessions, /api/login|logout|me|teams
src/viewer.js  /api/now (10 s edge cache), /api/bins, /api/history
src/admin.js   /api/admin/* (roles), passphrases, CSV import, bootstrap
schema.sql     D1 tables (idempotent)
tools/gen-secrets.sh  prints every secret + the three Burrow token files
```

## Deploy (first time, in this order)

```sh
cd cloud/surface
npm i
npx wrangler login

# 1. Database: create, paste the printed database_id into wrangler.jsonc, load the schema.
npx wrangler d1 create wormhole
#    -> edit wrangler.jsonc: "database_id": "REPLACE_ME"  ->  the id printed above
npx wrangler d1 execute wormhole --remote --file schema.sql

# 2. Bucket.
npx wrangler r2 bucket create wormhole-castings

# 3. Secrets. gen-secrets.sh prints fresh values (and the Burrow token files);
#    `--put` also pushes them. Or do it by hand:
tools/gen-secrets.sh --put
#    by hand:
#    openssl rand -hex 32 | npx wrangler secret put SESSION_SECRET      # signs the wh_session cookie
#    openssl rand -hex 32 | npx wrangler secret put LIVE_KEY            # X-Burrow-Key sent to the tunnels
#    openssl rand -hex 16 | npx wrangler secret put ADMIN_BOOTSTRAP     # one-time, for the first admin
#    printf '{"burrow1":"<t1>","burrow2":"<t2>","burrow3":"<t3>"}' | npx wrangler secret put EDGE_TOKENS

# 4. Deploy. The custom domain whs.makerlabkids.com must be a zone in this account;
#    the route in wrangler.jsonc creates the DNS record.
npx wrangler deploy

# 5. First admin (allowed only while no admin exists; needs the ADMIN_BOOTSTRAP value).
curl -sS https://whs.makerlabkids.com/api/admin/bootstrap \
  -H 'content-type: application/json' \
  -d '{"name":"ms-teacher","password":"<a real password, 8+ chars>","bootstrap":"<ADMIN_BOOTSTRAP>"}'

# 6. Log in as that admin (cookie jar), then create teams. Each reply carries the
#    passphrase exactly once; print it on the team's bin card.
curl -sS -c jar.txt https://whs.makerlabkids.com/api/login \
  -H 'content-type: application/json' \
  -d '{"name":"ms-teacher","passphrase":"<password>"}'
curl -sS -b jar.txt https://whs.makerlabkids.com/api/admin/teams \
  -H 'content-type: application/json' \
  -d '{"name":"Dirt Vader","period":3,"bin":7,"room":1}'
#    or many at once from CSV (team,period,bin,room; header optional; <= 60 rows per call):
curl -sS -b jar.txt https://whs.makerlabkids.com/api/admin/teams/import --data-binary @teams.csv
#    a teacher account (real password instead of a passphrase):
curl -sS -b jar.txt https://whs.makerlabkids.com/api/admin/teams \
  -H 'content-type: application/json' -d '{"name":"Mr Soil","role":"teacher","password":"<8+ chars>"}'
```

Then on each Burrow: write its token (from `gen-secrets.sh`) to
`/etc/burrow/cloud.token` and the LIVE_KEY to `/etc/burrow/live.key`; the
Burrow itself rejects any request arriving through its tunnel
(`burrow<N>.whs.makerlabkids.com`) that lacks `X-Burrow-Key: <LIVE_KEY>`.

Staff log in with `{"name": ..., "passphrase": <password>}` (or `team_id`);
students pick a team and type the three-word passphrase plus a first name.
Passphrases are matched case-insensitively and spaces count as hyphens.

## Local development

`wrangler.local.jsonc` is the same Worker with local D1/R2, a tiny
`test-assets/` dir instead of `web/dash`, and dummy secrets as vars
(`EDGE_TOKENS` = tok1/tok2/tok3, `ADMIN_BOOTSTRAP` = `bootstrap-me`).

```sh
npx wrangler d1 execute wormhole --local -c wrangler.local.jsonc --file schema.sql   # seed the schema
npx wrangler dev -c wrangler.local.jsonc --port 8787                                   # http://localhost:8787
curl -sS localhost:8787/api/admin/bootstrap -H 'content-type: application/json' \
  -d '{"name":"admin","password":"password123","bootstrap":"bootstrap-me"}'
curl -sS localhost:8787/v1/edge/ping -H 'authorization: Bearer tok1'
```

To point the dev server at the real dashboard, change `assets.directory` in
the local config to `../../web/dash`. To run a Burrow against it, set its
`cloud.url` to the dev URL and its token file to `tok1`. `LIVE_BASE` (var) makes
`/live/<room>` fetch `<LIVE_BASE>/burrow<room>/live` instead of the tunnel
hostnames, for a laptop Burrow.

## Tests

```sh
npx vitest run
```

Tests run inside workerd (`@cloudflare/vitest-plugin`) against real local D1
and R2 bindings from `wrangler.local.jsonc`: edge auth, casting PUT + verify
(mismatch, tamper, re-upload), rollups + history, snapshot merge, login flow and
rate limit, visits on page views, the `/live` proxy, admin roles.

## Operational notes

- Viewing is open to anyone: `/api/now`, `/api/bins`, `/api/history` and the
  `/live/<room>` streams need no login. An anonymous `/api/now` gets each Burrow's
  status trimmed to the wall header's fields (no network, tunnel or event
  details); it is cached 10 s apart from the logged-in copy. Changing things
  needs a login: messages, shows, `/api/admin/*` (role checked), the
  `/api/edge/<room>/*` tools (signal meter, Devices, undated CSV), and the
  Bluetooth page (`/bluetooth.html` redirects to `/login?next=`).
- `run_worker_first` is `["/*", "!/*.js", "!/*.css", "!/*.svg", "!/*.png",
  "!/*.ico", "!/*.md"]`: the SPA routes and the `.html` pages go through the
  Worker (a logged-in page view writes its `visits` row; `bluetooth.html` needs
  a login); scripts, styles and images are served straight from assets.
- PBKDF2 (100000 iterations) costs real CPU per login and per team created;
  the CSV import is capped at 60 rows per request for that reason.
- Castings are never parsed by the Worker, only hashed; `verified_at` is set
  only by `/v1/edge/verify` after reading the object back from R2.

## Alerts to your phone (optional, 2 minutes)

The Burrows push events the moment they happen (a bin silent 10 min, an Opal rebooted by
its watchdog, the cloud link back after an outage) and a cron in the Worker notices a Burrow
that stopped reporting for 3 minutes. Both can notify a human through any ntfy-style URL:

1. Install the ntfy app (Android/iOS) and subscribe to a private topic, e.g.
   `whs-wormhole-<something random>`.
2. `npx wrangler secret put ALERT_URL` and paste `https://ntfy.sh/<that topic>` (a bare
   `ntfy.sh/<topic>` or just `<topic>` is accepted too).
3. Optional: an ntfy access token (ntfy.sh/account > Access tokens) as
   `npx wrangler secret put ALERT_TOKEN`, or `https://user:pass@ntfy.sh/<topic>` in ALERT_URL.
   This setup delivers (2026-10-30: alerts arrived from every Burrow). **If ntfy answers 429,
   suspect our own sending first** (see "When alerts stop arriving" below): on 2026-10-29 and
   2026-11-01 the 429s followed floods of sends from our side, not a limit on normal use.
   **Free alternatives** that work from a Worker, same ALERT_URL secret:
   - Discord: make a server, channel > Edit > Integrations > Webhooks > New, copy the URL
     (`https://discord.com/api/webhooks/...`). The Discord phone app buzzes on each message.
   - Telegram: talk to @BotFather (`/newbot`), get the bot token; start a chat with the bot and
     read your chat id from `https://api.telegram.org/bot<token>/getUpdates`; set ALERT_URL to
     `https://api.telegram.org/bot<token>/sendMessage?chat_id=<id>`.
4. `npx wrangler deploy`. The Devices page shows "notifier configured" and lists open alerts;
   its "send a test alert to the phone" button (admin) shows exactly what ntfy answered.

### When alerts stop arriving

Check how much WE are sending before blaming the notifier:
- Devices page / `GET /api/admin/alerts`: `notify_error` per alert. Many alerts for the same
  key opened minutes apart = a loop.
- `GET /api/admin/events`: the same edge + ts + text stored many times = a Burrow re-sending a
  batch. On the Burrow, `/api/events` -> `state` shows sent / failed / last_error.
- 2026-11-01: postEvents notified every alert in a batch, one after another, before replying.
  A slow notifier made a 48-event batch outlast burrow1's 20 s timeout; burrow1 re-sent it
  every 20-30 s (8 events stored ~50 times each in 20 min, 132 failed posts), and each copy
  called ntfy again: hundreds of sends an hour, which ntfy then refused. Fixed (f411615): the
  reply goes out as soon as the events are stored, notifications run after it
  (ctx.waitUntil), and a re-sent batch (same edge, ts, kind, text) is stored and alerted once.

`ALERT_BINS=1` (a var in wrangler.jsonc) also notifies every bin that goes quiet; off by
default, since unplugged bins are normal. After changing schema.sql run
`npx wrangler d1 execute wormhole --remote --file schema.sql` once (idempotent) to add the
`events` and `alerts` tables.

## Enrolment: a fresh Pi is told who it is

`POST /v1/edge/enrol {secret, serial, room, eth_mac, wlan_mac}` (no bearer token: the fleet
secret `ENROL_SECRET` is the key). The Pi takes `room` from the subnet its Opal handed it
(192.168.8<room>.x), so it is named by where it stands: `burrow<room>`. The reply carries a fresh
upload token (only its sha256 is kept, table `enrolled`) and the room's cloudflared token from the
`TUNNEL_TOKENS` secret (`{"burrow0": "...", ...}`, the tokens from the Zero Trust dashboard). A new
Pi in a room replaces the previous one: the old token stops working and a `burrow.enrolled` warn
event names both serials. The static `EDGE_TOKENS` keep working alongside.

Setup once, from cloud/surface (the helper pipes each value from the repo's .env, never shown):
`../../tools/surface-secret.sh ENROL_SECRET | npx wrangler secret put ENROL_SECRET` (.env
`enrol_secret`, also on the Pis at /etc/burrow/enrol.secret) and
`../../tools/surface-secret.sh TUNNEL_TOKENS | npx wrangler secret put TUNNEL_TOKENS` (.env
`TUNNEL_TOKENS`, JSON; each Pi's own copy is /etc/cloudflared/token).

## Rollouts: update one Burrow at a time

`POST /api/admin/rollout {edge, build}` (admin): the Worker fetches that commit's tarball from
GitHub (`ROLLOUT_TARBALL_BASE` + `/<build>`, default codeload), stores it in the castings bucket
under `rollouts/<build>.tgz`, records its sha256, and from then on that Burrow's snapshot reply
carries `update_to: {build, sha256, url}` with `url` = this Surface's `/v1/edge/rollout/<build>`
(bearer token). The row closes when the Burrow's snapshot reports that build; 30 minutes without
is an error; `POST /api/admin/rollout/cancel {edge}`. `GET /api/admin/rollout` lists them and says
which Burrow is open; the admin page's Devices tab has the input and the buttons. Only one Burrow
updates at a time by construction. Table `rollouts` in schema.sql.

The Devices page also alerts when a Burrow runs on its own Wi-Fi (`tunnel.wifi_fallback == "up"`)
and when followers of a backhaul provider report no internet through it (`sameOpal` matches a
follower's provider BSSID to a provider's station MAC).

## Messages for a bin's screen

`/api/messages` (cookie): `GET ?uid=` lists a bin's five slots and their delivery status;
`POST {uid, slot, pin, title, lines[], start, end, count, boot}` sets one, `POST {uid, slot,
pin, clear: true}` empties it. A team may fill slots 1-3 of its own bin (the bin whose number
matches the team's), a teacher or admin any slot of any bin. The board's PIN travels with the
message and the board checks it (the Surface never knows PINs). Every snapshot reply lists the
undelivered messages (`messages: [...]`) for all bins; a Burrow hands a Bin its own on the next
push, the Bin acks by `seq` in its data (`msg_seq`), and the next snapshot brings the ack here
(`delivered_at`, `result` ok/refused). The dashboard's bin page has the editor (`msg.js`, the
same widget the board's own page uses); `bluetooth.html` is the same editor over Web Bluetooth.
The board is the truth: every Bin reports its slots (and who set each, through which door) by
revision, the Burrows relay that in `messages_state`, and `bin_messages` keeps the latest. `GET`
returns it as `board`; the bin page shows those slots, marks the Surface's own copies that are
still on their way as "waiting for the bin", and sends the `rev` it saw with every save; a save
based on an older `rev` gets 409 and the page reloads first. Both tables are in schema.sql: run
the d1 execute line above once after deploying.
