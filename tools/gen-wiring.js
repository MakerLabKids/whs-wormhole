// Generates branded SVG wiring diagrams for every Pico demo, one per
// project, into docs/wiring/. Pure string SVG, no dependencies.
//
//   node tools/gen-wiring.js
//
// The Pico 2 W shares the standard 40-pin Pico header. Each diagram
// shows the board, shared 3V3 / GND power rails, the always-present
// OLED, and that project's sensor or actuator, wired exactly as the
// project README. Signal wires each get their own vertical lane so no
// two wires overlap.

const fs = require("fs");
const path = require("path");

const OUT = path.join(__dirname, "..", "docs", "wiring");
fs.mkdirSync(OUT, { recursive: true });

const C = {
  blue: "#2E7DBC", green: "#7CB342", orange: "#E8762C", yellow: "#C99A1E",
  navy: "#1B3A5C", ink: "#222A35", light: "#F4F7FA", gray: "#6B7280",
  board: "#1B5E20", boardEdge: "#0E3D12", pad: "#C9A227", padHole: "#5C4A00",
  padOff: "#AEB6BF",
};
// Class wiring convention (one source of truth):
//   red    = 3V3 power        orange = 5V / VBUS        dark = GND
//   green  = DATA  -> I2C SDA, the 1-Wire probe bus, and SPI MISO (POCI)
//   white  = CLOCK -> I2C SCL and SPI SCK  (grey casing so it shows)
//   yellow = a lone signal, and SPI chip-select (CS)
//   blue   = SPI MOSI (PICO, data out from the Pico)
const W = {
  pwr: "#C62828", gnd: "#37474F", sda: "#7CB342", scl: "#FFFFFF",
  sig: "#E8B62C", vbus: "#E8762C", mosi: "#2E7DBC",
};
const CASING = "#8B949C";  // outline under white wires

const FUNC = {
  1: "GP0", 2: "GP1", 3: "GND", 4: "GP2", 5: "GP3", 6: "GP4", 7: "GP5",
  8: "GND", 9: "GP6", 10: "GP7", 11: "GP8", 12: "GP9", 13: "GND",
  14: "GP10", 15: "GP11", 16: "GP12", 17: "GP13", 18: "GND", 19: "GP14",
  20: "GP15", 21: "GP16", 22: "GP17", 23: "GND", 24: "GP18", 25: "GP19",
  26: "GP20", 27: "GP21", 28: "GND", 29: "GP22", 30: "RUN", 31: "GP26",
  32: "GP27", 33: "AGND", 34: "GP28", 35: "VREF", 36: "3V3", 37: "3V3EN",
  38: "GND", 39: "VSYS", 40: "VBUS",
};
const ADC = { 31: "ADC0", 32: "ADC1", 34: "ADC2" };

const BX = 118, BY = 104, BW = 152, BH = 476;
const ROW_Y0 = BY + 34, PITCH = 22;
const PAD_L = BX + 14, PAD_R = BX + BW - 14;
const EXIT_L = BX, EXIT_R = BX + BW;

function pin(p) {
  let row, x;
  if (p <= 20) { row = p - 1; x = PAD_L; }
  else { row = 40 - p; x = PAD_R; }
  return { x, y: ROW_Y0 + row * PITCH, side: p <= 20 ? "L" : "R" };
}

const RAIL_PWR = 298, RAIL_GND = 330, RAIL_TOP = 120;
const DEV_X = 452, DEV_W = 150;

// per-diagram wire-lane allocators
let CH, TOPY, USED, RAIL_MAXY;
function reset(usedPins) {
  CH = RAIL_GND + 20;   // first vertical signal lane, right of the rails
  TOPY = 64;            // first horizontal lane above the board
  USED = new Set(usedPins);
  RAIL_MAXY = Math.max(pin(36).y, pin(38).y);
}
function nextCH() { const x = CH; CH += 13; return x; }
function nextTOP() { const y = TOPY; TOPY += 12; return y; }

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
function text(x, y, s, o = {}) {
  const { size = 12, color = C.ink, bold = false, anchor = "start", italic = false, halo = false } = o;
  const h = halo ? ' stroke="#FFFFFF" stroke-width="2.6" paint-order="stroke" stroke-linejoin="round"' : "";
  return `<text x="${x}" y="${y}" font-family="Arial, Helvetica, sans-serif" font-size="${size}"`
    + ` fill="${color}" text-anchor="${anchor}"${bold ? ' font-weight="bold"' : ""}`
    + `${italic ? ' font-style="italic"' : ""}${h}>${esc(s)}</text>`;
}
const CASED = () => [W.scl, W.sig];  // light colors that need an outline on white
function wire(pts, color, width = 3.5) {
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0] + " " + p[1]).join(" ");
  let s = "";
  if (CASED().includes(color)) {
    s += `<path d="${d}" fill="none" stroke="${CASING}" stroke-width="${width + 2.6}"`
      + ` stroke-linejoin="round" stroke-linecap="round"/>`;
  }
  s += `<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}"`
    + ` stroke-linejoin="round" stroke-linecap="round"/>`;
  return s;
}
// a filled triangle arrowhead: tip AT (x,y), pointing along (dx,dy)
function arrowhead(x, y, dx, dy, len, color) {
  const L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L, px = -uy, py = ux;
  const bx = x - ux * len, by = y - uy * len, w = len * 0.5;
  return `<path d="M${x} ${y} L${bx + px * w} ${by + py * w} L${bx - px * w} ${by - py * w} z" fill="${color}"/>`;
}
function dot(x, y, color) {
  const ring = CASED().includes(color) ? ` stroke="${CASING}" stroke-width="1.6"` : "";
  return `<circle cx="${x}" cy="${y}" r="4.2" fill="${color}"${ring}/>`;
}

