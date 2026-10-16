// End-to-end: real Worker (wrangler dev :8787, local D1/R2) + real Burrow (:8213) + simbins + the dashboard.
import { chromium } from 'playwright';
const W = 'http://127.0.0.1:8787', B = 'http://127.0.0.1:8213';
const SHOTS = new URL('./shots/', import.meta.url).pathname;
import fs from 'node:fs'; fs.mkdirSync(SHOTS, { recursive: true });
const results = []; const ok = (n, c, extra='') => { results.push([n, !!c]); console.log((c ? 'PASS ' : 'FAIL ') + n + (extra ? '  ' + extra : '')); };
const j = async (r) => { try { return await r.json(); } catch { return null; } };

// ---- API level: bootstrap, teams, login -------------------------------------
let r = await fetch(W + '/api/admin/bootstrap', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: 'quincy', password: 'password123', bootstrap: 'bootstrap-me' }) });
ok('bootstrap admin', r.ok || r.status === 409 || r.status === 403, 'status ' + r.status);
r = await fetch(W + '/api/login', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ name: 'quincy', passphrase: 'password123' }) });
const cookie = (r.headers.get('set-cookie') || '').split(';')[0];
ok('admin login by name', r.ok && cookie.startsWith('wh_session='), 'status ' + r.status);
const H = { cookie, 'content-type': 'application/json' };
r = await fetch(W + '/api/admin/teams/import', { method: 'POST', headers: { cookie, 'content-type': 'text/csv' }, body: 'team,period,bin,room\nDirt Vader,1,1,1\nCompost Malone,1,2,1\nWorm Rangers,1,3,1\n' });
const imp = await j(r); const teams = imp?.teams || imp?.created || imp; const t0 = Array.isArray(teams) ? teams[0] : null;
ok('CSV import returns passphrases', t0 && (t0.passphrase || (t0.team && t0.passphrase)), JSON.stringify(imp).slice(0, 160));
const pass = t0?.passphrase; const teamName = t0?.team?.name || t0?.name;
r = await fetch(W + '/api/teams'); const tl = await j(r);
ok('/api/teams lists students only', Array.isArray(tl) && tl.length === 3 && !tl.find(t => t.name === 'quincy'));
const tid = tl.find(t => t.name === teamName)?.id;
r = await fetch(W + '/api/login', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ team_id: tid, passphrase: pass, first_name: 'Ada' }) });
const scookie = (r.headers.get('set-cookie') || '').split(';')[0];
ok('student login with passphrase', r.ok && scookie.startsWith('wh_session='), 'status ' + r.status);
// wait for the Burrow to snapshot + seal + upload at least one casting
console.log('waiting ~75 s for castings to seal and upload...');
await new Promise(res => setTimeout(res, 75000));
r = await fetch(B + '/api/status'); const st = await j(r);
ok('Burrow reached the Worker', st?.cloud?.reachable === true, JSON.stringify(st?.cloud).slice(0, 200));
ok('a casting got verified by read-back', (st?.store?.castings || 0) >= 1 && (st?.store?.unverified || 0) < (st?.store?.castings || 0), 'castings ' + st?.store?.castings + ' unverified ' + st?.store?.unverified);
r = await fetch(W + '/api/now', { headers: { cookie: scookie } }); const nowj = await j(r);
ok('Surface /api/now merges the snapshot', nowj && nowj.bins && Object.keys(nowj.bins).length >= 12 && nowj.edges && nowj.edges.burrow1, 'bins ' + (nowj && Object.keys(nowj.bins || {}).length));
const uid = Object.keys(nowj?.bins || {})[0];
r = await fetch(W + `/api/history?uid=${uid}&from=${Math.floor(Date.now()/1000)-3600}&to=${Math.floor(Date.now()/1000)}`, { headers: { cookie: scookie } }); const hist = await j(r);
ok('Surface /api/history has rollup points', hist && hist.points && hist.points.length >= 1, 'points ' + hist?.points?.length + ' step ' + hist?.step);
r = await fetch(W + '/api/now'); ok('anonymous /api/now is 401', r.status === 401);
r = await fetch(W + '/api/logout', { method: 'POST', headers: { cookie: scookie, 'content-type': 'application/json' }, body: '{}' }); ok('logout accepts JSON body', r.ok);

// ---- browser level ----------------------------------------------------------
const browser = await chromium.launch(); const errors = [];
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
page.on('pageerror', e => errors.push('pageerror: ' + e.message)); page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
page.on('requestfailed', rq => errors.push('reqfail: ' + rq.url()));
await page.goto(W + '/bin/' + uid); await page.waitForTimeout(1500);
ok('deep link while anonymous shows login and keeps URL', (await page.locator('#lf').count()) === 1 && page.url().endsWith('/bin/' + uid));
await page.screenshot({ path: SHOTS + '/login.png' });
await page.click('#staff'); await page.fill('#sn', 'quincy'); await page.fill('#pp', 'password123'); await page.click('#lf button[type=submit]');
await page.waitForTimeout(2500);
ok('staff login lands on the deep link', page.url().endsWith('/bin/' + uid) && (await page.locator('.chart-card').count()) >= 1, page.url());
await page.screenshot({ path: SHOTS + '/bin-after-staff-login.png', fullPage: true });
await page.goto(W + '/'); await page.waitForTimeout(2500);
const tiles = await page.locator('.tile').count(); ok('wall renders tiles from the Surface', tiles >= 12, 'tiles ' + tiles);
ok('header shows signed in', (await page.textContent('header')).includes('quincy'));
await page.screenshot({ path: SHOTS + '/wall-surface.png' });
for (const tab of ['edges', 'sessions', 'visits', 'teams', 'castings', 'stats']) {
  await page.goto(W + '/admin/' + tab); await page.waitForTimeout(2500);
  const txt = await page.textContent('main');
  const rows = await page.locator('main table tr').count();
  ok('admin tab ' + tab + ' renders', !/error|failed|could not/i.test(txt) && (rows >= 2 || tab === 'stats' || tab === 'castings'), 'rows ' + rows);
  await page.screenshot({ path: SHOTS + '/admin-' + tab + '.png', fullPage: true });
}
const stTxt = await page.goto(W + '/admin/castings').then(() => page.waitForTimeout(2500)).then(() => page.textContent('main'));
ok('castings tab lists a casting', /r1-\d{8}T\d{4}/.test(stTxt));
await page.goto(W + '/feed'); await page.waitForTimeout(12000);
const feedTxt = await page.textContent('main');
ok('feed receives live rows through the Worker /live proxy', /Dirt Vader|Compost|Worm/.test(feedTxt) && (await page.locator('main li, main .row, main .tick').count()) >= 1, feedTxt.slice(0, 120).replace(/\s+/g, ' '));
await page.screenshot({ path: SHOTS + '/feed-surface.png' });
// visits were recorded
r = await fetch(W + '/api/admin/visits', { headers: { cookie } }); const vis = await j(r);
ok('visits recorded page views', vis && (vis.visits || vis).length >= 3, 'n ' + (vis?.visits || vis)?.length);
// the Burrow-hosted copy still works with no login
await page.goto(B + '/'); await page.waitForTimeout(2000);
ok('Burrow-hosted wall needs no login', (await page.locator('.tile').count()) >= 12 && (await page.locator('#lf').count()) === 0);
await browser.close();
ok('no browser errors', errors.length === 0, errors.slice(0, 5).join(' | '));
const bad = results.filter(x => !x[1]); console.log(`\n${results.length} checks, ${bad.length} failed ${JSON.stringify(bad.map(x => x[0]))}`);
process.exit(bad.length ? 1 : 0);
