// Messages for the screen: five slots (three for the team, two for the teacher).
//
// One widget, three doors, one engine (picolab.Messages on the board):
//   * the board's own page      -> GET /msg?...&pin=     (the default transport)
//   * the website's bin page    -> POST /api/messages    (app.js passes a transport; the
//                                  message rides down through a Burrow, the board acks it)
//   * the Bluetooth page        -> "/msg?...&pin=\n" over the UART service (bluetooth.html)
//
// A slot has a title and up to five lines of 16 characters, and either a start and/or end
// time or a number of showings (blank: forever). "At power-on" slots show in the power-on
// sequence instead of after the worm shows. The screen shows one slot after each worm show,
// taking the live slots in turn.
//
//   Msg.create(el, {
//     send: function (query, cb) {...},   // query: "slot=1&title=..." ("" loads); cb(ok, json)
//     canEdit: function (i) {...},        // slot index 0-4 editable? default: all
//     open: true,                         // false: load at once (no Open button)
//     title, hint
//   });
//
// The default transport keeps the PIN in this browser for this board ('pin:' + host, the same
// key the dashboard and cal.js use), so it is typed once per phone.
//
// Who: before the editor opens (board and Bluetooth doors), the person sets their name once on
// this device and is told it is logged with every change. The board keeps the name against a
// random device id ('who:id') and never takes another from that device; only the teacher PIN
// renames it. The website door (identity: false) uses the real login instead.

