/* app.js: Worm Mission Control. One file, no build step, no dependencies.

   The same files are served by two very different hosts:
     - a classroom Burrow (Pi on the LAN, open, often offline for weeks)
     - the Surface (Cloudflare Worker at whs.makerlabkids.com, cookie login)
   /api/me tells us which: {"local":true} means Burrow. Everything that is
   Surface-only (login, admin, the per-room /live/<n> streams) keys off that.

   Routing is path-based (history.pushState); both hosts serve index.html for
   unknown paths, so a reload on /bin/<uid> works without hash tricks. */
(function () {
  'use strict';

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var POLL_MS = 15000;           // /api/now cadence; Bins post every 60 s, so this is plenty
  var STALE_S = 180;             // matches the Burrow's own stale threshold
  var LS_PROJECTOR = 'dash.projector';

  /* ---- state --------------------------------------------------------- */
  var S = {
    me: null,               // /api/me body (or {ok:false} when logged out on Surface)
    local: false,           // true on a Burrow
    bins: {},               // uid -> entry (latest row per bin), from /api/now + SSE
    edges: {},              // edge name -> status brief
    lastNow: 0,             // when /api/now last succeeded (ms)
    sse: { sources: [], connected: 0, failures: 0, timer: null, wanted: false },
    liveBuf: {},            // uid -> {metric: [last 60 values]} for the live sparklines
    ticker: [],             // recent rows for the live ticker (newest first)
    route: null,
    view: null,             // the current view object (has .destroy())
    pollTimer: null,
    rowListeners: []        // views subscribe to incoming rows
  };

  /* ---- small helpers --------------------------------------------------- */
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function nowS() { return Math.floor(Date.now() / 1000); }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function f1(v, unit) { return isNum(v) ? (Math.round(v * 10) / 10).toFixed(1) + (unit || '') : '–'; }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function clock(ts) { var d = new Date(ts * 1000); return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds()); }
  function hhmm(ts) { var d = new Date(ts * 1000); return pad2(d.getHours()) + ':' + pad2(d.getMinutes()); }
  function dateTime(ts) { if (!isNum(ts)) return '–'; var d = new Date(ts * 1000); return d.toLocaleDateString() + ' ' + hhmm(ts); }
  function ago(ts) {
    if (!isNum(ts)) return 'never';
    var s = nowS() - ts;
    if (s < 5) return 'just now';
    if (s < 60) return s + ' s ago';
    if (s < 3600) return Math.floor(s / 60) + ' min ago';
    if (s < 86400) return Math.floor(s / 3600) + ' h ago';
    return Math.floor(s / 86400) + ' d ago';
  }
  function cmpNum(a, b) { return (a == null ? 1e9 : a) - (b == null ? 1e9 : b); }

  /* fetch JSON; a 401 on the Surface means "show the login page" for every route */
  function api(path, opts) {
    opts = opts || {};
    var init = { method: opts.method || 'GET', headers: {}, credentials: 'same-origin', cache: 'no-store' };
    if (opts.body !== undefined) { init.headers['Content-Type'] = opts.ctype || 'application/json'; init.body = opts.ctype ? opts.body : JSON.stringify(opts.body); }
    return fetch(path, init).then(function (r) {
      // a 401 anywhere but /api/me and /api/login means the cookie died: show the login form (a 401 from /api/login is just a wrong passphrase)
      if (r.status === 401 && !S.local && path !== '/api/me' && path !== '/api/login') { S.me = { ok: false }; render(); throw new Error('not signed in'); }
      return r.text().then(function (t) {
        var j = null; try { j = t ? JSON.parse(t) : null; } catch (e) { j = { raw: t }; }
        if (!r.ok) { var e = new Error((j && (j.error || j.message)) || ('HTTP ' + r.status)); e.status = r.status; e.body = j; throw e; }
        return j;
      });
    });
  }

  /* ---- entries, status --------------------------------------------------
     An entry is what /api/now gives per uid: {ts, clk, src, edge, room, name,
     team, period, bin, home_room, d, stale}. The Surface's merged snapshot
     lifts team/period/bin/room out of d.bin too; we fall back to d.bin for
     anything missing so either host works. */
  function entryFromRow(row) {
    var d = row.d || {}, b = d.bin || {};
    return { ts: row.ts, clk: row.clk, src: row.src, edge: row.edge, room: row.room,
      name: row.name || d.name, team: b.team, period: b.period, bin: b.bin, home_room: b.room, d: d };
  }
  function teamOf(e) { var b = (e.d && e.d.bin) || {}; return e.team || b.team || e.name || (e.d && e.d.name) || 'unnamed bin'; }
  function periodOf(e) { var b = (e.d && e.d.bin) || {}; return e.period != null ? e.period : b.period; }
  function binNoOf(e) { var b = (e.d && e.d.bin) || {}; return e.bin != null ? e.bin : b.bin; }
  function roomOf(e) { var b = (e.d && e.d.bin) || {}; return e.home_room != null ? e.home_room : (b.room != null ? b.room : e.room); }
  function moistures(d) { return [d.moist1_pct, d.moist2_pct].filter(isNum); }
  function partsOk(d) {
    var parts = Array.isArray(d.parts) ? d.parts : [];
    var ok = parts.filter(function (p) { return p && p.ok; }).length;
    return { ok: ok, total: parts.length };
  }
  /* Thresholds (see README and /about). Order matters: stale beats everything,
     since a reading from an hour ago says nothing about the bin now. */
  function statusOf(e, now) {
    now = now || nowS();
    if (e.stale || !isNum(e.ts) || now - e.ts > STALE_S) return 'stale';
    var d = e.d || {}, t = d.in_temp_c, ms = moistures(d);
    if ((isNum(t) && (t > 30 || t < 10)) || ms.some(function (m) { return m < 15; })) return 'alarm';
    var p = partsOk(d);
    if ((isNum(t) && (t > 27 || t < 15)) || ms.some(function (m) { return m < 25; }) || p.ok < p.total) return 'warn';
    return 'ok';
  }
  var STATUS_LABEL = { ok: 'NOMINAL', warn: 'WARN', alarm: 'ALARM', stale: 'STALE' };
  /* why a bin is in its state, for the lamp's tooltip */
  function statusWhy(e, now) {
    now = now || nowS();
    if (e.stale || !isNum(e.ts)) return 'no reading yet';
    if (now - e.ts > STALE_S) return 'last reading ' + ago(e.ts) + ' ago';
    var d = e.d || {}, t = d.in_temp_c, why = [];
    if (isNum(t)) {
      if (t > 30) why.push('air temp ' + f1(t) + ' °C, above 30 (alarm)');
      else if (t < 10) why.push('air temp ' + f1(t) + ' °C, below 10 (alarm)');
      else if (t > 27) why.push('air temp ' + f1(t) + ' °C, above 27 (warn)');
      else if (t < 15) why.push('air temp ' + f1(t) + ' °C, below 15 (warn)');
    }
    [['soil moisture 1', d.moist1_pct], ['soil moisture 2', d.moist2_pct]].forEach(function (x) {
      if (!isNum(x[1])) return;
      if (x[1] < 15) why.push(x[0] + ' ' + f1(x[1]) + ' %, under 15 (alarm)');
      else if (x[1] < 25) why.push(x[0] + ' ' + f1(x[1]) + ' %, under 25 (warn)');
    });
    (d.parts || []).forEach(function (pt) { if (pt && pt.ok === false) why.push(pt.name + ' not responding (warn)'); });
    return why.length ? why.join('\n') : 'air temp 15–27 °C, soil moisture 25 % or more, every part reporting';
  }

  /* ---- data: polling + SSE ------------------------------------------- */
  function applyNow(j) {
    if (!j || !j.bins) return;
    S.edges = j.edges || {};
    var seen = {};
    Object.keys(j.bins).forEach(function (uid) {
      var e = j.bins[uid]; seen[uid] = 1;
      var old = S.bins[uid];
      if (!old || (e.ts || 0) >= (old.ts || 0)) S.bins[uid] = e;
    });
    // a bin that vanished from the snapshot (older than 24 h) leaves the wall too
    Object.keys(S.bins).forEach(function (uid) { if (!seen[uid]) delete S.bins[uid]; });
    S.lastNow = Date.now();
    renderHeader();
    if (S.view && S.view.onNow) S.view.onNow();
  }
  function pollNow() {
    return api('/api/now').then(applyNow).catch(function (e) { if (e.message !== 'not signed in') console.warn('now:', e.message); });
  }
  function startPolling() {
    if (S.pollTimer) return;
    pollNow();
    S.pollTimer = setInterval(pollNow, POLL_MS);
  }

  /* PROTOCOL.md says `event: row` carries the row JSON ({ts,clk,uid,name,room,edge,src,d});
     the Burrow actually sends {uid, entry} with the now-table entry. Accept both. */
  function normalizeRow(msg) {
    if (msg && msg.entry && !msg.d) {
      var e = msg.entry;
      return { ts: e.ts, clk: e.clk, uid: msg.uid, name: e.name, room: e.room, edge: e.edge, src: e.src, d: e.d || {}, _entry: e };
    }
    return msg;
  }
  function onRow(row, prevEntry) {
    row = normalizeRow(row);
    if (!row || !row.uid) return;
    var e = row._entry ? Object.assign({}, row._entry) : entryFromRow(row);
    var old = prevEntry || S.bins[row.uid];
    if (old && (old.ts || 0) > (e.ts || 0)) return;   // out-of-order replay; keep the newer
    e.stale = false;
    S.bins[row.uid] = e;
    // live sparklines keep the last 60 values of every numeric metric, in memory only
    var buf = S.liveBuf[row.uid] || (S.liveBuf[row.uid] = {});
    Object.keys(e.d || {}).forEach(function (k) {
      var v = e.d[k];
      if (isNum(v)) { (buf[k] = buf[k] || []).push(v); if (buf[k].length > 60) buf[k].shift(); }
    });
    S.ticker.unshift({ row: row, prev: old, at: Date.now() });
    if (S.ticker.length > 200) S.ticker.length = 200;
    S.rowListeners.forEach(function (fn) { try { fn(row, e, old); } catch (err) { console.error(err); } });
    renderHeader();
  }

  /* SSE: one stream on a Burrow (/live), one per room on the Surface (/live/1..3,
     each optional: a room whose Burrow is dark just stays disconnected).
     EventSource reconnects by itself, but after repeated failures we close it
     and retry with our own backoff so a dead edge is not hammered every second. */
  function sseUrls() { return S.local ? ['/live'] : ['/live/1', '/live/2', '/live/3']; }
  function startSSE() {
    S.sse.wanted = true;
    if (S.sse.sources.length || !window.EventSource) return;
    sseUrls().forEach(openSSE);
  }
  function openSSE(url) {
      var es;
      try { es = new EventSource(url); } catch (e) { return; }
      es._open = false; es._url = url; es._tries = 0;
      es.addEventListener('hello', function (ev) {
        try { var h = JSON.parse(ev.data); if (h && h.bins) applyNow({ bins: Object.assign({}, S.bins, h.bins), edges: S.edges }); } catch (e) { }
      });
      es.addEventListener('row', function (ev) { try { onRow(JSON.parse(ev.data)); } catch (e) { console.warn('bad row', e); } });
      es.onopen = function () { if (!es._open) { es._open = true; S.sse.connected++; } S.sse.failures = 0; renderHeader(); if (S.view && S.view.onSSE) S.view.onSSE(); };
      es.onerror = function () {
        if (es._open) { es._open = false; S.sse.connected--; }
        S.sse.failures++;
        renderHeader(); if (S.view && S.view.onSSE) S.view.onSSE();
        if (es.readyState === 2) {
          // a non-200 (the Surface says 502 for a dark room) closes the source for good;
          // the browser will not retry it, so we do, slowly, in case the room wakes up
          var i = S.sse.sources.indexOf(es); if (i >= 0) S.sse.sources.splice(i, 1);
          var delay = Math.min(60000, 5000 * Math.pow(2, es._tries++));
          setTimeout(function () { if (S.sse.wanted && !S.sse.sources.some(function (x) { return x._url === url; })) { var n = openSSE(url); if (n) n._tries = es._tries; } }, delay);
        } else if (S.sse.failures >= 3 * sseUrls().length) scheduleSSERetry();
      };
      S.sse.sources.push(es);
      return es;
  }
  function stopSSE(keepWanted) {
    S.sse.sources.forEach(function (es) { try { es.close(); } catch (e) { } });
    S.sse.sources = []; S.sse.connected = 0;
    if (!keepWanted) { S.sse.wanted = false; clearTimeout(S.sse.timer); S.sse.timer = null; }
  }
  function scheduleSSERetry() {
    if (S.sse.timer) return;
    var attempt = Math.min(6, Math.floor(S.sse.failures / sseUrls().length));
    var delay = Math.min(60000, 2000 * Math.pow(2, attempt));
    stopSSE(true);
    S.sse.timer = setTimeout(function () { S.sse.timer = null; if (S.sse.wanted) startSSE(); }, delay);
  }
  function sseState() {
    if (S.sse.connected > 0) return 'on';
    if (!S.sse.wanted) return 'off';
    return S.sse.failures ? 'down' : 'connecting';
  }

  /* ---- header -------------------------------------------------------- */
  function renderHeader() {
    var now = nowS(), counts = { ok: 0, warn: 0, alarm: 0, stale: 0 };
    Object.keys(S.bins).forEach(function (uid) { counts[statusOf(S.bins[uid], now)]++; });
    var c = $('#counts');
    c.innerHTML = ['ok', 'warn', 'alarm', 'stale'].map(function (k) {
      return '<span class="count ' + k + '" title="' + STATUS_LABEL[k] + '"><i></i>' + counts[k] + ' <span class="sr-only">' + STATUS_LABEL[k] + '</span></span>';
    }).join('');
    var eg = $('#edges');
    eg.innerHTML = Object.keys(S.edges).sort().map(function (name) {
      var e = S.edges[name] || {}, up = isNum(e.ts) && now - e.ts < 300;
      var clk = e.clk || '?', cloud = e.cloud_ok;
      return '<span class="edge ' + (up ? '' : 'down') + '" title="' + esc(name) + ' · room ' + esc(e.room) + ' · clock ' + esc(clk) +
        ' · castings ' + esc(e.castings) + (e.unverified ? ' (' + esc(e.unverified) + ' unverified)' : '') + ' · ' + (up ? 'up' : 'last seen ' + ago(e.ts)) + '">' +
        '<i></i>' + esc(e.edge || name) + ' <span class="muted">R' + esc(e.room) + '</span>' +
        ' <span class="clk ' + esc(clk) + '">' + esc(clk) + '</span>' +
        ' <span class="cloud ' + (cloud ? 'ok' : '') + '">' + (cloud ? 'cloud ok' : (S.local ? 'no cloud' : '')) + '</span>' +
        (isNum(e.castings) ? ' <span class="muted">' + e.castings + (e.unverified ? '/' + e.unverified + '!' : '') + '</span>' : '') + '</span>';
    }).join('');
    var live = $('#live'), st = sseState();
    live.className = 'live ' + (st === 'on' ? 'on' : '');
    live.title = st === 'on' ? 'live stream connected' : st === 'down' ? 'live stream down; polling' : st === 'connecting' ? 'connecting…' : 'polling';
    $('#live span').textContent = st === 'on' ? 'live' : st === 'down' ? 'polling' : st === 'connecting' ? 'connecting' : 'polling';
    var ck = $('#clock');
    ck.innerHTML = S.lastNow ? '<b>' + clock(Math.floor(S.lastNow / 1000)) + '</b> <span>' + ago(Math.floor(S.lastNow / 1000)) + '</span>' : 'loading…';
    // nav highlights + who's signed in
    document.querySelectorAll('.nav a').forEach(function (a) {
      var p = a.getAttribute('href');
      a.classList.toggle('on', p === '/' ? location.pathname === '/' : location.pathname.indexOf(p) === 0);
    });
    var role = S.me && S.me.role;
    $('#nav-admin').hidden = !(role === 'teacher' || role === 'admin');
    var who = $('#whoami');
    if (!S.local && S.me && S.me.ok) {
      who.hidden = false;
      var html = 'signed in as <b>' + esc(S.me.first_name || S.me.name || role) + '</b>' +
        (S.me.team && S.me.team.name ? ' · ' + esc(S.me.team.name) : '') + ' <button type="button" id="signout">sign out</button>';
      if (who._html !== html) {   // rebuilt only on change, so a focused sign-out button survives the per-row re-render
        who.innerHTML = html; who._html = html;
        $('#signout').onclick = function () { api('/api/logout', { method: 'POST', body: {} }).catch(function () { }).then(function () { S.me = { ok: false }; render(); }); };
      }
    } else { who.hidden = true; who._html = null; }
  }
  // relative times drift; refresh the header text once a second (cheap)
  setInterval(function () { if (S.lastNow) { var ck = $('#clock span'); if (ck) ck.textContent = ago(Math.floor(S.lastNow / 1000)); } }, 1000);

  /* ---- routing ------------------------------------------------------- */
  function parseRoute(path) {
    var m;
    if (path === '/' || path === '' || path === '/index.html') return { name: 'wall' };
    if ((m = path.match(/^\/bin\/([^/]+)\/?$/))) return { name: 'bin', uid: decodeURIComponent(m[1]) };
    // the live page lives at /feed: on a Burrow GET /live IS the SSE stream (server.py), so it can't be a page there
    if (path === '/feed' || path === '/feed/' || path === '/live/') return { name: 'live' };
    if (path === '/login') return { name: 'login' };
    if (path.indexOf('/admin') === 0) return { name: 'admin', tab: path.split('/')[2] || 'edges' };
    if (path === '/about') return { name: 'about' };
    return { name: 'wall' };
  }
  function navigate(path) { if (location.pathname !== path) history.pushState(null, '', path); render(); }
  document.addEventListener('click', function (ev) {
    var a = ev.target.closest && ev.target.closest('a[href]');
    if (!a || a.target || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    var href = a.getAttribute('href');
    if (href.charAt(0) !== '/' || href.indexOf('/api/') === 0 || a.hasAttribute('download')) return;
    ev.preventDefault(); navigate(href);
  });
  window.addEventListener('popstate', render);

  function render() {
    var r = parseRoute(location.pathname);
    var main = $('#view');
    if (S.view && S.view.destroy) S.view.destroy();
    S.view = null; S.rowListeners = [];
    main.innerHTML = '';
    document.body.classList.remove('print-cards');
    if (!S.me) { main.appendChild(el('div', 'empty', 'connecting…')); return; }
    // Surface, not signed in: every route shows the login form, URL kept so a reload lands back here
    if (!S.local && !S.me.ok) { S.view = viewLogin(main); renderHeader(); return; }
    S.route = r;
    startPolling();   // the header (counts, edges, clock) is on every page
    var v = { wall: viewWall, bin: viewBin, live: viewLive, login: viewLogin, admin: viewAdmin, about: viewAbout }[r.name];
    S.view = v(main, r);
    renderHeader();
  }

  /* ---- view: status wall --------------------------------------------- */
  function tileHTML(e, now) {
    var d = e.d || {}, st = statusOf(e, now), p = partsOk(d), ms = moistures(d);
    var probes = Array.isArray(d.probe_temps_c) ? d.probe_temps_c.filter(isNum) : [];
    var t = d.in_temp_c;
    var tCls = isNum(t) ? (t > 30 || t < 10 ? 'bad' : t > 27 || t < 15 ? 'meh' : '') : '';
    function mCls(m) { return !isNum(m) ? '' : m < 15 ? 'bad' : m < 25 ? 'meh' : ''; }
    var rd = '';
    rd += '<div class="rd"><span class="k">air temp</span><span class="v ' + tCls + '">' + f1(t) + '<small>°C</small></span></div>';
    rd += '<div class="rd"><span class="k">air humidity</span><span class="v">' + f1(d.in_hum_pct) + '<small>%</small></span></div>';
    if (isNum(d.in_press_hpa)) rd += '<div class="rd"><span class="k">air pressure</span><span class="v">' + Math.round(d.in_press_hpa) + '<small> hPa</small></span></div>';
    rd += '<div class="rd"><span class="k">soil moisture</span><span class="v">' +
      (ms.length ? [d.moist1_pct, d.moist2_pct].filter(isNum).map(function (m) { return '<span class="' + mCls(m) + '">' + f1(m) + '</span>'; }).join('<small> · </small>') : '–') + '<small>%</small></span></div>';
    rd += '<div class="rd"><span class="k">soil temp</span><span class="v">' + (probes.length ? probes.map(function (x) { return f1(x); }).join('<small> · </small>') : '–') + '<small>°C</small></span></div>';
    if (isNum(d.surface_mm)) rd += '<div class="rd"><span class="k">surface</span><span class="v">' + Math.round(d.surface_mm) + '<small> mm</small></span></div>';
    if (isNum(d.out_temp_c)) rd += '<div class="rd"><span class="k">room temp</span><span class="v">' + f1(d.out_temp_c) + '<small>°C</small></span></div>';
    var wifi = [d.mode, e.edge].filter(Boolean).join(' · ');
    return '<div class="who"><span>P' + esc(periodOf(e) != null ? periodOf(e) : '?') + ' · Bin ' + esc(binNoOf(e) != null ? binNoOf(e) : '?') + '</span>' +
      '<span class="lamp" title="' + esc(statusWhy(e, now)) + '"><i></i>' + STATUS_LABEL[st] + '</span></div>' +
      '<div class="team" title="' + esc(teamOf(e)) + '">' + esc(teamOf(e)) + '</div>' +
      '<div class="readings">' + rd + '</div>' +
      '<div class="foot"><span class="parts ' + (p.total && p.ok < p.total ? 'bad' : '') + '" title="' + esc((d.parts || []).map(function (x) { return (x.ok ? 'ok ' : 'FAIL ') + x.name; }).join('\n')) + '">' +
      (p.total ? 'parts ' + p.ok + '/' + p.total : 'parts –') + '</span>' +
      '<span title="Wi-Fi mode · edge">' + esc(wifi || '–') + (isNum(d.rssi) ? ' ' + d.rssi + ' dBm' : '') + '</span>' +
      '<span class="age" data-ts="' + (e.ts || 0) + '">' + ago(e.ts) + '</span></div>';
  }

  function viewWall(main) {
    var filter = { q: '', room: '', period: '' };
    var tiles = {};   // uid -> {a, sig, group}
    var tb = el('div', 'toolbar');
    tb.innerHTML = '<label class="sr-only" for="q">filter by team</label><input type="text" id="q" placeholder="filter teams…" autocomplete="off">' +
      '<label class="sr-only" for="froom">room</label><select id="froom"><option value="">all rooms</option><option>1</option><option>2</option><option>3</option></select>' +
      '<label class="sr-only" for="fper">period</label><select id="fper"><option value="">all periods</option>' + [1, 2, 3, 4, 5, 6, 7].map(function (p) { return '<option>' + p + '</option>'; }).join('') + '</select>' +
      '<span class="hint" id="shown"></span>';
    main.appendChild(tb);
    var wall = el('div', 'wall'); main.appendChild(wall);
    var empty = el('div', 'empty', 'No bins yet. When a Bin posts to this Burrow its tile appears here.'); empty.hidden = true; main.appendChild(empty);
    $('#q', tb).oninput = function () { filter.q = this.value.trim().toLowerCase(); draw(); };
    $('#froom', tb).onchange = function () { filter.room = this.value; draw(); };
    $('#fper', tb).onchange = function () { filter.period = this.value; draw(); };

    function groupKey(e) { return 'r' + (roomOf(e) != null ? roomOf(e) : 9) + 'p' + (periodOf(e) != null ? periodOf(e) : 99); }
    function groupLabel(e) { return 'Room ' + (roomOf(e) != null ? roomOf(e) : '?') + ' <small>Period ' + (periodOf(e) != null ? periodOf(e) : '?') + '</small>'; }
    function visible(e) {
      if (filter.room && String(roomOf(e)) !== filter.room) return false;
      if (filter.period && String(periodOf(e)) !== filter.period) return false;
      if (filter.q && teamOf(e).toLowerCase().indexOf(filter.q) < 0) return false;
      return true;
    }

    /* Update in place, keyed by uid: a tile only re-renders when its row changed,
       and only moves when its room/period changed, so the wall never jumps. */
    function draw() {
      var now = nowS(), uids = Object.keys(S.bins), shown = 0;
      var groups = {}, cursors = {}, lastGroup = null;
      function place(parent, node, after) {       // put node right after `after` (or first) only if it is not already there
        if (node.parentNode !== parent || node.previousElementSibling !== after) parent.insertBefore(node, after ? after.nextSibling : parent.firstChild);
      }
      uids.sort(function (a, b) {
        var ea = S.bins[a], eb = S.bins[b];
        return cmpNum(roomOf(ea), roomOf(eb)) || cmpNum(periodOf(ea), periodOf(eb)) || cmpNum(binNoOf(ea), binNoOf(eb)) || teamOf(ea).localeCompare(teamOf(eb));
      });
      uids.forEach(function (uid) {
        var e = S.bins[uid], gk = groupKey(e);
        var g = groups[gk];
        if (!g) {
          g = wall.querySelector('[data-group="' + gk + '"]');
          if (!g) { g = el('section', 'group'); g.dataset.group = gk; g.innerHTML = '<h2>' + groupLabel(e) + '</h2><div class="tiles"></div>'; }
          groups[gk] = g;
        }
        if (!cursors.hasOwnProperty(gk)) { place(wall, g, lastGroup); lastGroup = g; cursors[gk] = null; }   // groups land in sorted order too
        var t = tiles[uid];
        if (!t) {
          var a = el('a', 'tile'); a.href = '/bin/' + encodeURIComponent(uid); a.dataset.uid = uid;
          t = tiles[uid] = { a: a, sig: null };
        }
        var sig = (e.ts || 0) + ':' + statusOf(e, now);
        if (t.sig !== sig) { t.a.innerHTML = tileHTML(e, now); t.a.className = 'tile ' + statusOf(e, now); t.sig = sig; }
        var v = visible(e); t.a.hidden = !v; if (v) shown++;
        place(g.querySelector('.tiles'), t.a, cursors[gk]); cursors[gk] = t.a;
      });
      // drop tiles for bins that vanished, and empty groups
      Object.keys(tiles).forEach(function (uid) { if (!S.bins[uid]) { tiles[uid].a.remove(); delete tiles[uid]; } });
      Array.prototype.forEach.call(wall.querySelectorAll('.group'), function (g) {
        var any = Array.prototype.some.call(g.querySelectorAll('.tile'), function (a) { return !a.hidden; });
        g.hidden = !any;
        if (!g.querySelector('.tile')) g.remove();
      });
      empty.hidden = uids.length > 0;
      $('#shown', tb).textContent = uids.length ? shown + ' of ' + uids.length + ' bins' : '';
    }
    // "2 min ago" and stale-ness change without any new data: re-evaluate every 10 s
    var tick = setInterval(function () {
      var now = nowS();
      Object.keys(tiles).forEach(function (uid) {
        var e = S.bins[uid]; if (!e) return;
        var st = statusOf(e, now);
        if (!tiles[uid].a.classList.contains(st)) { tiles[uid].sig = null; }
        var age = tiles[uid].a.querySelector('.age'); if (age) age.textContent = ago(e.ts);
      });
      draw();
    }, 10000);
    S.rowListeners.push(function (row) {
      draw();
      var t = tiles[row.uid];
      if (t) { t.a.classList.remove('flash'); void t.a.offsetWidth; t.a.classList.add('flash'); }
    });
    startPolling(); startSSE();
    draw();
    return { onNow: draw, destroy: function () { clearInterval(tick); } };
  }

  /* ---- view: deep history -------------------------------------------- */
  var RANGES = [['6h', 6 * 3600], ['24h', 86400], ['3d', 3 * 86400], ['7d', 7 * 86400], ['30d', 30 * 86400]];
  var UNITS = { _c: '°C', _pct: '%', _hpa: ' hPa', _mm: ' mm', lux: ' lx', rssi: ' dBm' };
  var SKIP_METRICS = { up: 1, probes: 1, probe_count: 1, big: 1, small: 1, relay: 1 };   // bookkeeping and actuators, not science
  function unitFor(m) {
    if (/_c(_\d+)?$/.test(m)) return UNITS._c;
    if (/_pct(_\d+)?$/.test(m)) return UNITS._pct;
    if (/_hpa$/.test(m)) return UNITS._hpa;
    if (/_mm$/.test(m)) return UNITS._mm;
    if (m === 'lux') return UNITS.lux;
    if (m === 'rssi') return UNITS.rssi;
    return '';
  }
  function prettyMetric(m) {
    var names = { in_temp_c: 'air temp', out_temp_c: 'room temp', in_hum_pct: 'air humidity', out_hum_pct: 'room humidity', moist1_pct: 'soil moisture 1', moist2_pct: 'soil moisture 2',
      light_pct: 'light', lux: 'lux', in_press_hpa: 'air pressure', sound_pct: 'sound', surface_mm: 'surface', rssi: 'Wi-Fi signal' };
    if (names[m]) return names[m];
    var pm = m.match(/^probe_temps_c_(\d+)$/); if (pm) return 'soil temp ' + (parseInt(pm[1], 10) + 1);
    return m.replace(/_/g, ' ');
  }
  /* metric groups, in display order; anything numeric not listed gets its own small chart */
  var GROUPS = [
    { title: 'Temperature', unit: '°C', match: function (m) { return /^(in_temp_c|out_temp_c|probe_temps_c_\d+)$/.test(m); } },
    { title: 'Air humidity', unit: '%', min0: true, match: function (m) { return /^(in_hum_pct|out_hum_pct)$/.test(m); } },
    { title: 'Soil moisture', unit: '%', min0: true, match: function (m) { return /^moist\d_pct$/.test(m); } },
    { title: 'Air pressure', unit: ' hPa', match: function (m) { return /^in_press_hpa$/.test(m); } },
    { title: 'Light', unit: '', min0: true, match: function (m) { return /^(light_pct|lux)$/.test(m); } }
  ];
  var SERIES_COLORS = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6'];
  function seriesColor(i) { return getComputedStyle(document.documentElement).getPropertyValue(SERIES_COLORS[i % SERIES_COLORS.length]).trim() || '#2E7DBC'; }

  function viewBin(main, r) {
    var uid = r.uid, e = S.bins[uid], charts = [];
    var head = el('div', 'card binhead'); main.appendChild(head);
    var ranges = el('div', 'ranges'); main.appendChild(ranges);
    var out = el('div', 'charts'); main.appendChild(out);
    var curRange = (function () { try { return localStorage.getItem('dash.range') || '24h'; } catch (x) { return '24h'; } })();
    var roster = null;

    function drawHead() {
      var e = S.bins[uid];
      var name = e ? teamOf(e) : (roster && roster.team) || (roster && roster.name) || uid;
      var per = e ? periodOf(e) : roster && roster.period, bn = e ? binNoOf(e) : roster && roster.bin, room = e ? roomOf(e) : roster && roster.room;
      var st = e ? statusOf(e) : 'stale';
      var d = (e && e.d) || {};
      head.innerHTML = '<div><div class="team">' + esc(name) + '</div><div class="meta">Period ' + esc(per != null ? per : '?') + ' · Bin ' + esc(bn != null ? bn : '?') +
        ' · Room ' + esc(room != null ? room : '?') + ' · <span class="mono">' + esc(uid) + '</span>' + (d.name && d.name !== name ? ' · ' + esc(d.name) : '') + '</div>' +
        '<div class="meta"><span class="lamp tile-' + st + '" title="' + (e ? esc(statusWhy(e)) : '') + '">' + STATUS_LABEL[st] + '</span> · last reading ' + (e ? ago(e.ts) + ' (' + clock(e.ts) + ', clock ' + esc(e.clk || '?') + ')' : 'none yet') +
        (d.ip ? ' · <span class="mono">' + esc(d.ip) + '</span>' : '') + (isNum(d.rssi) ? ' · ' + d.rssi + ' dBm' : '') + '</div></div>' +
        '<div class="nowrow">' + [['air temp', d.in_temp_c, '°C'], ['air humidity', d.in_hum_pct, '%'], ['air pressure', isNum(d.in_press_hpa) ? Math.round(d.in_press_hpa) : null, ' hPa'], ['room temp', d.out_temp_c, '°C'], ['soil moisture 1', d.moist1_pct, '%'], ['soil moisture 2', d.moist2_pct, '%'],
          ['soil temp', Array.isArray(d.probe_temps_c) ? d.probe_temps_c.filter(isNum).map(function (x) { return f1(x); }).join(' · ') : null, '°C'],
          ['surface', isNum(d.surface_mm) ? Math.round(d.surface_mm) : null, ' mm'], ['light', d.light_pct, '%'], ['parts', (function () { var p = partsOk(d); return p.total ? p.ok + '/' + p.total : null; })(), '']]
          .filter(function (x) { return x[1] != null && x[1] !== ''; })
          .map(function (x) { return '<div class="rd"><span class="k">' + x[0] + '</span><span class="v">' + (typeof x[1] === 'number' ? f1(x[1]) : esc(x[1])) + '<small>' + x[2] + '</small></span></div>'; }).join('') +
        '</div>' + '<div class="spacer"></div><a class="btn ghost sm" href="/">← wall</a>';
    }
    function drawRanges(step, n) {
      ranges.innerHTML = RANGES.map(function (x) { return '<button type="button" data-r="' + x[0] + '" class="' + (x[0] === curRange ? 'on' : '') + '" aria-pressed="' + (x[0] === curRange) + '">' + x[0] + '</button>'; }).join('') +
        '<span class="step">' + (step ? 'step ' + esc(step) + ' · ' + n + ' buckets' : '') + '</span>';
      Array.prototype.forEach.call(ranges.querySelectorAll('button'), function (b) { b.onclick = function () { curRange = b.dataset.r; try { localStorage.setItem('dash.range', curRange); } catch (x) { } load(); }; });
    }
    function destroyCharts() { charts.forEach(function (c) { c.destroy(); }); charts = []; out.innerHTML = ''; }

    function load() {
      drawRanges(null, 0);
      var span = RANGES.filter(function (x) { return x[0] === curRange; })[0][1];
      var to = nowS(), from = to - span;
      out.innerHTML = '<div class="empty">loading history…</div>';
      api('/api/history?uid=' + encodeURIComponent(uid) + '&from=' + from + '&to=' + to).then(function (h) {
        destroyCharts();
        var pts = (h && h.points) || [], step = (h && h.step) || '5m';
        var stepS = step === '1h' ? 3600 : 300;
        drawRanges(step, pts.length);
        if (!pts.length) {
          out.innerHTML = '<div class="card empty">No history yet for this range.<br><span class="muted">Castings seal every 15 minutes; the first buckets appear after the next quarter hour.</span></div>';
          return;
        }
        // pivot: metric -> [{t,min,avg,max,n}]
        var byMetric = {};
        pts.forEach(function (p) {
          var ts = p[0], data = p[1] || {};
          Object.keys(data).forEach(function (m) {
            var a = data[m]; if (!Array.isArray(a) || !isNum(a[1])) return;
            (byMetric[m] = byMetric[m] || []).push({ t: ts, min: isNum(a[0]) ? a[0] : a[1], avg: a[1], max: isNum(a[2]) ? a[2] : a[1], n: a[3] || 1 });
          });
        });
        var metrics = Object.keys(byMetric).filter(function (m) { return !SKIP_METRICS[m] && !/^probe_ok/.test(m); }).sort();
        var used = {};
        GROUPS.forEach(function (g) {
          var ms = metrics.filter(g.match); if (!ms.length) return;
          ms.forEach(function (m) { used[m] = 1; });
          addChart(g.title, g.unit, ms, false, g.min0, from, to, stepS, byMetric);
        });
        metrics.filter(function (m) { return !used[m]; }).forEach(function (m) { addChart(prettyMetric(m), unitFor(m), [m], true, false, from, to, stepS, byMetric); });
      }).catch(function (err) {
        if (err.message === 'not signed in') return;
        out.innerHTML = '<div class="notice err">Could not load history: ' + esc(err.message) + '</div>';
      });
    }
    function summary(points) {
      var lo = Infinity, hi = -Infinity, sum = 0, n = 0;
      points.forEach(function (p) { if (p.min < lo) lo = p.min; if (p.max > hi) hi = p.max; sum += p.avg * p.n; n += p.n; });
      return { min: lo, max: hi, avg: n ? sum / n : NaN };
    }
    function addChart(title, unit, ms, small, min0, from, to, stepS, byMetric) {
      var card = el('div', 'chart-card' + (small ? ' small' : ''));
      var series = ms.map(function (m, i) {
        // probes dashed, "room" (out_*) dotted-ish, so lines differ by more than hue
        return { name: prettyMetric(m), color: seriesColor(i), dash: /^probe_|^out_/.test(m), points: byMetric[m] };
      });
      var legend = series.map(function (s) {
        var sm = summary(s.points);
        return '<span class="li"><span class="sw ' + (s.dash ? 'dash' : '') + '" style="border-color:' + s.color + '"></span>' + esc(s.name) +
          ' <span class="mm">min ' + f1(sm.min) + ' · avg ' + f1(sm.avg) + ' · max ' + f1(sm.max) + '</span></span>';
      }).join('');
      card.innerHTML = '<h3>' + esc(title) + ' <small>' + esc(unit.trim()) + '</small></h3><div class="legend">' + legend + '</div><div class="chartbox"></div>';
      out.appendChild(card);
      var ch = LineChart($('.chartbox', card), { unit: unit, gapS: stepS * 1.5, min0: min0 });
      ch.set(series, { from: from, to: to });
      charts.push(ch);
    }

    drawHead();
    if (!e) api('/api/bins').then(function (b) { roster = b && b[uid]; drawHead(); }).catch(function () { });
    load();
    startPolling(); startSSE();
    S.rowListeners.push(function (row) { if (row.uid === uid) drawHead(); });
    return { onNow: drawHead, destroy: destroyCharts };
  }

  /* ---- view: live ---------------------------------------------------- */
  var SPARK_METRICS = [['in_temp_c', 'air temp °C'], ['in_hum_pct', 'air humidity %'], ['moist1_pct', 'soil moisture 1 %'], ['moist2_pct', 'soil moisture 2 %']];
  var WATCH = ['in_temp_c', 'in_hum_pct', 'moist1_pct', 'moist2_pct', 'out_temp_c', 'light_pct', 'surface_mm'];
  function viewLive(main) {
    var sparkMetric = 'in_temp_c';
    var banner = el('div', 'notice'); banner.hidden = true; main.appendChild(banner);
    var grid = el('div', 'livegrid'); main.appendChild(grid);
    var left = el('div', 'card ticker'); left.innerHTML = '<h3>Incoming readings</h3><ol id="tick"></ol>'; grid.appendChild(left);
    var right = el('div'); right.innerHTML = '<div class="toolbar"><label for="sm">sparkline</label><select id="sm">' +
      SPARK_METRICS.map(function (x) { return '<option value="' + x[0] + '">' + x[1] + '</option>'; }).join('') + '</select><span class="hint">last 60 readings, held in this tab only</span></div><div class="sparks" id="sparks"></div>';
    grid.appendChild(right);
    var ol = $('#tick', left), sparks = $('#sparks', right), cards = {};
    $('#sm', right).onchange = function () { sparkMetric = this.value; drawSparks(true); };

    function changes(d, prev) {
      var parts = [];
      WATCH.forEach(function (k) {
        if (!isNum(d[k])) return;
        var p = prev && prev.d && prev.d[k], delta = isNum(p) ? d[k] - p : null;
        var arrow = delta === null || Math.abs(delta) < 0.05 ? '' : (delta > 0 ? ' <span class="up">▲' + f1(Math.abs(delta)) + '</span>' : ' <span class="dn">▼' + f1(Math.abs(delta)) + '</span>');
        parts.push(prettyMetric(k) + ' <b>' + (k === 'surface_mm' ? Math.round(d[k]) : f1(d[k])) + '</b>' + arrow);
      });
      return parts.join(' · ');
    }
    function addTick(item, isNew) {
      var row = item.row, e = entryFromRow(row);
      var li = el('li', isNew ? 'new' : '');
      li.innerHTML = '<span class="t">' + clock(row.ts) + '</span><a class="n" href="/bin/' + encodeURIComponent(row.uid) + '">' + esc(teamOf(e)) + '</a>' +
        '<span class="ch">' + changes(e.d || {}, item.prev) + (row.src === 'pull' ? ' · <i>pulled</i>' : '') + '</span>';
      if (isNew) ol.insertBefore(li, ol.firstChild); else ol.appendChild(li);
      while (ol.children.length > 150) ol.removeChild(ol.lastChild);
    }
    function drawSparks(force) {
      var now = nowS(), uids = Object.keys(S.bins).sort(function (a, b) { return teamOf(S.bins[a]).localeCompare(teamOf(S.bins[b])); });
      uids.forEach(function (uid) {
        var e = S.bins[uid], c = cards[uid];
        if (!c) {
          c = cards[uid] = el('a', 'spark'); c.href = '/bin/' + encodeURIComponent(uid);
          c.innerHTML = '<div class="n"></div><div class="v"><span></span><b></b></div><canvas height="40"></canvas>';
        }
        c.className = 'spark ' + statusOf(e, now);
        $('.n', c).textContent = teamOf(e);
        var vals = (S.liveBuf[uid] && S.liveBuf[uid][sparkMetric]) || [];
        var cur = e.d && e.d[sparkMetric];
        $('.v span', c).textContent = vals.length + ' pts · ' + ago(e.ts);
        $('.v b', c).textContent = f1(cur) + (unitFor(sparkMetric).trim());
        sparks.appendChild(c);
        if (force || c._n !== vals.length) { sparkline($('canvas', c), vals, seriesColor(0)); c._n = vals.length; }
      });
    }
    function banner_() {
      var st = sseState();
      banner.hidden = st === 'on' || st === 'connecting';
      banner.textContent = st === 'down' ? 'Edge live stream offline — polling /api/now every 15 s instead.' : 'Live stream unavailable in this browser — polling instead.';
    }
    // when SSE is down, poll results still produce "rows" for the ticker: any bin whose ts moved
    var lastTs = {}, lastEntry = {};
    function onNow() {
      Object.keys(S.bins).forEach(function (uid) {
        var e = S.bins[uid], prev = lastEntry[uid];
        lastEntry[uid] = e;
        if (sseState() !== 'on' && lastTs[uid] && e.ts > lastTs[uid]) {
          var row = { ts: e.ts, uid: uid, name: e.name, room: e.room, edge: e.edge, src: e.src, d: e.d, clk: e.clk };
          onRow(row, prev); return;   // onRow fans out to the listener below, which draws the tick
        }
        lastTs[uid] = e.ts;
      });
      drawSparks(false); banner_();
    }
    S.ticker.slice(0, 150).forEach(function (it) { addTick(it, false); });
    S.rowListeners.push(function (row, e) { lastTs[row.uid] = row.ts; lastEntry[row.uid] = e; addTick(S.ticker[0], true); drawSparks(false); });
    startPolling(); startSSE();
    drawSparks(true); banner_();
    if (!ol.children.length) ol.innerHTML = '<li class="muted">waiting for the first reading…</li>';
    var firstReal = S.rowListeners[S.rowListeners.length - 1];
    S.rowListeners[S.rowListeners.length - 1] = function (row, e) { var w = ol.querySelector('li.muted'); if (w) w.remove(); firstReal(row, e); };
    return { onNow: onNow, onSSE: banner_, destroy: function () { } };
  }

  /* ---- view: login (Surface only) ------------------------------------ */
  function viewLogin(main) {
    if (S.local) {   // a Burrow has no accounts: physical presence is the credential
      main.appendChild(el('div', 'card empty', 'No sign-in here: this classroom Burrow is open to everyone in the room. <a href="/">Back to the wall</a>.'));
      return { destroy: function () { } };
    }
    var box = el('div', 'card login');
    box.innerHTML = '<h1>Sign in</h1><p class="muted">Pick your team, type the team passphrase and your first name.</p>' +
      '<form id="lf"><div class="field" id="teamf"><label for="team">Team</label><select id="team" required><option value="">loading teams…</option></select></div>' +
      '<div class="field" id="namef" hidden><label for="sn">Staff name</label><input type="text" id="sn" maxlength="40" autocomplete="username"></div>' +
      '<div class="field"><label for="pp" id="ppl">Passphrase</label><input type="password" id="pp" required autocomplete="current-password"></div>' +
      '<div class="field" id="fnf"><label for="fn">Your first name</label><input type="text" id="fn" required maxlength="40" autocomplete="given-name"></div>' +
      '<div class="notice err" id="lerr" hidden></div><button class="btn g" type="submit">Sign in</button> ' +
      '<button class="btn ghost sm" type="button" id="staff">Teacher or admin? Sign in by name</button></form>';
    main.appendChild(box);
    var sel = $('#team', box), err = $('#lerr', box), staff = false;
    /* Staff accounts are not in the public team list: they sign in with a
       name and a real password instead of a team and a passphrase. */
    $('#staff', box).onclick = function () {
      staff = !staff;
      $('#teamf', box).hidden = staff; $('#namef', box).hidden = !staff; $('#fnf', box).hidden = staff;
      sel.required = !staff; $('#fn', box).required = !staff; $('#sn', box).required = staff;
      $('#ppl', box).textContent = staff ? 'Password' : 'Passphrase';
      this.textContent = staff ? 'Student? Sign in with your team' : 'Teacher or admin? Sign in by name';
      (staff ? $('#sn', box) : sel).focus();
    };
    api('/api/teams').then(function (teams) {
      teams = Array.isArray(teams) ? teams : (teams && teams.teams) || [];
      var byP = {};
      teams.forEach(function (t) { var p = t.period != null ? t.period : '?'; (byP[p] = byP[p] || []).push(t); });
      sel.innerHTML = '<option value="">choose your team…</option>' + Object.keys(byP).sort(function (a, b) { return cmpNum(+a, +b); }).map(function (p) {
        return '<optgroup label="Period ' + esc(p) + '">' + byP[p].sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); })
          .map(function (t) { return '<option value="' + esc(t.id) + '">' + esc(t.name) + (t.bin != null ? ' (bin ' + esc(t.bin) + ')' : '') + '</option>'; }).join('') + '</optgroup>';
      }).join('');
    }).catch(function (e) { sel.innerHTML = '<option value="">teams unavailable</option>'; err.hidden = false; err.textContent = 'Could not load the team list: ' + e.message; });
    $('#lf', box).onsubmit = function (ev) {
      ev.preventDefault(); err.hidden = true;
      var btn = $('button[type=submit]', box); btn.disabled = true;
      var body = staff ? { name: $('#sn', box).value.trim(), passphrase: $('#pp', box).value }
                       : { team_id: sel.value, passphrase: $('#pp', box).value, first_name: $('#fn', box).value.trim() };
      api('/api/login', { method: 'POST', body: body })
        .then(function (j) {
          S.me = j && j.me ? Object.assign({ ok: true }, j.me) : null;
          return S.me ? null : api('/api/me').then(function (m) { S.me = m; });
        })
        .then(function () { S.local = false; navigate(location.pathname === '/login' ? '/' : location.pathname); })
        .catch(function (e) { btn.disabled = false; err.hidden = false; err.textContent = e.status === 429 ? 'Too many tries; wait a minute.' : e.status === 401 || e.status === 403 ? 'Wrong team or passphrase.' : e.message; });
    };
    return { destroy: function () { } };
  }

  /* ---- view: admin (Surface, teacher/admin) --------------------------- */
  var TABS = [['edges', 'Edges'], ['sessions', "Who's looking"], ['visits', 'Visits'], ['teams', 'Teams'], ['castings', 'Castings'], ['stats', 'Stats']];
  function isTime(k, v) { return isNum(v) && v > 1e9 && /(^|_)(ts|at|seen|time|created|t0|t1|last_ok|expires)$/.test(k); }
  function fmtCell(k, v) {
    if (v == null) return '<span class="muted">–</span>';
    if (typeof v === 'boolean') return v ? 'yes' : 'no';
    if (isTime(k, v)) return esc(dateTime(v)) + ' <span class="muted">(' + ago(v) + ')</span>';
    if (typeof v === 'object') return '<span class="mono">' + esc(JSON.stringify(v)) + '</span>';
    return esc(v);
  }
  function table(rows, opts) {
    opts = opts || {};
    if (!Array.isArray(rows)) { if (rows && typeof rows === 'object') rows = Object.keys(rows).map(function (k) { return Object.assign({ key: k }, typeof rows[k] === 'object' ? rows[k] : { value: rows[k] }); }); else rows = []; }
    if (!rows.length) return '<div class="empty">nothing here yet</div>';
    var cols = opts.cols || [];
    rows.forEach(function (r) { Object.keys(r).forEach(function (k) { if (cols.indexOf(k) < 0 && !(opts.hide && opts.hide.indexOf(k) >= 0)) cols.push(k); }); });
    return '<div class="tablewrap"><table><thead><tr>' + cols.map(function (c) { return '<th>' + esc(c.replace(/_/g, ' ')) + '</th>'; }).join('') + (opts.actions ? '<th></th>' : '') + '</tr></thead><tbody>' +
      rows.map(function (r) { return '<tr>' + cols.map(function (c) { return '<td class="' + (isNum(r[c]) && !isTime(c, r[c]) ? 'num' : '') + '">' + fmtCell(c, r[c]) + '</td>'; }).join('') + (opts.actions ? '<td>' + opts.actions(r) + '</td>' : '') + '</tr>'; }).join('') +
      '</tbody></table></div>';
  }
  function kv(obj) {
    if (!obj || typeof obj !== 'object') return '<div class="empty">nothing here yet</div>';
    return '<dl class="kv">' + Object.keys(obj).map(function (k) { return '<dt>' + esc(k.replace(/_/g, ' ')) + '</dt><dd>' + fmtCell(k, obj[k]) + '</dd>'; }).join('') + '</dl>';
  }

  function viewAdmin(main, r) {
    var role = S.me && S.me.role, isAdmin = role === 'admin';
    if (S.local || !(role === 'teacher' || isAdmin)) {
      main.appendChild(el('div', 'card empty', S.local ? 'There is no admin page on a classroom Burrow: everything here is open, and teams live in the cloud.' : 'This page is for teachers.'));
      return { destroy: function () { } };
    }
    var tab = r.tab, timers = [];
    var tabs = el('div', 'tabs');
    tabs.setAttribute('role', 'tablist');
    tabs.innerHTML = TABS.filter(function (t) { return t[0] !== 'teams' && t[0] !== 'castings' || isAdmin; })
      .map(function (t) { return '<button type="button" role="tab" data-tab="' + t[0] + '" class="' + (t[0] === tab ? 'on' : '') + '" aria-selected="' + (t[0] === tab) + '">' + t[1] + '</button>'; }).join('');
    main.appendChild(tabs);
    Array.prototype.forEach.call(tabs.querySelectorAll('button'), function (b) { b.onclick = function () { navigate('/admin/' + b.dataset.tab); }; });
    var body = el('div', 'card'); main.appendChild(body);
    function fail(e) { body.innerHTML = '<div class="notice err">' + esc(e.message) + '</div>'; }
    function every(ms, fn) { fn(); timers.push(setInterval(fn, ms)); }

    if (tab === 'edges') api('/api/admin/edges').then(function (j) {
      var rows = Array.isArray(j) ? j : (j && (j.edges || j.rows)) || j;
      body.innerHTML = '<h3>Burrows</h3>' + table(rows);
    }).catch(fail);

    else if (tab === 'sessions') every(30000, function () {
      api('/api/admin/sessions').then(function (j) {
        var rows = Array.isArray(j) ? j : (j && (j.sessions || j.rows)) || [];
        body.innerHTML = '<h3>Signed in during the last 10 minutes <small class="muted">(refreshes every 30 s · ' + rows.length + ')</small></h3>' +
          table(rows.map(function (s) { return { first_name: s.first_name, team: s.team_name || (s.team && s.team.name) || s.team, period: s.period || (s.team && s.team.period), role: s.role, last_seen: s.last_seen, since: s.created }; }));
      }).catch(fail);
    });

    else if (tab === 'visits') api('/api/admin/visits').then(function (j) {
      var counts = (j && (j.counts || j.per_team)) || [], recent = (j && (j.recent || j.visits)) || (Array.isArray(j) ? j : []);
      if (!Array.isArray(counts)) counts = Object.keys(counts).map(function (k) { return { team: k, visits: counts[k] }; });
      body.innerHTML = '<h3>Views per team</h3>' + table(counts) + '<h3 style="margin-top:18px">Recent page views</h3>' + table(recent, { hide: ['ip_hash', 'ip'] });
    }).catch(fail);

    else if (tab === 'teams') teamsTab(body);

    else if (tab === 'castings') {
      var today = new Date(), day = today.getFullYear() + '-' + pad2(today.getMonth() + 1) + '-' + pad2(today.getDate());
      body.innerHTML = '<div class="toolbar"><label for="croom">room</label><select id="croom"><option value="">all</option><option>1</option><option>2</option><option>3</option></select>' +
        '<label for="cday">day</label><input type="date" id="cday" value="' + day + '"><button class="btn sm" id="cgo" type="button">List</button></div><div id="clist"></div>';
      function listCastings() {
        var room = $('#croom', body).value, d = $('#cday', body).value;
        $('#clist', body).innerHTML = '<div class="empty">loading…</div>';
        api('/api/admin/castings?room=' + encodeURIComponent(room) + '&day=' + encodeURIComponent(d)).then(function (j) {
          var rows = Array.isArray(j) ? j : (j && (j.castings || j.rows)) || [];
          $('#clist', body).innerHTML = table(rows, { cols: ['id', 'room', 'rows', 'size', 't0', 't1', 'verified_at'], actions: function (c) {
            return c.id ? '<a class="btn sm" href="/api/admin/castings/' + encodeURIComponent(c.id) + '" download="' + esc(c.id) + '.jsonl.gz">download</a>' : '';
          } });
        }).catch(function (e) { $('#clist', body).innerHTML = '<div class="notice err">' + esc(e.message) + '</div>'; });
      }
      $('#cgo', body).onclick = listCastings; listCastings();
    }

    else if (tab === 'stats') api('/api/admin/stats').then(function (j) { body.innerHTML = '<h3>Cloud stats</h3>' + kv(j); }).catch(fail);

    else body.innerHTML = '<div class="empty">unknown tab</div>';

    return { destroy: function () { timers.forEach(clearInterval); } };
  }

  function teamsTab(body) {
    var passBlock = '';
    function render() {
      api('/api/admin/teams').then(function (j) {
        var rows = Array.isArray(j) ? j : (j && (j.teams || j.rows)) || [];
        rows.sort(function (a, b) { return cmpNum(a.period, b.period) || cmpNum(a.bin, b.bin); });
        body.innerHTML = '<h3>Teams <small class="muted">(' + rows.length + ')</small></h3>' +
          table(rows, { hide: ['passphrase_hash', 'hash'], actions: function (t) {
            return '<button class="btn sm ghost" data-act="reset" data-id="' + esc(t.id) + '" type="button">reset passphrase</button> ' +
              (t.disabled ? '' : '<button class="btn sm r" data-act="disable" data-id="' + esc(t.id) + '" data-name="' + esc(t.name) + '" type="button">disable</button>');
          } }) +
          '<div id="passout">' + passBlock + '</div>' +
          '<h3 style="margin-top:20px">Add a team</h3><form id="newteam" class="row2">' +
          '<div><label for="tn">name</label><input id="tn" type="text" required></div><div><label for="tp">period</label><input id="tp" type="number" min="1" max="9" required style="width:70px"></div>' +
          '<div><label for="tb">bin</label><input id="tb" type="number" min="1" required style="width:70px"></div><div><label for="tr">room</label><input id="tr" type="number" min="1" max="3" required style="width:70px"></div>' +
          '<button class="btn g" type="submit">Create</button></form>' +
          '<h3 style="margin-top:20px">Import CSV</h3><p class="muted">One team per line: <code>team,period,bin,room</code>. Every imported team gets a fresh passphrase; they are shown once, below.</p>' +
          '<textarea id="csv" placeholder="Dirt Vader,3,7,1&#10;Compost Malone,3,8,1"></textarea><div style="margin-top:8px"><button class="btn" id="imp" type="button">Import</button></div>';
        Array.prototype.forEach.call(body.querySelectorAll('button[data-act]'), function (b) {
          b.onclick = function () {
            var id = b.dataset.id;
            if (b.dataset.act === 'reset') {
              api('/api/admin/teams/' + encodeURIComponent(id) + '/reset', { method: 'POST', body: {} }).then(function (j) { showPass([j], 'New passphrase'); }).catch(alertErr);
            } else if (confirm('Disable "' + b.dataset.name + '"? Their passphrase stops working.')) {
              api('/api/admin/teams/' + encodeURIComponent(id), { method: 'DELETE' }).then(render).catch(alertErr);
            }
          };
        });
        $('#newteam', body).onsubmit = function (ev) {
          ev.preventDefault();
          api('/api/admin/teams', { method: 'POST', body: { name: $('#tn', body).value.trim(), period: +$('#tp', body).value, bin: +$('#tb', body).value, room: +$('#tr', body).value } })
            .then(function (j) { showPass([j], 'New team'); }).catch(alertErr);
        };
        $('#imp', body).onclick = function () {
          var csv = $('#csv', body).value.trim(); if (!csv) return;
          api('/api/admin/teams/import', { method: 'POST', body: csv, ctype: 'text/csv' }).then(function (j) {
            var list = Array.isArray(j) ? j : (j && (j.teams || j.created || j.passphrases)) || [];
            if (!Array.isArray(list) && typeof list === 'object') list = Object.keys(list).map(function (k) { return { name: k, passphrase: list[k] }; });
            showPass(list, 'Imported ' + list.length + ' teams');
          }).catch(alertErr);
        };
        wirePrint();
      }).catch(function (e) { body.innerHTML = '<div class="notice err">' + esc(e.message) + '</div>'; });
    }
    function alertErr(e) { if (e.message !== 'not signed in') alert(e.message); }
    var lastCards = [];
    /* passphrases come back exactly once, so they go in a copyable block and on printable cards */
    function showPass(list, title) {
      lastCards = list.map(function (t) { var tt = t.team || t; return { name: tt.name, period: tt.period, bin: tt.bin, room: tt.room, passphrase: t.passphrase || tt.passphrase }; });
      var text = lastCards.map(function (t) { return [t.name, 'P' + t.period, 'bin ' + t.bin, t.passphrase].join('\t'); }).join('\n');
      passBlock = '<div class="notice info" id="passnote"><b>' + esc(title) + '</b> — write these down now; they are not shown again.<br>' +
        '<pre class="pass" id="passtext">' + esc(text) + '</pre>' +
        '<button class="btn sm" id="copypass" type="button">Copy</button> <button class="btn sm ghost" id="printcards" type="button">Print cards</button></div>';
      render();
    }
    function wirePrint() {
      var cp = $('#copypass', body), pr = $('#printcards', body);
      if (cp) cp.onclick = function () {
        var t = $('#passtext', body).textContent;
        var done = function () { cp.textContent = 'Copied'; setTimeout(function () { cp.textContent = 'Copy'; }, 1500); };
        if (navigator.clipboard) navigator.clipboard.writeText(t).then(done, function () { selectText($('#passtext', body)); });
        else selectText($('#passtext', body));
      };
      if (pr) pr.onclick = function () {
        var old = $('#cards-print'); if (old) old.remove();
        var sec = el('section', '', ''); sec.id = 'cards-print';
        sec.innerHTML = '<h2>Team cards <button class="btn sm ghost" id="closecards" type="button">close</button></h2><div class="cards">' + lastCards.map(function (t) {
          return '<div class="tcard"><div class="n">' + esc(t.name) + '</div><div class="m">Period ' + esc(t.period) + ' · Bin ' + esc(t.bin) + ' · Room ' + esc(t.room) + '</div>' +
            '<div class="p">' + esc(t.passphrase) + '</div><div class="u">' + esc(location.origin) + '/login · pick your team, type the passphrase and your first name</div></div>';
        }).join('') + '</div>';
        $('#view').appendChild(sec);
        document.body.classList.add('print-cards');
        $('#closecards').onclick = function () { document.body.classList.remove('print-cards'); sec.remove(); };
        setTimeout(function () { window.print(); }, 50);
      };
    }
    function selectText(node) { var r = document.createRange(); r.selectNodeContents(node); var s = getSelection(); s.removeAllRanges(); s.addRange(r); }
    render();
  }

  /* ---- view: about ----------------------------------------------------- */
  function viewAbout(main) {
    var box = el('div', 'card');
    box.innerHTML = '<h1>About Mission Control</h1>' +
      '<p>Every worm bin has a small computer (a <b>Bin</b>) that reads its sensors once a minute and posts them to the classroom <b>Burrow</b> (a Raspberry Pi). ' +
      'The Burrow keeps every reading on its own memory card in sealed 15-minute blocks called <b>castings</b>, copies them to the other classrooms\' Burrows, and uploads them to the cloud (<b>the Surface</b>) whenever the school has internet.</p>' +
      '<h2>What the colors mean</h2><div class="swatches">' +
      '<div class="swatch" style="border-color:var(--ok)"><b>NOMINAL</b> (green): air temp 15–27 °C, soil moisture 25 % or more, every part reporting.</div>' +
      '<div class="swatch" style="border-color:var(--warn)"><b>WARN</b> (orange): air temp above 27 °C or below 15 °C, soil moisture under 25 %, or a sensor part not responding.</div>' +
      '<div class="swatch" style="border-color:var(--alarm)"><b>ALARM</b> (red): air temp above 30 °C or below 10 °C, or soil moisture under 15 %. Worms are in trouble; go look.</div>' +
      '<div class="swatch" style="border-color:var(--stale)"><b>STALE</b> (grey, striped): no reading for 3 minutes. The Bin may be off, or off the Wi-Fi.</div></div>' +
      '<h2>Pages</h2><ul><li><a href="/">Wall</a>: one tile per bin, grouped by room and period. Click a tile for its history. The projector button makes everything bigger.</li>' +
      '<li><a href="/feed">Live</a>: every reading as it arrives, with a sparkline per bin.</li>' +
      '<li>Bin pages show 6 hours to 30 days of history. Each point is a 5-minute (or hourly) bucket: the line is the average and the shaded band is the min–max inside that bucket. Gaps in the line are gaps in the data.</li></ul>' +
      '<h2>Where the data goes</h2><p>Bin → Burrow (this classroom, kept 7 days as castings, longer as 5-minute summaries) → the other Burrows (mirrors) → the Surface at <a href="https://whs.makerlabkids.com">whs.makerlabkids.com</a> (raw castings in storage, summaries in a database). ' +
      'Nothing is deleted from a Burrow until the cloud has confirmed it holds an identical copy.</p>' +
      '<p class="muted">You are looking at ' + (S.local ? 'a classroom Burrow (' + esc(Object.keys(S.edges).join(', ') || 'local') + '): open to anyone in the room, no login.' : 'the Surface: the cloud copy, with team logins.') + '</p>';
    main.appendChild(box);
    return { destroy: function () { } };
  }

  /* ---- boot ----------------------------------------------------------- */
  function projector(on) {
    document.body.classList.toggle('projector', on);
    $('#proj').classList.toggle('on', on); $('#proj').setAttribute('aria-pressed', on);
    try { localStorage.setItem(LS_PROJECTOR, on ? '1' : ''); } catch (e) { }
  }
  $('#proj').onclick = function () { projector(!document.body.classList.contains('projector')); };
  try { if (localStorage.getItem(LS_PROJECTOR) === '1') projector(true); } catch (e) { }

  function whoami() {
    return fetch('/api/me', { credentials: 'same-origin', cache: 'no-store' }).then(function (r) {
      if (r.status === 401) return { ok: false };
      return r.json();
    }).catch(function () { return { ok: true, role: 'local', local: true, offline: true }; });   // no API at all: behave like a Burrow and let polling complain
  }
  whoami().then(function (me) {
    S.me = me; S.local = !!me.local;
    render();
    // a cookie can expire while the tab sits on a projector: re-check every 5 minutes on the Surface
    if (!S.local) setInterval(function () { whoami().then(function (m) { if (m.offline) return; var was = S.me && S.me.ok; S.me = m; if (was !== !!m.ok) render(); }); }, 300000);
  });
})();
