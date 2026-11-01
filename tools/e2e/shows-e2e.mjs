import { chromium } from 'playwright';
import crypto from 'crypto';
import fs from 'fs';
import os from 'os';
import path from 'path';
const W = 'http://127.0.0.1:8787', B = 'http://127.0.0.1:8214', UID = 'e66100000000cafe';
let fails = 0;
const ok = (name, cond, info = '') => { console.log((cond ? 'PASS ' : 'FAIL ') + name + (info ? '  (' + info + ')' : '')); if (!cond) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const push = async (extra = {}) => (await fetch(B + '/ingest', { method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ id: UID, name: 'Show Bin', ip: '192.168.81.130', in_temp_c: 21, bin: { team: 'Show Bin', period: 1, bin: 30, room: 1 }, ...extra }) })).json();
async function until(f, ms = 30000) { const end = Date.now() + ms; while (Date.now() < end) { const v = await f(); if (v) return v; await sleep(500); } return null; }

// the show file: 3 frames, 128x64
const pbm = Buffer.concat([0x00, 0xff, 0x0f].map((b, i) => Buffer.concat([Buffer.from('P4\n' + (i ? '' : '# fps 5\n') + '128 64\n'), Buffer.alloc(1024, b)])));
const sha = crypto.createHash('sha256').update(pbm).digest('hex');
const file = path.join(os.tmpdir(), 'wiggle.pbm'); fs.writeFileSync(file, pbm);

let r = await fetch(W + '/api/admin/bootstrap', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: 'quincy', password: 'password123', bootstrap: 'bootstrap-me' }) });
ok('bootstrap admin', r.ok || r.status === 409 || r.status === 403, 'status ' + r.status);
const p0 = await push({ shows_rev: 0 });
ok('the bin pushes; nothing for it yet', p0.ok && !p0.shows);
ok('the Surface hears the bin', !!(await until(async () => { const j = await (await fetch(W + '/api/public/now')).json().catch(() => ({})); return JSON.stringify(j).includes(UID); }, 75000)));   // /api/public/now is cached

const browser = await chromium.launch(); const page = await browser.newPage(); const errs = [];
page.on('pageerror', (e) => errs.push(String(e)));
await page.goto(W + '/'); await page.waitForTimeout(1000);
await page.click('#staff'); await page.fill('#sn', 'quincy'); await page.fill('#pp', 'password123'); await page.click('#lf button[type=submit]');
await page.waitForTimeout(1500);
await page.goto(W + '/bin/' + UID); await page.waitForSelector('.showcard .sh-files', { timeout: 15000 });
ok('the bin page has a Shows card', await page.isVisible('.showcard'));
await page.setInputFiles('.showcard input[type=file]', file);
ok('the name comes from the file', (await page.inputValue('.showcard input[type=text]')) === 'wiggle');
await page.click('.showcard [data-add]');
await page.waitForSelector('.showcard .sh-row:has-text("wiggle")', { timeout: 10000 });
ok('uploaded: listed as 3 frames', (await page.textContent('.showcard .sh-files')).includes('3 frames'));
ok('it says on its way', (await page.textContent('.showcard .sh-state')).includes('On its way'));
await page.click('.showcard [data-pick]');
// keep only wiggle and Wormhole, Wormhole first
const names = await page.$$eval('.showcard [data-on]', (cs) => cs.map((c) => c.getAttribute('data-on')));
for (const n of names) if (n !== 'wiggle' && n !== 'Wormhole') await page.uncheck(`.showcard [data-on="${n}"]`);   // each untick redraws the list
await page.click('.showcard [data-up="Wormhole"]');
await page.click('.showcard [data-save]');
await page.waitForTimeout(1000);
const api = await page.evaluate(async (u) => (await fetch('/api/shows?uid=' + u)).json(), UID);
ok('the playlist saved in order', JSON.stringify(api.list) === '["Wormhole","wiggle"]', JSON.stringify(api.list));

// the Burrow's next cloud pass fetches the file; the bin's next push gets the shows
const rep = await until(async () => { const j = await push({ shows_rev: 0 }); return j.shows ? j : null; });
ok('the push reply carries the shows', !!rep && rep.shows.rev === api.rev && JSON.stringify(rep.shows.list) === '["Wormhole","wiggle"]', rep && JSON.stringify(rep.shows));
ok('with the file by sha256', !!rep && rep.shows.files[0].sha256 === sha);
const got = Buffer.from(await (await fetch(B + '/shows/' + sha + '.pbm')).arrayBuffer());
ok('the bin can fetch it from the Burrow, byte for byte', got.equals(pbm), got.length + ' bytes');

// the bin reports the rev: the page flips to "On the bin"
const rev = rep ? rep.shows.rev : -1;
await push({ shows_rev: rev });
ok('no more shows in the reply once the bin has them', !(await push({ shows_rev: rev })).shows);
const onb = await until(async () => (await page.evaluate(async (u) => (await fetch('/api/shows?uid=' + u)).json(), UID)).on_board, 30000);
ok('the Surface sees the board has them', !!onb);
await page.reload(); await page.waitForSelector('.showcard .sh-state', { timeout: 15000 }); await page.waitForTimeout(800);
ok('the page says On the bin', (await page.textContent('.showcard .sh-state')).includes('On the bin'));
fs.mkdirSync(process.env.SHOTS || 'shots', { recursive: true });
await (await page.$('.showcard')).screenshot({ path: path.join(process.env.SHOTS || 'shots', 'shows-card.png') });
ok('no browser errors', errs.length === 0, errs.join(' | '));
await browser.close();
console.log(fails ? fails + ' FAILED' : 'ALL PASS');
process.exit(fails ? 1 : 0);
