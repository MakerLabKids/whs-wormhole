// Admin "people" screens against a local Worker: add a teacher, and a class from a CSV of student names and bins
// (one team per bin, a slip per student, student names never sent to the server).
import { chromium } from 'playwright';
const W = 'http://127.0.0.1:8787';
let fails = 0;
const ok = (name, cond, info = '') => { console.log((cond ? 'PASS ' : 'FAIL ') + name + (info ? '  (' + info + ')' : '')); if (!cond) fails++; };
const post = (path, body, cookie) => fetch(W + path, { method: 'POST', headers: { 'content-type': 'application/json', ...(cookie ? { cookie } : {}) }, body: JSON.stringify(body) });
const loginOk = async (body) => { const r = await post('/api/login', body); const j = await r.json().catch(() => ({})); return j.ok ? j.me.role : 'refused ' + r.status; };

let r = await post('/api/admin/bootstrap', { name: 'quincy', password: 'password123', bootstrap: 'bootstrap-me' });
ok('bootstrap admin', r.ok || r.status === 409, 'status ' + r.status);
// a team that already exists for bin 45: it must keep its passphrase unless asked
const lc = (await post('/api/login', { name: 'quincy', passphrase: 'password123' })).headers.get('set-cookie').split(';')[0];
const pre = await (await post('/api/admin/teams', { name: 'Night Crawlers', period: 2, bin: 45, room: 1 }, lc)).json();
ok('a team already has bin 45', pre.ok);

const browser = await chromium.launch(); const page = await browser.newPage(); const errs = [], sent = [];
page.on('pageerror', (e) => errs.push(String(e)));
page.on('request', (q) => { if (q.method() !== 'GET') sent.push(q.url() + ' ' + (q.postData() || '')); });
await page.addInitScript(() => { window.print = () => { window.__printed = (window.__printed || 0) + 1; }; });
await page.goto(W + '/login'); await page.waitForTimeout(800);
await page.click('#staff'); await page.fill('#sn', 'quincy'); await page.fill('#pp', 'password123'); await page.click('#lf button[type=submit]');
await page.waitForTimeout(1200);
await page.goto(W + '/admin/teams'); await page.waitForSelector('#newstaff', { timeout: 15000 });

// 1. a teacher
await page.fill('#sn2', 'Mrs. Example'); await page.selectOption('#srole', 'teacher'); await page.click('#newstaff button[type=submit]');
await page.waitForSelector('#passtext', { timeout: 10000 });
const tpass = (await page.textContent('#passtext')).trim().split('\t').pop();
ok('the new teacher signs in as a teacher', (await loginOk({ name: 'Mrs. Example', passphrase: tpass })) === 'teacher', tpass);

