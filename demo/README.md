# demo/ : fake demos that run on their own

Self-contained pages with moving SIMULATED data. No hardware, no
server, no build: open the file in a browser, or use the live links.
Use them to pitch a look, rehearse a lesson, or argue about designs
before building the real thing.

| Demo | What's inside | Live |
| ---- | ------------- | ---- |
| [`mission-control-skins.html`](mission-control-skins.html) | FOUR skins for the classroom wall display, switchable at the top of the page: **1 Flight Deck** (NASA ops room), **2 The Living Bin** (animated worms in a soil cross-section), **3 The Leaderboard** (game-show rankings + confetti), **4 WORM//NET** (cyberpunk hologram + worm radar). Six fake teams, drifting sensors, injected anomalies. | [view](https://makerlabkids.github.io/wormhole/demos/mission-control.html) |

The REAL mission control (aggregator + wall page fed by actual Picos)
lives in [`projects/mission-control`](../projects/mission-control).

New fake demos go here. The live copies under `docs/demos/` are
generated: run `node tools/gen-packages.js` after adding one.
