// Generates the cross-project navigation and the EVERYTHING install:
//
//   node tools/gen-packages.js
//
// writes:
//   docs/TOC.txt                     - plain-text index of install links,
//                                      installed onto every board as toc.txt
//   projects/blink/package.json      - the blink suite
//   projects/everything/package.json - ALL programs from ALL projects, each
//                                      in its own folder on the board, plus
//                                      every driver, worm-bin as the root
//                                      main.py, and toc.txt
//   and patches every other package.json to also install toc.txt.

const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const GH = "github:MakerLabKids/whs-wormhole";
const INSTALL = "https://viper-ide.org/?install=" + GH;

// ---- the manifest -------------------------------------------------
// Board layout for the EVERYTHING install: every entry lands at
// <boardDir>/<file>. Root entries (worm-bin) land at /.
const LIBS = ["picolab.py", "ssd1306.py", "bme280.py", "ads1115.py",
              "vl53l0x.py", "vl53l1x.py", "bh1750.py"];

const PROJECTS = [
  { name: "everything", desc: "ALL of the below on the board at once (this install)" },
  { name: "mission-control", desc: "one wall display for every station: join the WormHole net + aggregator server" },
  { name: "blink", dir: "projects/blink", boardDir: "blink",
    desc: "blink in 4 levels, up to async + morse-code your name",
    files: ["01_blink.py", "02_blink_config.py", "03_blink_async.py",
            "advanced/04_morse_name.py"] },
  { name: "worm-bin", dir: "projects/worm-bin", boardDir: "",   // board ROOT: ships as main.py
    desc: "THE CAPSTONE: every sensor + actuator at once (root main.py, runs at boot)",
    files: ["main.py", "index.html"] },
  // boardDir must NOT equal a lib module name: a root folder named
  // bme280 shadows lib/bme280.py and breaks every import of the driver
  // (found the hard way, on real hardware).
  { name: "bme280", dir: "projects/bme280", boardDir: "bme280-demos",
    desc: "temp/humidity/pressure in 4 tiers up to two hot-swap sensors",
    files: ["hello.py", "bench.py", "main.py", "multi.py", "index.html"] },
  { name: "soil-temperature", dir: "projects/soil-temperature", boardDir: "soil-temperature",
    desc: "DS18B20 probe array, per-probe POST codes, live rescan",
    files: ["bench.py", "main.py", "index.html"] },
  { name: "soil-moisture", dir: "projects/soil-moisture", boardDir: "soil-moisture",
    desc: "capacitive moisture with calibration",
    files: ["bench.py", "main.py", "index.html"] },
  { name: "light-basic", dir: "projects/light-basic", boardDir: "light-basic",
    desc: "GL5528 photoresistor divider (plus an ADS1115 variant)",
    files: ["hello_ads1115.py", "bench.py", "main.py", "index.html"] },
  { name: "light-lux", dir: "projects/light-lux", boardDir: "light-lux",
    desc: "BH1750 real-lux meter (shared classroom kit)",
    files: ["bench.py", "main.py", "index.html"] },
  { name: "sound", dir: "projects/sound", boardDir: "sound",
    desc: "MAX9814 mic level meter, clap test",
    files: ["bench.py", "main.py", "index.html"] },
  { name: "servo", dir: "projects/servo", boardDir: "servo",
    desc: "SG90 servo: web slider, sweep, follow-light",
    files: ["bench.py", "main.py", "index.html"] },
  { name: "speaker", dir: "projects/speaker", boardDir: "speaker",
    desc: "play tones + RTTTL melodies through an LM386 amp (the 'tunes')",
    files: ["main.py", "index.html"] },
  { name: "vibration", dir: "projects/vibration", boardDir: "vibration",
    desc: "buzz + tap the bin (transistor-driven motor) for behavior tests",
    files: ["main.py", "index.html"] },
  { name: "distance-vl53l1x", dir: "projects/distance-vl53l1x", boardDir: "distance-vl53l1x",
    desc: "long-range laser distance, 4 m",
    files: ["bench.py", "main.py", "index.html"] },
  { name: "distance-station", dir: "projects/distance-station", boardDir: "distance-station",
    desc: "the original VL53L0X station",
    files: ["main.py", "index.html"] },
];

const EXAMPLES = [
  { name: "01-hello-world", files: ["main.py"] },
  { name: "03-blink", files: ["main.py"] },
  { name: "04-webserver", files: ["main.py"] },
  { name: "05-display", files: ["main.py"] },
];

// Guard: a board folder that matches a driver module name shadows the
// driver on import. Refuse to generate such a layout.
const libNames = new Set(LIBS.map(l => l.replace(/\.py$/, "")));
for (const p of PROJECTS) {
  if (p.boardDir && libNames.has(p.boardDir)) {
    throw new Error(`boardDir "${p.boardDir}" shadows lib module ${p.boardDir}.py`);
  }
}

