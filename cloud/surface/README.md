# Surface: the Wormhole cloud tier

A single Cloudflare Worker (`src/index.js`, plain ES modules, no runtime
dependencies) with D1 (`DB`), R2 (`CASTINGS`) and the dashboard served as
static assets from `../../web/dash`. The wire protocol is
[`edge/burrow/PROTOCOL.md`](../../edge/burrow/PROTOCOL.md); the design is
`docs/design/index.html`. Free tier only: no Durable Objects, KV or Queues.

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

- `/api/now` is cached 10 s at the edge after the cookie check; anonymous
  requests never see the cached body.
- `run_worker_first` is `["/*", "!/*.*"]`: extension-less paths (the SPA
  routes) go through the Worker so a logged-in page view writes its `visits`
  row; files with an extension are served straight from assets.
- PBKDF2 (100000 iterations) costs real CPU per login and per team created;
  the CSV import is capped at 60 rows per request for that reason.
- Castings are never parsed by the Worker, only hashed; `verified_at` is set
  only by `/v1/edge/verify` after reading the object back from R2.
