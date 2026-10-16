# e2e: the whole chain on one laptop

Real Worker (`wrangler dev`, local D1 + R2, `cloud/surface/wrangler.e2e.jsonc`
which serves `web/dash` and points `/live/1` at a tiny local proxy), a real
Burrow uploading to it, 12 fake Bins, and a headless Chromium driving the
dashboard: bootstrap admin, CSV import, student and staff logins, wall, bin
history, every admin tab, the live feed through the Worker, visits logging,
and the Burrow-hosted copy with no login. 26 checks, about two minutes.

```
cd tools/e2e && npm i && npx playwright install chromium   # once
tools/e2e/run.sh
```

Screenshots land in `tools/e2e/shots/`. The one check that is allowed to
nag is "no browser errors": an anonymous first `/api/me` (401) and the two
rooms without a tunnel (`/live/2`, `/live/3` → 503) show up in the console
by design.
