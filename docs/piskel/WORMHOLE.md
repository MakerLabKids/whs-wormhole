# Piskel, the Wormhole build

This folder is a build of [Piskel](https://github.com/piskelapp/piskel) (Apache License 2.0,
see LICENSE here; copyright the Piskel authors), served from the lab guide so the class has a
pixel editor that is always there and already set up for the bin's screen.

Built from piskelapp/piskel commit 85800e3 (2026-10-28) with `npm ci && npm run build`, keeping
only what index.html loads (index.html, css/, img/, logo.png, js/piskel-packaged-min-*.js).

Our one change, in src/js/Constants.js: a new sprite is 128 x 64 at 10 frames a second
(upstream: 32 x 32 at 12), the size of the OLED on every bin.

docs/shows.html opens this editor and its "Get my drawing from Piskel" button reads the frames
straight out of the open editor (same site, so no export step).

To rebuild: clone piskelapp/piskel, set DEFAULT WIDTH 128 / HEIGHT 64 / FPS 10 in
src/js/Constants.js, `npm ci && npm run build`, copy the files above from dest/prod.