function drawPico() {
  let s = `<rect x="${BX}" y="${BY}" width="${BW}" height="${BH}" rx="12"`
    + ` fill="${C.board}" stroke="${C.boardEdge}" stroke-width="2"/>`;
  s += `<rect x="${BX + BW / 2 - 22}" y="${BY - 13}" width="44" height="17" rx="4"`
    + ` fill="#9AA5AD" stroke="#6B7680" stroke-width="1.5"/>`;
  s += text(BX + BW / 2, BY + 20, "Pico 2 W", { size: 11, color: "#C7E0C9", anchor: "middle", bold: true });
  for (let p = 1; p <= 40; p++) {
    const { x, y } = pin(p);
    const used = USED.has(p);
    // GROUND pads are SQUARE on the real Pico, everything else is ROUND.
    // It is the best landmark for counting pins, so match it exactly.
    if (FUNC[p] === "GND" || FUNC[p] === "AGND") {
      s += `<rect x="${x - 7}" y="${y - 7}" width="14" height="14" rx="1"`
        + ` fill="${used ? C.pad : C.padOff}" stroke="${C.boardEdge}" stroke-width="1"/>`;
    } else {
      s += `<circle cx="${x}" cy="${y}" r="7.2"`
        + ` fill="${used ? C.pad : C.padOff}" stroke="${C.boardEdge}" stroke-width="1"/>`;
    }
    s += `<circle cx="${x}" cy="${y}" r="3" fill="${used ? C.padHole : "#7E8791"}"/>`;
    const inX = p <= 20 ? x + 13 : x - 13;
    const anchor = p <= 20 ? "start" : "end";
    s += text(inX, y + 4, FUNC[p], { size: 10.5, color: "#EAF4EB", bold: used, anchor });
    if (ADC[p]) {
      const ax = p <= 20 ? inX + 34 : inX - 34;
      s += text(ax, y + 4, ADC[p], { size: 8, color: "#A6C4A8", anchor });
    }
  }
  return s;
}

// Pin numbers are drawn LAST (see diagram()) so they sit ON TOP of the
// wires: the connected pins are the ones you most need to read, and their
// own wires would otherwise bury the number. Halo keeps them legible.
function drawPinNumbers() {
  let s = "";
  for (let p = 1; p <= 40; p++) {
    const { x, y } = pin(p);
    const used = USED.has(p);
    const numX = p <= 20 ? x - 20 : x + 20;   // pushed clear of the board edge
    s += text(numX, y + 3.5, p, { size: 9, color: used ? C.ink : "#3B4756", anchor: p <= 20 ? "end" : "start", bold: used, halo: true });
  }
  return s;
}

function drawRails() {
  const bot = RAIL_MAXY + 16;
  let s = wire([[RAIL_PWR, RAIL_TOP], [RAIL_PWR, bot]], W.pwr, 5);
  s += wire([[RAIL_GND, RAIL_TOP], [RAIL_GND, bot]], W.gnd, 5);
  s += text(RAIL_PWR, RAIL_TOP - 8, "3V3", { size: 11, color: W.pwr, anchor: "middle", bold: true });
  s += text(RAIL_GND, RAIL_TOP - 8, "GND", { size: 11, color: W.gnd, anchor: "middle", bold: true });
  const p36 = pin(36), p38 = pin(38);
  s += wire([[EXIT_R, p36.y], [RAIL_PWR, p36.y]], W.pwr) + dot(EXIT_R, p36.y, W.pwr);
  s += wire([[EXIT_R, p38.y], [RAIL_GND, p38.y]], W.gnd) + dot(EXIT_R, p38.y, W.gnd);
  return s;
}

// rail tap: horizontal from a rail to a device pin
function tap(railX, dp, color) {
  if (dp.y > RAIL_MAXY) RAIL_MAXY = dp.y;
  return wire([[railX, dp.y], [dp.x, dp.y]], color) + dot(dp.x, dp.y, color);
}
// signal wire from a Pico pin to one device pin, on its own lane
function sig(pinNum, dp, color) {
  const pp = pin(pinNum), cx = nextCH();
  let pts, start;
  if (pp.side === "L") {
    const ty = nextTOP(), lx = EXIT_L - (10 + (TOPY - 70));
    pts = [[EXIT_L, pp.y], [lx, pp.y], [lx, ty], [cx, ty], [cx, dp.y], [dp.x, dp.y]];
    start = [EXIT_L, pp.y];
  } else {
    pts = [[EXIT_R, pp.y], [cx, pp.y], [cx, dp.y], [dp.x, dp.y]];
    start = [EXIT_R, pp.y];
  }
  return wire(pts, color) + dot(start[0], start[1], color) + dot(dp.x, dp.y, color);
}
// shared bus: one Pico pin feeding several device pins from one lane.
// Left-side pins route up over the board; right-side pins go straight
// out to their lane.
function bus(pinNum, dps, color) {
  const pp = pin(pinNum), cx = nextCH();
  let s;
  if (pp.side === "L") {
    const ty = nextTOP();
    const lx = EXIT_L - (10 + (TOPY - 70));
    s = wire([[EXIT_L, pp.y], [lx, pp.y], [lx, ty], [cx, ty]], color) + dot(EXIT_L, pp.y, color);
    const maxY = Math.max(...dps.map(d => d.y));
    s += wire([[cx, ty], [cx, maxY]], color);
  } else {
    s = wire([[EXIT_R, pp.y], [cx, pp.y]], color) + dot(EXIT_R, pp.y, color);
    const minY = Math.min(...dps.map(d => d.y), pp.y);
    const maxY = Math.max(...dps.map(d => d.y), pp.y);
    s += wire([[cx, minY], [cx, maxY]], color);
  }
  for (const d of dps) s += wire([[cx, d.y], [d.x, d.y]], color) + dot(d.x, d.y, color);
  return s;
}