window.Msg = (function () {
  var SLOTS = 5, TEAM = 3, LINES = 5, WIDTH = 16;
  var styled = false;
  function injectStyle() {
    if (styled) return; styled = true;
    var s = document.createElement('style');
    s.textContent =
      '.msg-head{font-size:12px;letter-spacing:1px;color:#94a3b8;font-weight:700;margin-bottom:4px}' +
      '.msg-hint{font-size:12px;color:#94a3b8;margin-bottom:8px}' +
      '.msg-slots{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}' +
      '.msg-slot{background:#0f172a;border:1px solid #334155;border-radius:10px;padding:8px}' +
      '.msg-slot.msg-ro{opacity:.75}' +
      '.msg-slot h4{margin:0 0 6px 0;font-size:12px;color:#94a3b8;letter-spacing:1px}' +
      '.msg-slot h4 span{float:right;font-weight:normal;color:#86efac}' +
      '.msg-in{display:block;width:100%;box-sizing:border-box;background:#1e293b;color:#f8fafc;border:1px solid #334155;border-radius:6px;padding:4px 6px;font-size:13px;font-family:ui-monospace,Menlo,monospace;margin:3px 0}' +
      '.msg-in.msg-title{font-weight:700}' +
      '.msg-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:12px;color:#94a3b8;margin:5px 0}' +
      '.msg-row input{background:#1e293b;color:#f8fafc;border:1px solid #334155;border-radius:6px;padding:3px 5px;font-size:12px}' +
      '.msg-row input[type=number]{width:4em}' +
      '.msg-b{background:#334155;color:#f8fafc;border:0;border-radius:8px;padding:5px 10px;font-size:12px;font-weight:700;cursor:pointer}' +
      '.msg-b.msg-save{background:#14532d;color:#86efac}' +
      '.msg-b:disabled{opacity:.5;cursor:default}' +
      '.msg-note{font-size:11px;color:#94a3b8;min-height:14px;margin-top:4px}' +
      '.msg-msg{font-size:12px;color:#94a3b8;margin-top:6px}' +
      '.msg-who{font-size:12px;color:#94a3b8;margin:6px 0 10px}.msg-who b{color:#e2e8f0}.msg-who a{color:#93c5fd;cursor:pointer;margin-left:8px}' +
      '.msg-gate{background:#0f172a;border:1px solid #334155;border-radius:10px;padding:10px;max-width:420px}' +
      '.msg-gate p{font-size:13px;margin:0 0 8px}.msg-gate input{width:60%;margin-right:6px}' +
      '.msg-log{font-size:11px;color:#94a3b8;margin-top:10px}.msg-log div{padding:2px 0;border-top:1px solid #1e293b}.msg-log b{color:#cbd5e1}';
    document.head.appendChild(s);
  }
  // The board's door: GET /msg?... with the PIN this browser keeps for this host.
  function pinFetch(url, cb) {
    var k = 'pin:' + location.host, pin = null;
    try { pin = localStorage.getItem(k); } catch (e) {}
    if (!pin) { pin = prompt('This board is locked. Its PIN?'); if (!pin) { cb && cb(false); return; } try { localStorage.setItem(k, pin); } catch (e) {} }
    fetch(url + (url.indexOf('?') < 0 ? '?' : '&') + 'pin=' + encodeURIComponent(pin), { cache: 'no-store' })
      .then(function (r) {
        if (r.status === 403) { try { localStorage.removeItem(k); } catch (e) {} r.json().then(function (j) { alert(j.locked ? 'Too many wrong PINs: wait a minute.' : 'Wrong PIN.'); }).catch(function () {}); cb && cb(false); return; }
        if (!r.ok) { cb && cb(false); return; }
        r.json().then(function (j) { cb && cb(true, j); }).catch(function () { cb && cb(false); });
      }).catch(function () { cb && cb(false); });
  }
  function boardSend(query, cb) { pinFetch('/msg' + (query ? '?' + query : ''), cb); }

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function toLocal(ts) {                 // unix seconds -> datetime-local value, this phone's zone
    if (!ts) return '';
    var d = new Date(ts * 1000);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function fromLocal(v) {                // datetime-local value -> unix seconds (0 when blank)
    if (!v) return 0;
    var t = new Date(v).getTime();
    return isNaN(t) ? 0 : Math.floor(t / 1000);
  }
  function when(ts) { return ts ? new Date(ts * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : ''; }
  function store(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }
  function fetchKey(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function deviceId() {
    var id = fetchKey('who:id');
    if (!id) { id = 'd' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36); store('who:id', id); }
    return id;
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function create(el, cfg) {
    cfg = cfg || {};
    var send0 = cfg.send || boardSend;
    var identity = cfg.identity !== false;           // the board and Bluetooth doors: a name per device
    var me = identity ? deviceId() : null;
    function send(q, cb, ctx) { send0(identity ? (q ? q + '&' : '') + 'me=' + encodeURIComponent(me) : q, cb, ctx); }
    var canEdit = cfg.canEdit || function () { return true; };
    var shown = [];                                  // what the page last displayed per slot (for the conflict check)
    injectStyle();
    el.innerHTML = '';
    var head = document.createElement('div'); head.className = 'msg-head'; head.textContent = cfg.title || 'MESSAGES ON THE SCREEN';
    var hint = document.createElement('div'); hint.className = 'msg-hint';
    hint.textContent = cfg.hint || ('Five slots: three for the team, two for the teacher. After each worm show the screen shows the next live one for a few seconds: ' +
      'a title and up to five lines, 16 characters each. Give it a start and/or end time, or a number of showings; blank means forever. ' +
      '"At power-on" slots show when the board starts instead.');
    var who = document.createElement('div'); who.className = 'msg-who';
    var gate = document.createElement('div'); gate.className = 'msg-gate'; gate.hidden = true;
    var slots = document.createElement('div'); slots.className = 'msg-slots';
    var msg = document.createElement('div'); msg.className = 'msg-msg';
    var logbox = document.createElement('div'); logbox.className = 'msg-log';
    var open = document.createElement('button'); open.className = 'msg-b'; open.textContent = cfg.openLabel || 'Open (needs the PIN)';
    el.appendChild(head); el.appendChild(hint); el.appendChild(open); el.appendChild(who); el.appendChild(gate); el.appendChild(slots); el.appendChild(msg); el.appendChild(logbox);
    var ids = 'msg' + Math.floor(Math.random() * 1e6) + '_';
    function $(k) { return document.getElementById(ids + k); }

    function slotHtml(i) {
      var ro = !canEdit(i), dis = ro ? ' disabled' : '';
      var h = '<div class="msg-slot' + (ro ? ' msg-ro' : '') + '"><h4>' + (i < TEAM ? 'SLOT ' + (i + 1) : 'TEACHER ' + (i - TEAM + 1)) + ' <span id="' + ids + 'state' + i + '"></span></h4>' +
        '<input class="msg-in msg-title" id="' + ids + 'title' + i + '" maxlength="' + WIDTH + '" placeholder="title (on top, underlined)"' + dis + '>';
      for (var n = 1; n <= LINES; n++) h += '<input class="msg-in" id="' + ids + 'l' + i + '_' + n + '" maxlength="' + WIDTH + '" placeholder="line ' + n + '"' + dis + '>';
      h += '<div class="msg-row">from <input type="datetime-local" id="' + ids + 'start' + i + '"' + dis + '></div>' +
        '<div class="msg-row">until <input type="datetime-local" id="' + ids + 'end' + i + '"' + dis + '></div>' +
        '<div class="msg-row">or show <input type="number" min="1" id="' + ids + 'count' + i + '" placeholder="&infin;"' + dis + '> times' +
        ' <label><input type="checkbox" id="' + ids + 'boot' + i + '"' + dis + '> at power-on</label></div>' +
        (ro ? '<div class="msg-row">set by the teacher on the website</div>'
            : '<div class="msg-row"><button class="msg-b msg-save" data-i="' + i + '">Save</button><button class="msg-b msg-clear" data-i="' + i + '">Clear</button></div>') +
        '<div class="msg-note" id="' + ids + 'note' + i + '"></div></div>';
      return h;
    }
    function render(j) {
      if (!slots.children.length) {
        var h = '';
        for (var i = 0; i < SLOTS; i++) h += slotHtml(i);
        slots.innerHTML = h;
        var bs = slots.getElementsByTagName('button');
        for (var b = 0; b < bs.length; b++) bs[b].onclick = onButton;
      }
      for (var i = 0; i < SLOTS; i++) {
        var s = (j.slots || [])[i] || {}, lines = s.lines || [];
        shown[i] = (j.slots || [])[i] || null;
        $('title' + i).value = s.title || '';
        for (var n = 1; n <= LINES; n++) $('l' + i + '_' + n).value = lines[n - 1] || '';
        $('start' + i).value = toLocal(s.start);
        $('end' + i).value = toLocal(s.end);
        $('count' + i).value = s.count || '';
        $('boot' + i).checked = !!s.boot;
        var note = '', state = '', st = j.status && j.status[i + 1], q = j.queued && j.queued[i];
        if (st && st.pending && j.queued !== undefined) {   // the website's copy is still on its way: say what is coming
          note = q ? 'waiting for the bin: "' + (q.title || (q.lines || [])[0] || '') + '"' : 'clearing: waiting for the bin';
        }
        if (s.title || lines.length) {
          if (j.active) state = j.active[i] ? (s.boot ? 'at power-on' : 'on the screen') : 'not showing';
          else if (st) state = st.pending ? 'waiting for the bin' : (st.result === 'refused' ? 'refused' : (s.boot ? 'at power-on' : 'on the board'));
          if (s.count) note += (note ? '. ' : '') + 'shown ' + (s.shown || 0) + ' of ' + s.count + (s.shown >= s.count ? ': done' : '');
          else if (s.shown) note += (note ? '. ' : '') + 'shown ' + s.shown + ' times';
          if (s.start && j.now < s.start) note += (note ? '. ' : '') + 'Starts ' + when(s.start);
          if (s.end && j.now > s.end) note += (note ? '. ' : '') + 'Ended ' + when(s.end);
          if ((s.start || s.end) && j.clk === 'none') note += (note ? '. ' : '') + 'The board has no clock yet: save once and it takes this phone\'s.';
          if (st && st.set_by) note += (note ? '. ' : '') + 'Set by ' + st.set_by + (st.set_at ? ' ' + when(st.set_at) : '');
          if (s.by) note += (note ? '. ' : '') + 'Set by ' + s.by + (s.via ? ' over ' + s.via : '') + (s.at ? ' ' + when(s.at) : '');
          if (st && st.result === 'refused') note += (note ? '. ' : '') + 'The board refused it: wrong PIN. Save again with the right one.';
          if (st && st.pending) note += (note ? '. ' : '') + 'It lands on the board within about two minutes of its next push.';
        } else {
          state = 'empty';
          if (st && st.pending) note = 'clearing: waiting for the bin';
        }
        $('state' + i).textContent = state;
        $('note' + i).textContent = note;
      }
      if (j.clk === 'none') msg.textContent = 'The board does not know the time yet (no Burrow seen). Saving any slot sets it from this phone.';
      else if (j.clk) msg.textContent = 'Board clock: ' + when(j.now) + (j.clk === 'est' ? ' (estimated)' : '');
      else if (j.board_seen) msg.textContent = 'What the board reported ' + when(j.board_seen) + ' (revision ' + (j.board && j.board.rev) + '). A save is refused if the board changed since.';
      else if (j.queued !== undefined) msg.textContent = 'The board has not reported its slots yet (it needs the new code, and a Burrow with it); these are the website\'s copies.';
      else msg.textContent = '';
      if (j.changes && j.changes.length) {
        logbox.innerHTML = '<b>Recent changes on this board</b>' + j.changes.map(function (c) {
          return '<div>' + esc(when(c.ts) || 'no clock') + ' · <b>' + esc(c.by) + '</b> over ' + esc(c.via) + ' · ' + esc(c.what) + (c.slot && c.slot !== '-' ? ' slot ' + esc(c.slot) : '') + (c.title ? ' "' + esc(c.title) + '"' : '') + '</div>';
        }).join('');
      } else logbox.innerHTML = '';
      drawWho(j);
    }
    function drawWho(j) {
      if (!identity) { who.innerHTML = ''; return; }
      if (j.me) store('who:name', j.me);
      who.innerHTML = j.me ? 'You are <b>' + esc(j.me) + '</b> on this device. Every change you make is recorded under that name.' +
        (j.teacher_pin ? '<a id="' + ids + 'rename">teacher: change the name</a>' : '') : '';
      var a = $('rename');
      if (a) a.onclick = function () {
        var tp = prompt('The teacher PIN?'); if (!tp) return;
        var n = prompt('The new name for this device?', j.me || ''); if (!n) return;
        send('name=' + encodeURIComponent(n.trim()) + '&tpin=' + encodeURIComponent(tp), function (ok, r) {
          if (ok && r && r.me) { render(r); } else alert('Not changed' + (r && r.error ? ': ' + r.error : '.'));
        });
      };
    }
    function askName(j) {
      slots.innerHTML = ''; logbox.innerHTML = ''; who.innerHTML = '';
      gate.hidden = false;
      gate.innerHTML = '<p><b>Before you can post to the screen, tell the board who you are.</b></p>' +
        '<p>Your name is recorded on the board with every message you set or clear, and shown next to it. ' +
        'It cannot be changed from this phone or laptop afterwards; only a teacher can change it.</p>' +
        '<input class="msg-in" id="' + ids + 'whoname" maxlength="32" placeholder="first and last name" style="display:inline-block">' +
        '<button class="msg-b msg-save" id="' + ids + 'whogo">That\'s me</button><div class="msg-note" id="' + ids + 'whonote"></div>';
      $('whogo').onclick = function () {
        var n = $('whoname').value.trim();
        if (n.length < 2) { $('whonote').textContent = 'Type your name first.'; return; }
        if (!confirm('Record "' + n + '" as the name on this device? It is logged with every change and only a teacher can change it.')) return;
        $('whonote').textContent = 'telling the board...';
        send('name=' + encodeURIComponent(n), function (ok, r) {
          if (ok && r && r.me) { store('who:name', r.me); gate.hidden = true; render(r); }
          else $('whonote').textContent = 'The board did not take it' + (r && r.error ? ': ' + r.error : '.');
        });
      };
    }
    function onButton(ev) {
      var i = parseInt(ev.target.getAttribute('data-i'), 10), q = 'slot=' + (i + 1) + '&now=' + Math.floor(Date.now() / 1000);
      if (ev.target.className.indexOf('msg-clear') >= 0) {
        if (!confirm('Clear ' + (i < TEAM ? 'slot ' + (i + 1) : 'teacher slot ' + (i - TEAM + 1)) + '?')) return;
        q += '&clear=1';
      } else {
        var title = $('title' + i).value.trim(), any = !!title;
        q += '&title=' + encodeURIComponent(title);
        for (var n = 1; n <= LINES; n++) {
          var v = $('l' + i + '_' + n).value.replace(/\s+$/, '');
          if (v) any = true;
          q += '&l' + n + '=' + encodeURIComponent(v);
        }
        if (!any) { $('note' + i).textContent = 'Type a title or a line first.'; return; }
        var start = fromLocal($('start' + i).value), end = fromLocal($('end' + i).value);
        var count = parseInt($('count' + i).value, 10) || 0;
        if (start && end && end <= start) { $('note' + i).textContent = 'The end is before the start.'; return; }
        if (start) q += '&start=' + start;
        if (end) q += '&end=' + end;
        if (count) q += '&count=' + count;
        if ($('boot' + i).checked) q += '&boot=1';
      }
      $('note' + i).textContent = 'saving...';
      send(q, function (ok, j) {
        if (ok && j && !j.error) render(j);
        else if (j && j.conflict) {
          // the board has something else in this slot: keep the typing, show theirs, let Save go through next time
          var t = j.theirs, what = t ? ('"' + (t.title || '') + (t.lines && t.lines.length ? ' | ' + t.lines.join(' | ') : '') + '"' + (t.by ? ', set by ' + t.by + (t.via ? ' over ' + t.via : '') : '')) : 'nothing (it was cleared)';
          shown[i] = t || null;
          $('note' + i).textContent = 'Not saved: this slot changed on the board since the page loaded. It now holds ' + what + '. Your text is kept; press Save again to replace it.';
        }
        else $('note' + i).textContent = 'Not saved' + (j && j.error ? ': ' + j.error : '.');
      }, { slot: i + 1, seen: shown[i] || null });
    }
    function load() {
      msg.textContent = 'asking the board...';
      // the name this device already told some board: offer it to this one too (first name wins, on the board)
      var known = identity ? fetchKey('who:name') : null;
      send(known ? 'name=' + encodeURIComponent(known) : '', function (ok, j) {
        if (ok && j && j.slots) {
          open.style.display = 'none';
          if (identity && !j.me) { msg.textContent = ''; askName(j); } else render(j);
        } else msg.textContent = cfg.failText || 'Could not read the messages (older board software, or no PIN).';
      });
    }
    open.onclick = load;
    if (cfg.open === false) load();
    return { reload: load };
  }
  // query string ("slot=1&title=...") -> the object the website's API takes
  function queryToBody(q) {
    var p = new URLSearchParams(q), b = { slot: parseInt(p.get('slot'), 10) };
    if (p.get('clear')) { b.clear = true; return b; }
    b.title = p.get('title') || ''; b.lines = [];
    for (var n = 1; n <= LINES; n++) b.lines.push(p.get('l' + n) || '');
    if (p.get('start')) b.start = parseInt(p.get('start'), 10);
    if (p.get('end')) b.end = parseInt(p.get('end'), 10);
    if (p.get('count')) b.count = parseInt(p.get('count'), 10);
    if (p.get('boot')) b.boot = true;
    return b;
  }
  return { create: create, pinFetch: pinFetch, queryToBody: queryToBody, SLOTS: SLOTS, TEAM: TEAM };
})();
