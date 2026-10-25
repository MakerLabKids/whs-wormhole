# demo/ : the wall skins, live when they can be

Self-contained pages, no build. `mission-control-skins.html` runs on
**real data** when it can reach it: its own host's `/api/now` (a Burrow in
the classroom, or whs.makerlabkids.com when logged in), else the website's
public feed `https://whs.makerlabkids.com/api/public/now` (anonymous,
trimmed, cached 60 s). The badge in the rail says LIVE or SIMULATED. With no
feed reachable, or with the SIM button pressed, the built-in fake engine
runs instead, so the page still works offline for pitching a look or
rehearsing a lesson.

| Demo | What's inside | Live |
| ---- | ------------- | ---- |
| [`mission-control-skins.html`](mission-control-skins.html) | SEVEN skins for the classroom wall display, switchable at the top of the page: **1 Flight Deck** (NASA ops room), **2 The Living Bin** (animated worms in a soil cross-section), **3 The Leaderboard** (game-show rankings + confetti), **4 WORM//NET** (cyberpunk hologram + worm radar), **5 The Daily Worm**, **6 Orbital**, **7 Worm Ranch**. Live bins by period; the sim has 46 fake teams with drifting sensors and injected anomalies. | [view](https://makerlabkids.github.io/whs-wormhole/demos/mission-control.html) |

The REAL mission control (aggregator + wall page fed by actual Picos)
lives in [`projects/mission-control`](../projects/mission-control).

New demos go here. The copies under `docs/demos/` (GitHub Pages) and
`web/dash/wall.html` (served by every Burrow and the website, linked as
"Skins" in the dashboard header) are generated: run
`node tools/gen-packages.js` after editing.