// ---- resistors with real color bands --------------------------------
const BAND_HEX = ["#1B1B1B", "#7B4A12", "#C62828", "#F57C00", "#F2C400",
                  "#3B8C3F", "#1E64B4", "#7E2AA8", "#8E8E8E", "#FAFAFA"];
const BAND_NAME = ["black", "brown", "red", "orange", "yellow",
                   "green", "blue", "violet", "grey", "white"];
const GOLD = "#C9A227";

function bandDigits(ohms) {
  let mult = 0, v = ohms;
  while (v >= 100) { v /= 10; mult++; }
  v = Math.round(v);
  return [Math.floor(v / 10), v % 10, mult];   // 2 digits + multiplier
}
// 4-band (5%) name string, e.g. "yellow violet red gold"
function bandWords(ohms) {
  const [a, b, m] = bandDigits(ohms);
  return `${BAND_NAME[a]} ${BAND_NAME[b]} ${BAND_NAME[m]} gold`;
}
// 5-band (1%) name string: 3 digits + multiplier + brown
function bandWords5(ohms) {
  const [a, b, m] = bandDigits(ohms);
  return `${BAND_NAME[a]} ${BAND_NAME[b]} black ${BAND_NAME[m - 1]} brown`;
}
// Tan resistor body with its actual 4 bands. vertical=true stands it up.
function resistorGlyph(x, y, w, h, ohms, vertical) {
  const [a, b, m] = bandDigits(ohms);
  const cols = [BAND_HEX[a], BAND_HEX[b], BAND_HEX[m], GOLD];
  let s = `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3"`
    + ` fill="#E9D9B6" stroke="${C.ink}" stroke-width="1.3"/>`;
  cols.forEach((c, i) => {
    const f = 0.16 + i * 0.2;
    if (vertical) {
      s += `<rect x="${x + 1}" y="${y + h * f}" width="${w - 2}" height="${Math.max(3, h * 0.09)}" fill="${c}"/>`;
    } else {
      s += `<rect x="${x + w * f}" y="${y + 1}" width="${Math.max(3, w * 0.09)}" height="${h - 2}" fill="${c}"/>`;
    }
  });
  return s;
}

function deviceBox(x, y, w, h, title, sub, accent, dashed) {
  let s = `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="9" fill="${dashed ? "#FFFFFF" : C.light}"`
    + ` stroke="${accent}" stroke-width="2.5"${dashed ? ' stroke-dasharray="6 4"' : ""}/>`;
  if (!dashed) {
    s += `<path d="M${x} ${y + 9} q0 -9 9 -9 h${w - 18} q9 0 9 9 v17 h-${w} z" fill="${accent}"/>`;
    s += text(x + w / 2, y + 18, title, { size: 13, color: "#FFFFFF", anchor: "middle", bold: true });
  } else {
    s += text(x + w / 2, y + 17, title, { size: 12, color: C.gray, anchor: "middle", bold: true });
  }
  if (sub) s += text(x + w / 2, y + h + 14, sub, { size: 9.5, color: C.gray, anchor: "middle", italic: true });
  return s;
}
function devPin(x, y, name) {
  return text(x + 8, y + 3.5, name, { size: 9.5, color: C.ink, bold: true });
}

// The always-present OLED, top-right. Returns its pin coordinates.
let OLED_PINS;
function drawOLED() {
  const x = DEV_X, y = 116, w = DEV_W, h = 96;
  let s = deviceBox(x, y, w, h, "OLED", "0x3C", C.blue);
  const p = {
    VCC: { x, y: y + 40 }, GND: { x, y: y + 56 },
    SDA: { x, y: y + 72 }, SCL: { x, y: y + 88 },
  };
  s += devPin(x, p.VCC.y, "VCC") + devPin(x, p.GND.y, "GND")
    + devPin(x, p.SDA.y, "SDA") + devPin(x, p.SCL.y, "SCL");
  OLED_PINS = p;
  return s;
}