// ---- docs/TOC.txt -------------------------------------------------
let toc = `MAKER LAB KIDS - PICO PROJECT INDEX
====================================

With your Pico connected in Viper IDE, paste any install link below
into the browser and that project lands on the board. Stop a running
program (Ctrl+C or the Stop button), open any file in the file panel,
and run it. No reason to ever leave Viper.

`;
for (const p of PROJECTS) {
  toc += `${p.name}\n  ${p.desc}\n  ${INSTALL}/projects/${p.name}/package.json\n\n`;
}
toc += `workshop examples (01 hello-world, 03 blink, 04 webserver, 05 display)
  ${INSTALL}/examples/01-hello-world/package.json  (etc.)

Lab guide + wiring diagrams:  https://makerlabkids.github.io/whs-wormhole/
Electronics glossary:         https://makerlabkids.github.io/whs-wormhole/glossary.html
Programming cheat sheet:      https://makerlabkids.github.io/whs-wormhole/cheatsheet.html
Repo + docs:                  https://github.com/MakerLabKids/whs-wormhole
Firmware (.uf2, flash once):  https://github.com/MakerLabKids/whs-wormhole/raw/main/firmware/RPI_PICO2_W-20260406-v1.28.0.uf2
`;
fs.writeFileSync(path.join(ROOT, "docs", "TOC.txt"), toc);
console.log("wrote docs/TOC.txt");

const TOC_ENTRY = ["fs:toc.txt", `${GH}/docs/TOC.txt`];

// ---- projects/blink/package.json ---------------------------------
const blink = PROJECTS.find(p => p.name === "blink");
fs.mkdirSync(path.join(ROOT, "projects", "blink"), { recursive: true });
fs.writeFileSync(path.join(ROOT, "projects", "blink", "package.json"), JSON.stringify({
  name: "picolab-blink",
  version: "0.1.0",
  description: "Maker Lab Kids Pico blink suite: 4 levels from bare blink to async and morse (installs to the board root)",
  urls: blink.files.map(f => [`fs:${f}`, `${GH}/projects/blink/${f}`]).concat([TOC_ENTRY]),
}, null, 2) + "\n");
console.log("wrote projects/blink/package.json");

// ---- projects/everything/package.json ----------------------------
const urls = [];
for (const p of PROJECTS) {
  if (!p.files) continue;
  for (const f of p.files) {
    const target = p.boardDir ? `${p.boardDir}/${f}` : f;
    urls.push([`fs:${target}`, `${GH}/${p.dir}/${f}`]);
  }
}
for (const e of EXAMPLES) {
  for (const f of e.files) {
    urls.push([`fs:examples/${e.name}/${f}`, `${GH}/examples/${e.name}/${f}`]);
  }
}
for (const l of LIBS) {
  // fs: keeps the drivers as readable .py source on the board
  urls.push([`fs:lib/${l}`, `${GH}/lib/${l}`]);
}
urls.push(["fs:cal.js", GH + "/web/cal.js"]);
urls.push(TOC_ENTRY);

fs.mkdirSync(path.join(ROOT, "projects", "everything"), { recursive: true });
fs.writeFileSync(path.join(ROOT, "projects", "everything", "package.json"), JSON.stringify({
  name: "picolab-everything",
  version: "0.1.0",
  description: "Maker Lab Kids Pico EVERYTHING install: all projects in their own folders, all drivers, worm-bin as the boot program, and toc.txt for navigation",
  urls,
}, null, 2) + "\n");
console.log(`wrote projects/everything/package.json (${urls.length} files)`);

// ---- publish demo/ pages to docs/demos/ (the live Pages copies) ----
const demoSrc = path.join(ROOT, "demo");
const demoOut = path.join(ROOT, "docs", "demos");
fs.mkdirSync(demoOut, { recursive: true });
if (fs.existsSync(demoSrc)) {
  for (const f of fs.readdirSync(demoSrc)) {
    if (!f.endsWith(".html")) continue;
    // demo/mission-control-skins.html -> docs/demos/mission-control.html
    const out = f.replace(/-skins\.html$/, ".html");
    fs.copyFileSync(path.join(demoSrc, f), path.join(demoOut, out));
    console.log(`published demo/${f} -> docs/demos/${out}`);
    // the skins also ship inside the dashboard, so every Burrow (and the
    // website) serves them on live data at /wall.html
    if (f === "mission-control-skins.html") {
      fs.copyFileSync(path.join(demoSrc, f), path.join(ROOT, "web", "dash", "wall.html"));
      console.log(`published demo/${f} -> web/dash/wall.html`);
    }
  }
}

// ---- patch toc.txt into every other package.json ------------------
const pkgs = [];
for (const base of ["projects", "examples"]) {
  for (const d of fs.readdirSync(path.join(ROOT, base))) {
    const f = path.join(ROOT, base, d, "package.json");
    if (fs.existsSync(f)) pkgs.push(f);
  }
}
for (const f of pkgs) {
  const pkg = JSON.parse(fs.readFileSync(f, "utf8"));
  if (!pkg.urls) continue;
  if (!pkg.urls.some(u => u[0] === "fs:toc.txt")) {
    pkg.urls.push(TOC_ENTRY);
    fs.writeFileSync(f, JSON.stringify(pkg, null, 2) + "\n");
    console.log("patched toc into", path.relative(ROOT, f));
  }
}
console.log("done");
