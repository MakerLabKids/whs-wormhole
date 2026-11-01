// Pico code over Wi-Fi, the whole chain: real Worker + real Burrow + a fake Bin + headless
// Chromium + real GitHub. Make a release from a pushed commit on the Devices page, Update one bin,
// the Burrow caches the files, the bin's push reply carries them, every file matches GitHub byte
// for byte (and boot.py is not among them), the bin reports the version: "up to date".
//   COMMIT=<a pushed commit> tools/e2e/code-e2e.sh
import { chromium } from 'playwright';
const W = 'http://127.0.0.1:8787', B = 'http://127.0.0.1:8214', UID = 'e66100000000c0de';
const COMMIT = process.env.COMMIT;
const V = COMMIT.slice(0, 7);
const RAW = 'https://raw.githubusercontent.com/MakerLabKids/whs-wormhole/' + COMMIT + '/';
let fails = 0;
const ok = (name, cond, info = '') => { console.log((cond ? 'PASS ' : 'FAIL ') + name + (info ? '  (' + info + ')' : '')); if (!cond) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const push = async (extra = {}) => (await fetch(B + '/ingest', { method: 'POST', headers: { 'content-type': 'application/json' },
  body: JSON.stringify({ id: UID, name: 'Code Bin', ip: '192.168.81.131', in_temp_c: 21, bin: { team: 'Code Bin', period: 1, bin: 31, room: 1 }, ...extra }) })).json();
async function until(f, ms = 60000) { const end = Date.now() + ms; while (Date.now() < end) { const v = await f(); if (v) return v; await sleep(1000); } return null; }

await fetch(W + '/api/admin/bootstrap', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: 'quincy', password: 'password123', bootstrap: 'bootstrap-me' }) });
ok('the bin pushes, nothing for it', !(await push({ code: 'old0000' })).code);
const browser = await chromium.launch();
const page = await browser.newPage();
const errs = [];
page.on('pageerror', (e) => errs.push(String(e)));
page.on('dialog', (d) => d.accept());
await page.goto(W + '/'); await page.waitForTimeout(800);
await page.click('#staff'); await page.fill('#sn', 'quincy'); await page.fill('#pp', 'password123'); await page.click('#lf button[type=submit]');
await page.waitForTimeout(1200);
const pico = () => page.evaluate(async () => (await fetch('/api/admin/pico')).json());
ok('the Surface lists the bin', !!(await until(async () => { await push({ code: 'old0000' }); return ((await pico()).bins || []).some((b) => b.uid === UID); })));
await page.goto(W + '/admin/edges'); await page.waitForSelector('#pico', { timeout: 20000 });
ok('the Devices page has the code panel', await page.isVisible('#pico'));
await page.fill('#pico-commit', COMMIT); await page.click('#pico-release');
await page.waitForSelector('#pico-version', { timeout: 60000 });
const rel = await pico();
ok('a release from GitHub', rel.releases[0] && rel.releases[0].version === V, JSON.stringify(rel.releases[0]));
await page.click('#pico [data-pico="' + UID + '"]');
await page.waitForTimeout(1000);
const rep = await until(async () => { const j = await push({ code: 'old0000' }); return j.code ? j : null; }, 90000);
ok('the push reply carries the update', !!rep && rep.code.version === V, rep && rep.code.files.length + ' files');
const paths = rep ? rep.code.files.map((f) => f.path) : [];
ok('code files only, never boot.py', paths.includes('main.py') && paths.includes('lib/ota.py') && !paths.includes('boot.py') && paths.every((p) => !p.endsWith('.json')), paths.join(' '));
const pkg = await (await fetch(RAW + 'projects/worm-bin/package.json')).json();
const srcOf = Object.fromEntries(pkg.urls.map((u) => [u[0].replace(/^fs:/, ''), u[1].replace(/^github:MakerLabKids\/whs-wormhole\//, '')]));
let same = 0;
for (const f of (rep ? rep.code.files : [])) {
  const mine = Buffer.from(await (await fetch(B + '/code/' + f.sha256)).arrayBuffer());
  const gh = Buffer.from(await (await fetch(RAW + srcOf[f.path])).arrayBuffer());
  if (mine.equals(gh)) same++; else console.log('  differs:', f.path);
}
ok('every file from the Burrow matches GitHub byte for byte', !!rep && same === rep.code.files.length, same + '/' + (rep ? rep.code.files.length : 0));
await push({ code: V });
ok('no update once the bin runs it', !(await push({ code: V })).code);
const upd = await until(async () => { const b = ((await pico()).bins || []).find((x) => x.uid === UID); return b && b.code === V; }, 60000);
await page.goto(W + '/admin/edges'); await page.waitForSelector('#pico', { timeout: 20000 }); await page.waitForTimeout(800);
ok('the page says up to date', !!upd && (await page.textContent('#pico')).includes('up to date'));
await (await page.$('#pico')).screenshot({ path: (process.env.SHOTS || 'shots') + '/pico-card.png' });
ok('no browser errors', errs.length === 0, errs.join(' | '));
await browser.close();
console.log(fails ? fails + ' FAILED' : 'ALL PASS');
process.exit(fails ? 1 : 0);