// ---- diagram assembly ----------------------------------------------
function diagram(title, sub, usedPins, bodyFn, legend) {
  reset(usedPins);
  const body = drawOLED() + bodyFn();   // side effects: RAIL_MAXY, OLED_PINS, lanes
  let inner = drawPico() + drawRails() + body + drawPinNumbers();
  let head = text(40, 36, title, { size: 22, color: C.navy, bold: true })
    + text(40, 55, sub, { size: 12.5, color: C.gray });
  const lx = 648, ly = 128;
  let leg = `<rect x="${lx - 14}" y="${ly - 24}" width="378" height="${30 + legend.length * 23}" rx="9"`
    + ` fill="#FFFFFF" stroke="#E1E8EF" stroke-width="1.5"/>`;
  leg += text(lx, ly - 6, "Connections", { size: 13, color: C.navy, bold: true });
  legend.forEach((r, i) => {
    const yy = ly + 18 + i * 23;
    if (!r.color) {   // text-only row (e.g. resistor band names)
      leg += text(lx, yy, r.text, { size: 11, color: C.ink });
      return;
    }
    if (CASED().includes(r.color)) {
      leg += `<line x1="${lx}" y1="${yy - 4}" x2="${lx + 26}" y2="${yy - 4}" stroke="${CASING}" stroke-width="6.6" stroke-linecap="round"/>`;
    }
    leg += `<line x1="${lx}" y1="${yy - 4}" x2="${lx + 26}" y2="${yy - 4}" stroke="${r.color}" stroke-width="4" stroke-linecap="round"/>`;
    leg += text(lx + 34, yy, r.text, { size: 11.5, color: C.ink });
  });
  let foot = text(40, 676, "Maker Lab Kids  ·  Pico 2 W  ·  numbers outside the board are physical header pins", { size: 10.5, color: C.gray })
    + text(1000, 676, "MakerLabKids.com", { size: 10.5, color: C.blue, anchor: "end", bold: true });
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1040 700" font-family="Arial, Helvetica, sans-serif">`
    + `<rect width="1040" height="700" fill="#FFFFFF"/>` + head + inner + leg + foot + `</svg>`;
}

// I2C body: OLED + sensor share SDA/SCL and the rails
function bodyI2C(title, addr, accent) {
  const x = DEV_X, y = 258, w = DEV_W, h = 96;
  let s = deviceBox(x, y, w, h, title, addr, accent);
  const p = {
    VCC: { x, y: y + 40 }, GND: { x, y: y + 56 },
    SDA: { x, y: y + 72 }, SCL: { x, y: y + 88 },
  };
  s += devPin(x, p.VCC.y, "VCC") + devPin(x, p.GND.y, "GND")
    + devPin(x, p.SDA.y, "SDA") + devPin(x, p.SCL.y, "SCL");
  s += tap(RAIL_PWR, OLED_PINS.VCC, W.pwr) + tap(RAIL_GND, OLED_PINS.GND, W.gnd);
  s += tap(RAIL_PWR, p.VCC, W.pwr) + tap(RAIL_GND, p.GND, W.gnd);
  s += bus(1, [OLED_PINS.SDA, p.SDA], W.sda);
  s += bus(2, [OLED_PINS.SCL, p.SCL], W.scl);
  return s;
}
// OLED-only I2C plumbing (for analog projects)
function oledI2C() {
  let s = tap(RAIL_PWR, OLED_PINS.VCC, W.pwr) + tap(RAIL_GND, OLED_PINS.GND, W.gnd);
  s += bus(1, [OLED_PINS.SDA], W.sda) + bus(2, [OLED_PINS.SCL], W.scl);
  return s;
}

const projects = {};
const i2cLegend = (pwrName) => [
  { color: W.pwr, text: `3V3 (pin 36) -> red rail -> each ${pwrName}` },
  { color: W.gnd, text: "GND (pin 38) -> black rail -> each GND" },
  { color: W.sda, text: "SDA: GP0 (pin 1) -> OLED + sensor" },
  { color: W.scl, text: "SCL: GP1 (pin 2) -> OLED + sensor" },
];

projects["display"] = () => diagram(
  "display wiring", "the OLED screen alone: the same four wires every I2C part shares",
  [1, 2, 36, 38], () => oledI2C(), [
    { color: W.pwr, text: "VCC -> 3V3 (pin 36) via the red rail" },
    { color: W.gnd, text: "GND -> GND (pin 38) via the black rail" },
    { color: W.sda, text: "SDA -> GP0 (pin 1)" },
    { color: W.scl, text: "SCL -> GP1 (pin 2)" },
    { text: "every sensor diagram starts from this" },
  ]);

projects["distance-station"] = () => diagram(
  "distance-station wiring", "VL53L0X laser distance + OLED on the shared I2C bus",
  [1, 2, 36, 38], () => bodyI2C("VL53L0X", "0x29", C.orange), i2cLegend("VIN"));

projects["distance-vl53l1x"] = () => diagram(
  "distance-vl53l1x wiring", "VL53L1X long-range distance + OLED on the shared I2C bus",
  [1, 2, 36, 38], () => bodyI2C("VL53L1X", "0x29", C.orange), i2cLegend("VIN"));

projects["bme280"] = () => diagram(
  "bme280 wiring", "BME280 temp / humidity / pressure + OLED on the shared I2C bus",
  [1, 2, 36, 38], () => bodyI2C("BME280", "0x76 / 0x77", C.green), i2cLegend("VCC"));

projects["light-lux"] = () => diagram(
  "light-lux wiring", "BH1750 lux sensor + OLED on the shared I2C bus",
  [1, 2, 36, 38], () => bodyI2C("BH1750", "0x23", C.yellow), i2cLegend("VCC"));

