import { chromium } from "playwright";
const url = process.argv[2];
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
const errors = []; p.on("pageerror", e => errors.push(String(e))); p.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
await p.goto(url, { waitUntil: "load" });
await p.waitForFunction(() => /LIVE|SIMULATED/.test(document.getElementById("src").textContent), null, { timeout: 20000 });
const badge = await p.textContent("#src");
const tiles = await p.$$eval("#deckgrid .tile", els => els.map(e => e.innerText.replace(/\s+/g, " ").trim()));
const opts = await p.$$eval("#clsSel option", els => els.map(e => e.textContent));
console.log("badge:", badge); console.log("period options:", opts.join(" | ")); console.log("deck tiles:", tiles.length); tiles.slice(0, 3).forEach(t => console.log("  ", t));
for (const v of ["bin", "board", "net", "paper", "orbital", "garden"]) { await p.click(`#rail button[data-v="${v}"]`); await p.waitForTimeout(500); }
console.log("leaderboard rows:", (await p.$$eval("#rows .rrow", els => els.map(e => e.innerText.replace(/\s+/g, " ").trim()))).slice(0, 2));
console.log("headline:", await p.textContent("#phead")); console.log("orbital tag:", await p.textContent("#orbtag"));
await p.click("#simbtn"); await p.waitForTimeout(800); console.log("after SIM:", await p.textContent("#src"), "| tiles:", (await p.$$("#deckgrid .tile")).length);
await p.click("#simbtn"); await p.waitForFunction(() => /LIVE/.test(document.getElementById("src").textContent), null, { timeout: 20000 }); console.log("back to:", await p.textContent("#src"));
await p.screenshot({ path: process.argv[3], fullPage: false });
console.log("page errors:", errors.length ? errors : "none");
await b.close();