// 2. a class from a CSV: header, quotes, two new bins and the existing bin 45
const csv = 'student,bin,period,room\n"Lovelace, Ada",38,3,1\nGrace Hopper,38,3,1\nAlan Turing,46,3,2\nKatherine Johnson,45\nno bin here\n';
await page.fill('#classcsv', csv); await page.click('#classgo');
await page.waitForSelector('#classmake', { timeout: 5000 });
const prev = await page.textContent('#classout');
ok('preview: bins 38, 45, 46', /38[\s\S]*Bin 38[\s\S]*45[\s\S]*Night Crawlers[\s\S]*keeps its passphrase[\s\S]*46/.test(prev), prev.slice(0, 160));
ok('preview flags the bad line', /Skipped line\(s\) 5/.test(prev));
await page.click('#classmake');
await page.waitForSelector('#cards-print .slip', { timeout: 15000 });
const slips = await page.$$eval('#cards-print .slip', (els) => els.map((e) => ({ who: e.querySelector('.who').textContent, m: e.querySelector('.m').textContent, p: e.querySelector('.p').textContent })));
ok('one slip per student', slips.length === 4, slips.length);
ok('the print dialog opened', (await page.evaluate(() => window.__printed)) >= 1);
const ada = slips.find((s) => s.who === 'Lovelace, Ada'), grace = slips.find((s) => s.who === 'Grace Hopper');
ok('students in one bin share a passphrase', ada && grace && ada.p === grace.p && /^[a-z]+-[a-z]+-[a-z]+$/.test(ada.p), ada && ada.p);
const teams = await (await fetch(W + '/api/teams')).json();
const t38 = (teams.teams || teams).find((t) => t.name === 'Bin 38');
ok('Bin 38 is a team in period 3', !!t38 && t38.period === 3, JSON.stringify(t38));
ok('Bin 38 login works', (await loginOk({ team_id: t38.id, passphrase: ada.p, first_name: 'Ada' })) === 'team');
const kj = slips.find((s) => s.who === 'Katherine Johnson');
ok('the existing bin keeps its passphrase', kj && /current passphrase/.test(kj.p) && /Night Crawlers/.test(kj.m), kj && kj.p);
ok('the existing team still signs in with its old passphrase', (await loginOk({ team_id: pre.team.id, passphrase: pre.passphrase, first_name: 'Kat' })) === 'team');
ok('no student name was sent to the server', !sent.some((s) => /Lovelace|Hopper|Turing|Katherine/.test(s)), sent.filter((s) => /Lovelace|Hopper|Turing|Katherine/.test(s)).join(' | ').slice(0, 200));
await page.screenshot({ path: 'shots/people-slips.png', fullPage: true });

// 3. the teacher changes her own password: current one, new one twice, no pasting into the second
const tp = await browser.newPage();
tp.on('pageerror', (e) => errs.push(String(e)));
await tp.goto(W + '/login'); await tp.waitForTimeout(600);
await tp.click('#staff'); await tp.fill('#sn', 'Mrs. Example'); await tp.fill('#pp', tpass); await tp.click('#lf button[type=submit]');
await tp.waitForTimeout(1200);
await tp.goto(W + '/admin/password'); await tp.waitForSelector('#pwf', { timeout: 10000 });
const pasteBlocked = await tp.evaluate(() => {
  const el = document.getElementById('pwnew2'), dt = new DataTransfer(); dt.setData('text/plain', 'pasted!');
  const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
  return !el.dispatchEvent(ev);      // false = a handler called preventDefault
});
ok('pasting into "new password again" is blocked', pasteBlocked);
const pastable = await tp.evaluate(() => {
  const el = document.getElementById('pwnew'), dt = new DataTransfer(); dt.setData('text/plain', 'x');
  return el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
});
ok('pasting into the first new-password box is allowed', pastable);
await tp.fill('#pwold', 'wrong-one'); await tp.fill('#pwnew', 'wiggle'); await tp.type('#pwnew2', 'wiggle'); await tp.click('#pwf button[type=submit]');
await tp.waitForTimeout(800);
ok('a wrong current password is refused and she stays signed in', /current password is wrong/.test(await tp.textContent('#pwout')) && !!(await tp.$('#pwf')));
await tp.fill('#pwold', tpass); await tp.fill('#pwnew', 'wiggle'); await tp.fill('#pwnew2', ''); await tp.type('#pwnew2', 'wiggle2'); await tp.click('#pwf button[type=submit]');
await tp.waitForTimeout(300);
ok('two different new passwords are caught', /different/.test(await tp.textContent('#pwout')));
await tp.type('#pwnew2', 'wiggle'); await tp.click('#pwf button[type=submit]');
await tp.waitForSelector('.notice.info', { timeout: 8000 });
ok('the password is changed', /Password changed/.test(await tp.textContent('.notice.info')));
ok('the old password no longer works', (await loginOk({ name: 'Mrs. Example', passphrase: tpass })).startsWith('refused'));
ok('the new one does', (await loginOk({ name: 'Mrs. Example', passphrase: 'wiggle' })) === 'teacher');
ok('no page errors', !errs.length, errs.join(' | '));
await browser.close();
console.log(fails ? fails + ' FAILED' : 'ALL PASS');
process.exit(fails ? 1 : 0);