function analog(title, sub, adcPin, accent, outName) {
  const x = DEV_X, y = 262, w = DEV_W, h = 92;
  let s = deviceBox(x, y, w, h, title, sub, accent);
  const p = { VCC: { x, y: y + 42 }, GND: { x, y: y + 60 }, OUT: { x, y: y + 78 } };
  s += devPin(x, p.VCC.y, "VCC") + devPin(x, p.GND.y, "GND") + devPin(x, p.OUT.y, outName);
  s += oledI2C();
  s += tap(RAIL_PWR, p.VCC, W.pwr) + tap(RAIL_GND, p.GND, W.gnd);
  s += sig(adcPin, p.OUT, W.sig);
  return s;
}
projects["soil-moisture"] = () => diagram(
  "soil-moisture wiring", "Capacitive soil sensor (analog) + OLED",
  [1, 2, 31, 36, 38], () => analog("Soil moisture", "capacitive v1.2", 31, C.orange, "AOUT"),
  [
    { color: W.sig, text: "AOUT -> GP26 (pin 31, ADC0)" },
    { color: W.pwr, text: "3V3 (pin 36) -> VCC (OLED + sensor)" },
    { color: W.gnd, text: "GND (pin 38) -> GND (OLED + sensor)" },
    { color: W.sda, text: "OLED SDA/SCL on GP0 / GP1 (pins 1, 2)" },
  ]);
projects["sound"] = () => diagram(
  "sound wiring", "MAX9814 microphone amp (analog) + OLED",
  [1, 2, 32, 36, 38], () => analog("MAX9814", "GAIN floating = 60dB", 32, C.blue, "OUT"),
  [
    { color: W.sig, text: "OUT -> GP27 (pin 32, ADC1)" },
    { color: W.pwr, text: "3V3 (pin 36) -> VDD (OLED + sensor)" },
    { color: W.gnd, text: "GND (pin 38) -> GND (OLED + sensor)" },
    { color: W.sda, text: "OLED SDA/SCL on GP0 / GP1 (pins 1, 2)" },
  ]);

projects["light-basic"] = () => diagram(
  "light-basic wiring", "GL5528 photoresistor divider: 3V3 - LDR - GP28 - 10k - GND, + OLED",
  [1, 2, 34, 36, 38], () => {
    let s = oledI2C();
    const GX = DEV_X + 54, GW = 24;                 // divider column
    const ldrTop = 244, ldrH = 54, ldrBot = ldrTop + ldrH;
    const resTop = 320, resH = 54, resBot = resTop + resH;
    const junc = (ldrBot + resTop) / 2;             // the shared node = GP28 row

    // 3V3 rail -> top of the LDR
    s += tap(RAIL_PWR, { x: GX, y: ldrTop }, W.pwr);

    // the LDR (photoresistor): a body with a serpentine + light arrows
    s += `<rect x="${GX - GW / 2}" y="${ldrTop}" width="${GW}" height="${ldrH}" rx="4" fill="#E9D9B6" stroke="${C.ink}" stroke-width="1.3"/>`;
    s += `<path d="M${GX - 7} ${ldrTop + 12} h14 v9 h-14 v9 h14 v9 h-14" fill="none" stroke="${C.orange}" stroke-width="1.7"/>`;
    for (const yy of [ldrTop + 15, ldrTop + 33]) {   // two light rays pointing INTO the LDR
      const ex = GX + GW / 2 + 4, ey = yy, sx = ex + 23, sy = ey - 18;
      const dx = ex - sx, dy = ey - sy, L = Math.hypot(dx, dy);
      s += wire([[sx, sy], [ex, ey]], C.yellow, 2);
      // tip pokes ~3px past the line end so the line cannot blunt the point
      s += arrowhead(ex + dx / L * 3, ey + dy / L * 3, dx, dy, 9, C.yellow);
    }
    s += text(GX + GW / 2 + 40, ldrTop + 20, "GL5528", { size: 10.5, color: C.ink, bold: true });
    s += text(GX + GW / 2 + 40, ldrTop + 33, "LDR", { size: 10.5, color: C.ink, bold: true });

    // LDR bottom -> junction -> 10k top (one vertical wire)
    s += wire([[GX, ldrBot], [GX, resTop]], C.ink, 2.5);
    s += dot(GX, junc, W.sig);
    // junction taps out to GP28 (the ADC reads this node)
    s += sig(34, { x: GX, y: junc }, W.sig);
    s += text(GX + 12, junc - 5, "junction = the GP28 row", { size: 9.5, color: C.ink, italic: true });

    // the 10k, with real color bands
    s += resistorGlyph(GX - GW / 2, resTop, GW, resH, 10000, true);
    s += text(GX + GW / 2 + 8, resTop + resH / 2 + 3, "10k", { size: 10.5, color: C.ink, bold: true });

    // 10k bottom -> GND rail
    s += tap(RAIL_GND, { x: GX, y: resBot }, W.gnd);
    return s;
  },
  [
    { color: W.pwr, text: "3V3 (pin 36) -> top of the LDR" },
    { color: W.sig, text: "LDR/10k junction -> GP28 (pin 34, ADC2)" },
    { color: W.gnd, text: "GND (pin 38) -> bottom of the 10k" },
    { text: "the junction is NOT a wire: it is just the" },
    { text: "breadboard row GP28 plugs into (LDR low" },
    { text: "leg + 10k high leg both land there)" },
    { color: W.sda, text: "OLED SDA/SCL on GP0 / GP1 (pins 1, 2)" },
    { text: "brighter light -> LDR drops -> GP28 rises" },
  ]);

