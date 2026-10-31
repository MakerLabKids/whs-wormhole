// Messages for the screen: three slots a team fills in from the dashboard.
//
// One widget, every dashboard, one engine (picolab.Messages on the board:
// msg.json + the /msg route, PIN-gated like every change). A slot has a
// title and up to five lines of 16 characters, and either a start and/or
// end time or a number of showings (blank: forever). The screen shows one
// slot after each worm show, taking the live slots in turn.
//
//   Msg.create(el);          // renders the card; "Open" asks the board (and the PIN, once)
//
// The PIN is kept in this browser for this board ('pin:' + host, the same
// key the dashboard and cal.js use), so it is typed once per phone.

window.Msg = (function () {
  var SLOTS = 3, LINES = 5, WIDTH = 16;
  var styled = false;
  function injectStyle() {
    if (styled) return; styled = true;
    var s = document.createElement('style');
    s.textContent =
      '.msg-head{font-size:12px;letter-spacing:1px;color:#94a3b8;font-weight:700;margin-bottom:4px}' +
      '.msg-hint{font-size:12px;color:#94a3b8;margin-bottom:8px}' +
      '.msg-slots{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}' +
      '.msg-slot{background:#0f172a;border:1px solid #334155;border-radius:10px;padding:8px}' +
      '.msg-slot h4{margin:0 0 6px 0;font-size:12px;color:#94a3b8;letter-spacing:1px}' +
      '.msg-slot h4 span{float:right;font-weight:normal;color:#86efac}' +
      '.msg-in{display:block;width:100%;box-sizing:border-box;background:#1e293b;color:#f8fafc;border:1px solid #334155;border-radius:6px;padding:4px 6px;font-size:13px;font-family:ui-monospace,Menlo,monospace;margin:3px 0}' +
      '.msg-in.msg-title{font-weight:700}' +
      '.msg-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:12px;color:#94a3b8;margin:5px 0}' +
      '.msg-row input{background:#1e293b;color:#f8fafc;border:1px solid #334155;border-radius:6px;padding:3px 5px;font-size:12px}' +
      '.msg-row input[type=number]{width:4em}' +
      '.msg-b{background:#334155;color:#f8fafc;border:0;border-radius:8px;padding:5px 10px;font-size:12px;font-weight:700;cursor:pointer}' +
      '.msg-b.msg-save{background:#14532d;color:#86efac}' +
      '.msg-note{font-size:11px;color:#94a3b8;min-height:14px;margin-top:4px}' +
      '.msg-msg{font-size:12px;color:#94a3b8;margin-top:6px}';
    document.head.appendChild(s);
  }
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

  function create(el) {
    injectStyle();
    el.innerHTML = '';
    var head = document.createElement('div'); head.className = 'msg-head'; head.textContent = 'MESSAGES ON THE SCREEN';
    var hint = document.createElement('div'); hint.className = 'msg-hint';
    hint.textContent = 'Three slots. After each worm show the screen shows the next live one for a few seconds: a title and up to five lines, 16 characters each. ' +
      'Give it a start and/or end time, or a number of showings; blank means forever.';
    var slots = document.createElement('div'); slots.className = 'msg-slots';
    var msg = document.createElement('div'); msg.className = 'msg-msg';
    var open = document.createElement('button'); open.className = 'msg-b'; open.textContent = 'Open (needs the PIN)';
    el.appendChild(head); el.appendChild(hint); el.appendChild(open); el.appendChild(slots); el.appendChild(msg);

    function slotHtml(i) {
      var h = '<div class="msg-slot" id="msgslot' + i + '"><h4>SLOT ' + (i + 1) + ' <span id="msgstate' + i + '"></span></h4>' +
        '<input class="msg-in msg-title" id="msgtitle' + i + '" maxlength="' + WIDTH + '" placeholder="title (on top, underlined)">';
      for (var n = 1; n <= LINES; n++) h += '<input class="msg-in" id="msgl' + i + '_' + n + '" maxlength="' + WIDTH + '" placeholder="line ' + n + '">';
      h += '<div class="msg-row">from <input type="datetime-local" id="msgstart' + i + '"></div>' +
        '<div class="msg-row">until <input type="datetime-local" id="msgend' + i + '"></div>' +
        '<div class="msg-row">or show <input type="number" min="1" id="msgcount' + i + '" placeholder="&infin;"> times</div>' +
        '<div class="msg-row"><button class="msg-b msg-save" data-i="' + i + '">Save</button><button class="msg-b msg-clear" data-i="' + i + '">Clear</button></div>' +
        '<div class="msg-note" id="msgnote' + i + '"></div></div>';
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
        document.getElementById('msgtitle' + i).value = s.title || '';
        for (var n = 1; n <= LINES; n++) document.getElementById('msgl' + i + '_' + n).value = lines[n - 1] || '';
        document.getElementById('msgstart' + i).value = toLocal(s.start);
        document.getElementById('msgend' + i).value = toLocal(s.end);
        document.getElementById('msgcount' + i).value = s.count || '';
        var note = '', state = '';
        if (s.title || lines.length) {
          var live = (j.active || [])[i];
          state = live ? 'on the screen' : 'not showing';
          if (s.count) note = 'shown ' + (s.shown || 0) + ' of ' + s.count + (s.shown >= s.count ? ': done' : '');
          else if (s.shown) note = 'shown ' + s.shown + ' times';
          if (s.start && j.now < s.start) note += (note ? '. ' : '') + 'Starts ' + when(s.start);
          if (s.end && j.now > s.end) note += (note ? '. ' : '') + 'Ended ' + when(s.end);
          if ((s.start || s.end) && j.clk === 'none') note += (note ? '. ' : '') + 'The board has no clock yet: save once and it takes this phone\'s.';
        } else state = 'empty';
        document.getElementById('msgstate' + i).textContent = state;
        document.getElementById('msgnote' + i).textContent = note;
      }
      msg.textContent = j.clk === 'none' ? 'The board does not know the time yet (no Burrow seen). Saving any slot sets it from this phone.' :
        'Board clock: ' + when(j.now) + (j.clk === 'est' ? ' (estimated)' : '');
    }
    function onButton(ev) {
      var i = parseInt(ev.target.getAttribute('data-i'), 10), q = 'slot=' + (i + 1) + '&now=' + Math.floor(Date.now() / 1000);
      if (ev.target.className.indexOf('msg-clear') >= 0) {
        if (!confirm('Clear slot ' + (i + 1) + '?')) return;
        q += '&clear=1';
      } else {
        var title = document.getElementById('msgtitle' + i).value.trim(), any = !!title;
        q += '&title=' + encodeURIComponent(title);
        for (var n = 1; n <= LINES; n++) {
          var v = document.getElementById('msgl' + i + '_' + n).value.replace(/\s+$/, '');
          if (v) any = true;
          q += '&l' + n + '=' + encodeURIComponent(v);
        }
        if (!any) { document.getElementById('msgnote' + i).textContent = 'Type a title or a line first.'; return; }
        var start = fromLocal(document.getElementById('msgstart' + i).value), end = fromLocal(document.getElementById('msgend' + i).value);
        var count = parseInt(document.getElementById('msgcount' + i).value, 10) || 0;
        if (start && end && end <= start) { document.getElementById('msgnote' + i).textContent = 'The end is before the start.'; return; }
        if (start) q += '&start=' + start;
        if (end) q += '&end=' + end;
        if (count) q += '&count=' + count;
      }
      document.getElementById('msgnote' + i).textContent = 'saving...';
      pinFetch('/msg?' + q, function (ok, j) {
        if (ok && j && !j.error) render(j);
        else document.getElementById('msgnote' + i).textContent = 'Not saved' + (j && j.error ? ': ' + j.error : '.');
      });
    }
    open.onclick = function () {
      msg.textContent = 'asking the board...';
      pinFetch('/msg', function (ok, j) {
        if (ok && j && j.slots) { open.style.display = 'none'; render(j); }
        else msg.textContent = 'Could not read the messages (older board software, or no PIN).';
      });
    };
    return { reload: open.onclick };
  }
  return { create: create };
})();