// shared: the banded 4.7k pullup from a DATA line up to the 3V3 rail
function pullup47(ry) {
  const rx = RAIL_GND + 34;
  let s = resistorGlyph(rx, ry - 26, 13, 32, 4700, true);
  s += text(rx + 6, ry - 30, "4.7k", { size: 9, color: C.ink, anchor: "middle", bold: true });
  s += wire([[RAIL_PWR, ry - 18], [rx + 6, ry - 18], [rx + 6, ry - 26]], W.pwr, 2.5);
  s += wire([[rx + 6, ry + 6], [rx + 6, ry], [DEV_X - 8, ry]], W.sda, 2.5);
  return s;
}
function ds18b20Box(y, title) {
  const x = DEV_X, w = DEV_W, h = 66;
  let s = deviceBox(x, y, w, h, title, "", C.orange);
  const p = { VCC: { x, y: y + 34 }, GND: { x, y: y + 48 }, DATA: { x, y: y + 62 } };
  s += devPin(x, p.VCC.y, "red 3V3") + devPin(x, p.GND.y, "blk GND") + devPin(x, p.DATA.y, "grn DATA");
  return { s, p };
}

projects["soil-temperature"] = () => diagram(
  "soil-temperature wiring", "DS18B20 waterproof probe(s) + OLED  ·  needs a 4.7k pullup",
  [1, 2, 29, 36, 38], () => {
    const x = DEV_X, y = 262, w = DEV_W, h = 92;
    let s = deviceBox(x, y, w, h, "DS18B20", "one or many on one wire", C.orange);
    const p = { VCC: { x, y: y + 42 }, GND: { x, y: y + 60 }, DATA: { x, y: y + 78 } };
    s += devPin(x, p.VCC.y, "red 3V3") + devPin(x, p.GND.y, "black GND") + devPin(x, p.DATA.y, "green DATA");
    s += oledI2C();
    s += tap(RAIL_PWR, p.VCC, W.pwr) + tap(RAIL_GND, p.GND, W.gnd);
    s += sig(29, p.DATA, W.sda);
    s += pullup47(y + 78);
    return s;
  },
  [
    { color: W.sda, text: "green DATA -> GP22 (pin 29)" },
    { color: W.pwr, text: "red -> 3V3 (pin 36);  4.7k: DATA -> 3V3" },
    { color: W.gnd, text: "black -> GND (pin 38)" },
    { color: W.sda, text: "OLED SDA/SCL on GP0 / GP1 (pins 1, 2)" },
    { text: "4.7k bands: yellow violet red gold" },
    { text: "  (1% 5-band: yellow violet black brown brown)" },
  ]);

projects["soil-temperature-multi"] = () => diagram(
  "many DS18B20 probes, one wire", "three shown, dozens possible  ·  STILL just one 4.7k pullup",
  [1, 2, 29, 36, 38], () => {
    let s = oledI2C();
    const boxes = [ds18b20Box(238, "DS18B20 probe 1"),
                   ds18b20Box(330, "DS18B20 probe 2"),
                   ds18b20Box(422, "DS18B20 probe 3")];
    boxes.forEach(b => { s += b.s; });
    // power + ground: every probe taps the same rails
    boxes.forEach(b => { s += tap(RAIL_PWR, b.p.VCC, W.pwr) + tap(RAIL_GND, b.p.GND, W.gnd); });
    // ONE data lane from GP22 feeds every probe's DATA pin
    s += bus(29, boxes.map(b => b.p.DATA), W.sda);
    // and ONE pullup for the whole bus
    s += pullup47(boxes[0].p.DATA.y);
    s += text(DEV_X + DEV_W / 2, 520, "probe 4, 5, 6... same three wires. No new resistor.",
      { size: 11.5, color: C.gray, anchor: "middle", italic: true });
    return s;
  },
  [
    { color: W.sda, text: "ONE green DATA bus -> GP22 (pin 29), all probes" },
    { color: W.pwr, text: "ONE 4.7k pullup TOTAL: DATA -> 3V3" },
    { color: W.gnd, text: "all reds to 3V3 rail, all blacks to GND rail" },
    { text: "each probe has a factory serial number, so the" },
    { text: "code tells them apart automatically (and you can" },
    { text: "label + position each one on the dashboard)" },
    { text: "4.7k bands: yellow violet red gold" },
  ]);

projects["bme280-multi"] = () => diagram(
  "two BME280s on one bus", "inside the bin + outside the bin  ·  the SDO pad picks the address",
  [1, 2, 36, 38], () => {
    let s = "";
    const mk = (y, title, addr, note) => {
      const x = DEV_X, w = DEV_W, h = 96;
      let d = deviceBox(x, y, w, h, title, addr, C.green);
      const p = { VCC: { x, y: y + 40 }, GND: { x, y: y + 56 },
                  SDA: { x, y: y + 72 }, SCL: { x, y: y + 88 } };
      d += devPin(x, p.VCC.y, "VCC") + devPin(x, p.GND.y, "GND")
        + devPin(x, p.SDA.y, "SDA") + devPin(x, p.SCL.y, "SCL");
      d += text(x + w + 8, y + 50, note, { size: 10.5, color: C.orange, bold: true });
      return { d, p };
    };
    const a = mk(250, "BME280  IN", "0x76", "SDO -> GND");
    const b = mk(392, "BME280  OUT", "0x77", "SDO -> 3V3");
    s += a.d + b.d;
    s += tap(RAIL_PWR, OLED_PINS.VCC, W.pwr) + tap(RAIL_GND, OLED_PINS.GND, W.gnd);
    [a, b].forEach(m => { s += tap(RAIL_PWR, m.p.VCC, W.pwr) + tap(RAIL_GND, m.p.GND, W.gnd); });
    s += bus(1, [OLED_PINS.SDA, a.p.SDA, b.p.SDA], W.sda);
    s += bus(2, [OLED_PINS.SCL, a.p.SCL, b.p.SCL], W.scl);
    return s;
  },
  [
    { color: W.sda, text: "SDA: GP0 (pin 1) -> OLED + both sensors" },
    { color: W.scl, text: "SCL: GP1 (pin 2) -> OLED + both sensors" },
    { color: W.pwr, text: "3V3 + GND rails feed everything" },
    { text: "the SDO pad sets the address: GND = 0x76," },
    { text: "3V3 = 0x77. Two addresses = max two per bus." },
  ]);

projects["soil-moisture-multi"] = () => diagram(
  "many moisture probes via ADS1115", "the I2C chip that adds 4 analog inputs  ·  two probes shown",
  [1, 2, 36, 38], () => {
    let s = oledI2C();
    // ADS1115 on the I2C bus
    const ax = DEV_X, ay = 236, aw = DEV_W, ah = 118;
    s += deviceBox(ax, ay, aw, ah, "ADS1115", "0x48 (ADDR->GND)", C.blue);
    const ap = { VDD: { x: ax, y: ay + 36 }, GND: { x: ax, y: ay + 50 },
                 SDA: { x: ax, y: ay + 64 }, SCL: { x: ax, y: ay + 78 },
                 A0: { x: ax, y: ay + 96 }, A1: { x: ax, y: ay + 112 } };
    s += devPin(ax, ap.VDD.y, "VDD") + devPin(ax, ap.GND.y, "GND")
      + devPin(ax, ap.SDA.y, "SDA") + devPin(ax, ap.SCL.y, "SCL")
      + devPin(ax, ap.A0.y, "A0") + devPin(ax, ap.A1.y, "A1");
    s += tap(RAIL_PWR, ap.VDD, W.pwr) + tap(RAIL_GND, ap.GND, W.gnd);
    s += bus(1, [OLED_PINS.SDA, ap.SDA], W.sda);
    s += bus(2, [OLED_PINS.SCL, ap.SCL], W.scl);
    // two moisture probes feeding A0 / A1
    const mk = (y, title) => {
      const h = 64;
      let d = deviceBox(DEV_X, y, DEV_W, h, title, "", C.orange);
      const p = { VCC: { x: DEV_X, y: y + 34 }, GND: { x: DEV_X, y: y + 47 },
                  OUT: { x: DEV_X, y: y + 60 } };
      d += devPin(DEV_X, p.VCC.y, "VCC") + devPin(DEV_X, p.GND.y, "GND") + devPin(DEV_X, p.OUT.y, "AOUT");
      return { d, p };
    };
    const m1 = mk(384, "moisture probe 1");
    const m2 = mk(472, "moisture probe 2");
    s += m1.d + m2.d;
    [m1, m2].forEach(m => { s += tap(RAIL_PWR, m.p.VCC, W.pwr) + tap(RAIL_GND, m.p.GND, W.gnd); });
    // AOUT -> A0/A1: short lane just left of the device column
    const lane = DEV_X - 22;
    s += wire([[DEV_X - 8, m1.p.OUT.y], [lane, m1.p.OUT.y], [lane, ap.A0.y], [DEV_X - 8, ap.A0.y]], W.sig, 2.5);
    const lane2 = DEV_X - 34;
    s += wire([[DEV_X - 8, m2.p.OUT.y], [lane2, m2.p.OUT.y], [lane2, ap.A1.y], [DEV_X - 8, ap.A1.y]], W.sig, 2.5);
    return s;
  },
  [
    { color: W.sig, text: "probe 1 AOUT -> A0, probe 2 AOUT -> A1" },
    { color: W.sda, text: "ADS1115 rides the same I2C bus as the OLED" },
    { color: W.pwr, text: "3V3 + GND rails feed everything" },
    { text: "A2 and A3 are still free (light divider, more" },
    { text: "probes); a second ADS1115 at 0x49 adds 4 more" },
  ]);

projects["servo"] = () => diagram(
  "servo wiring", "SG90 servo (web-driven) + OLED  ·  optional GL5528 for follow-light",
  [1, 2, 21, 34, 36, 38, 40], () => {
    const x = DEV_X, y = 244, w = DEV_W, h = 92;
    let s = deviceBox(x, y, w, h, "SG90 servo", "power from VBUS 5V", C.green);
    const p = { SIG: { x, y: y + 42 }, PWR: { x, y: y + 60 }, GND: { x, y: y + 78 } };
    s += devPin(x, p.SIG.y, "orange SIG") + devPin(x, p.PWR.y, "red +5V") + devPin(x, p.GND.y, "brown GND");
    s += oledI2C();
    s += sig(21, p.SIG, W.sig);
    s += sig(40, p.PWR, W.vbus);   // VBUS, deliberately NOT the 3V3 rail
    s += tap(RAIL_GND, p.GND, W.gnd);
    // optional LDR (dashed) below
    const ly = 378, lh = 96;
    let d = deviceBox(x, ly, w, lh, "GL5528 (optional)", "follow-light mode", C.gray, true);
    const q = { TOP: { x, y: ly + 44 }, MID: { x, y: ly + 66 }, BOT: { x, y: ly + 86 } };
    d += devPin(x, q.TOP.y, "LDR->3V3") + devPin(x, q.MID.y, "junction") + devPin(x, q.BOT.y, "10k->GND");
    d += tap(RAIL_PWR, q.TOP, W.pwr);
    d += sig(34, q.MID, W.sig);
    d += tap(RAIL_GND, q.BOT, W.gnd);
    return s + d;
  },
  [
    { color: W.sig, text: "SIG (servo orange lead) -> GP16 (pin 21)" },
    { color: W.vbus, text: "+5V (servo red lead) -> VBUS (pin 40) NOT 3V3!" },
    { color: W.gnd, text: "GND (servo brown lead) -> GND (pin 38)" },
    { color: W.sig, text: "optional LDR junction -> GP28 (pin 34)" },
  ]);

projects["speaker"] = () => diagram(
  "speaker wiring", "LM386 amp + speaker, PWM tone from the Pico + OLED",
  [1, 2, 24, 36, 38, 40], () => {
    const x = DEV_X, y = 250, w = DEV_W, h = 92;
    let s = deviceBox(x, y, w, h, "LM386 amp", "power from VBUS 5V", C.blue);
    const p = { IN: { x, y: y + 42 }, VCC: { x, y: y + 60 }, GND: { x, y: y + 78 } };
    s += devPin(x, p.IN.y, "yel IN") + devPin(x, p.VCC.y, "red +5V") + devPin(x, p.GND.y, "blk GND");
    s += oledI2C();
    s += sig(24, p.IN, W.sig);       // GP18 = pin 24: the PWM tone (a signal)
    s += sig(40, p.VCC, W.vbus);     // VBUS 5V, deliberately not 3V3
    s += tap(RAIL_GND, p.GND, W.gnd);
    // speaker to the right of the amp
    const sx = x + w + 66, sy = y + 26;
    s += `<rect x="${sx}" y="${sy}" width="42" height="42" rx="6" fill="#334155" stroke="#1e293b" stroke-width="1.5"/>`;
    s += `<circle cx="${sx + 21}" cy="${sy + 21}" r="13" fill="#0f172a" stroke="#64748b"/>`;
    s += text(sx + 21, sy + 60, "speaker", { size: 10, color: C.gray, anchor: "middle" });
    s += wire([[x + w, y + 50], [sx, sy + 14]], C.ink, 2);
    s += wire([[x + w, y + 66], [sx, sy + 30]], W.gnd, 2);
    return s;
  },
  [
    { color: W.sig, text: "IN <- GP18 (pin 24): the PWM tone" },
    { color: W.vbus, text: "+5V (amp VCC) -> VBUS (pin 40), NOT 3V3" },
    { color: W.gnd, text: "GND (amp) -> GND (pin 38), shared" },
    { text: "amp OUT+ / OUT- -> the speaker terminals" },
    { text: "turn the amp's volume pot DOWN to start" },
  ]);

projects["vibration"] = () => diagram(
  "vibration wiring", "vibrating motor via a transistor switch + OLED",
  [1, 2, 25, 36, 38], () => {
    const x = DEV_X, y = 250, w = DEV_W, h = 96;
    let s = deviceBox(x, y, w, h, "motor driver", "2N2222 + diode, or kit module", C.orange);
    const p = { SIG: { x, y: y + 44 }, PWR: { x, y: y + 64 }, GND: { x, y: y + 84 } };
    s += devPin(x, p.SIG.y, "yel S") + devPin(x, p.PWR.y, "red +3V3") + devPin(x, p.GND.y, "blk GND");
    s += oledI2C();
    s += sig(25, p.SIG, W.sig);       // GP19 = pin 25 -> base via 1k
    s += tap(RAIL_PWR, p.PWR, W.pwr);
    s += tap(RAIL_GND, p.GND, W.gnd);
    // motor glyph to the right
    const mx = x + w + 70, my = y + 34;
    s += `<circle cx="${mx + 18}" cy="${my + 18}" r="18" fill="#334155" stroke="#1e293b" stroke-width="1.5"/>`;
    s += text(mx + 18, my + 24, "M", { size: 17, color: "#e2e8f0", anchor: "middle", bold: true });
    s += text(mx + 18, my + 54, "motor", { size: 10, color: C.gray, anchor: "middle" });
    s += wire([[x + w, y + 58], [mx, my + 10]], W.pwr, 2);
    s += wire([[x + w, y + 74], [mx, my + 26]], C.ink, 2);
    return s;
  },
  [
    { color: W.sig, text: "S (base via 1k) <- GP19 (pin 25)" },
    { color: W.pwr, text: "motor + -> 3V3 (pin 36)" },
    { color: W.gnd, text: "transistor emitter -> GND (pin 38)" },
    { text: "flyback diode ACROSS the motor (band to +3V3)" },
    { text: "no diode = dead transistor; or use a kit module" },
  ]);

const names = Object.keys(projects);
for (const name of names) {
  const svg = projects[name]();
  fs.writeFileSync(path.join(OUT, name + ".svg"), svg);
  console.log("wrote docs/wiring/" + name + ".svg (" + svg.length + " bytes)");
}
console.log("done:", names.length, "diagrams");
