// Shows for a bin's screen, sent from the website (the Surface's /api/shows). The bin's
// Burrow hands them to the board on its next push; the board plays them (lib/pbmshow.py).
//
//   Shows.create(el, {uid, api})   // api(path, {method, body}) -> Promise of JSON (app.js's api)
//
// A show file is a .pbm made on the lab guide's "Make your own show" page (draw in Piskel,
// convert, download). Here the team uploads it, deletes ones they no longer want, and picks
// which shows play and in what order (their own and the ten worm screens), or "everything".

window.Shows = (function () {
  var MAKER = 'https://makerlabkids.github.io/whs-wormhole/shows.html';
  var styled = false;
  function injectStyle() {
    if (styled) return; styled = true;
    var s = document.createElement('style');
    s.textContent =
      '.sh-head{font-size:12px;letter-spacing:1px;color:#94a3b8;font-weight:700;margin-bottom:4px}' +
      '.sh-hint{font-size:12px;color:#94a3b8;margin-bottom:8px}.sh-hint a{color:#7dd3fc}' +
      '.sh-state{font-size:13px;margin:6px 0}.sh-ok{color:#86efac}.sh-wait{color:#fcd34d}.sh-err{color:#fca5a5}' +
      '.sh-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}' +
      '.sh-box{background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:10px;padding:10px}' +
      '.sh-row{display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid #1e293b;font-size:14px}' +
      '.sh-row:last-child{border-bottom:0}.sh-row .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis}' +
      '.sh-row small{color:#94a3b8}.sh-row button{font-size:12px;padding:2px 8px;color:#0f172a;background:#e2e8f0;border:0;border-radius:6px;cursor:pointer}.sh-row button:disabled{opacity:.35;cursor:default}' +
      '.sh-add{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:8px}' +
      '.sh-add input[type=text]{width:11em}';
    document.head.appendChild(s);
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function kb(n) { return (n / 1024).toFixed(n < 10240 ? 1 : 0) + ' KB'; }
  function b64(buf) {
    var u = new Uint8Array(buf), s = '', CH = 0x8000;
    for (var i = 0; i < u.length; i += CH) s += String.fromCharCode.apply(null, u.subarray(i, i + CH));
    return btoa(s);
  }
  function cleanName(s) { return String(s || '').toLowerCase().replace(/\.pbm$/, '').replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 24); }

  function create(root, opt) {
    injectStyle();
    var uid = opt.uid, api = opt.api, data = null, order = null;   // order: the playlist being edited (names)
    root.innerHTML = '<div class="sh-head">SHOWS ON THE SCREEN</div>' +
      '<div class="sh-hint">Pictures and videos for this bin\'s screen. Make one on <a href="' + MAKER + '" target="_blank" rel="noopener">Make your own show</a> ' +
      '(draw in Piskel, then Download the .pbm), add it here, and pick what plays. It reaches the bin within a few minutes.</div>' +
      '<div class="sh-state"></div><div class="sh-cols"><div class="sh-box sh-files"></div><div class="sh-box sh-list"></div></div>';
    var stateEl = root.querySelector('.sh-state'), filesEl = root.querySelector('.sh-files'), listEl = root.querySelector('.sh-list');

    function say(cls, text) { stateEl.className = 'sh-state ' + cls; stateEl.textContent = text; }
    function took(j) { data = j; order = null; draw(); }
    function failed(e) { say('sh-err', (e && e.body && e.body.error) || (e && e.message) || 'that did not work'); }
    function post(body) { body.uid = uid; return api('/api/shows', { method: 'POST', body: body }).then(took).catch(failed); }

    function draw() {
      if (!data) return;
      if (data.on_board) say('sh-ok', data.rev ? 'On the bin: everything below is on its screen.' : 'Nothing sent from the website yet.');
      else say('sh-wait', 'On its way to the bin (it picks changes up on its next push, then plays them from the next show).');
      // own files
      var h = '<div class="sh-head">YOUR SHOWS (' + kb(data.used || 0) + ' of ' + kb(data.limit || 0) + ')</div>';
      if (!data.files.length) h += '<div class="sh-hint">None yet.</div>';
      data.files.forEach(function (f) {
        h += '<div class="sh-row"><span class="n"><b>' + esc(f.name) + '</b> <small>' + (f.frames > 1 ? f.frames + ' frames' : 'picture') +
          ', ' + f.w + '×' + f.h + ', ' + kb(f.size) + (f.set_by ? ', ' + esc(f.set_by) : '') + '</small></span>' +
          '<button type="button" data-del="' + esc(f.name) + '">Delete</button></div>';
      });
      h += '<div class="sh-add"><input type="file" accept=".pbm"><input type="text" placeholder="name" maxlength="24" spellcheck="false"><button type="button" class="btn sm" data-add>Add</button></div>';
      filesEl.innerHTML = h;
      var fileIn = filesEl.querySelector('input[type=file]'), nameIn = filesEl.querySelector('input[type=text]');
      fileIn.onchange = function () { if (fileIn.files[0] && !nameIn.value) nameIn.value = cleanName(fileIn.files[0].name); };
      filesEl.querySelector('[data-add]').onclick = function () {
        var f = fileIn.files[0], name = cleanName(nameIn.value || (f && f.name));
        if (!f) { say('sh-err', 'Pick a .pbm file first (from Make your own show).'); return; }
        if (!name) { say('sh-err', 'Give it a name: letters, numbers and dashes.'); return; }
        say('sh-wait', 'Uploading ' + name + '...');
        f.arrayBuffer().then(function (buf) { return post({ name: name, pbm: b64(buf) }); });
      };
      Array.prototype.forEach.call(filesEl.querySelectorAll('[data-del]'), function (b) {
        b.onclick = function () { if (confirm('Delete ' + b.getAttribute('data-del') + ' from this bin?')) post({ delete: b.getAttribute('data-del') }); };
      });
      drawList();
    }

    function drawList() {
      var all = data.files.map(function (f) { return f.name; }).concat(data.builtins || []);
      var cur = order || (data.list ? data.list.slice() : null);
      var h = '<div class="sh-head">WHAT PLAYS</div>';
      if (!cur) {
        h += '<div class="sh-hint">Everything: the ten worm screens, then your shows A to Z.</div>' +
             '<button type="button" class="btn sm" data-pick>Choose and order them</button>';
        listEl.innerHTML = h;
        listEl.querySelector('[data-pick]').onclick = function () { order = all.slice(); drawList(); };
        return;
      }
      h += '<div class="sh-hint">Ticked ones play, top to bottom, round and round.</div>';
      var rows = cur.concat(all.filter(function (n) { return cur.indexOf(n) < 0; }));
      rows.forEach(function (n, i) {
        var on = cur.indexOf(n) >= 0;
        h += '<div class="sh-row"><input type="checkbox" data-on="' + esc(n) + '"' + (on ? ' checked' : '') + '>' +
          '<span class="n">' + esc(n) + (data.builtins.indexOf(n) >= 0 ? ' <small>worm screen</small>' : '') + '</span>' +
          (on ? '<button type="button" data-up="' + esc(n) + '"' + (cur.indexOf(n) === 0 ? ' disabled' : '') + '>↑</button>' +
                '<button type="button" data-down="' + esc(n) + '"' + (cur.indexOf(n) === cur.length - 1 ? ' disabled' : '') + '>↓</button>' : '') + '</div>';
      });
      h += '<div class="sh-add"><button type="button" class="btn sm" data-save>Save</button>' +
           '<button type="button" class="btn ghost sm" data-default>Play everything</button>' +
           (order ? '<button type="button" class="btn ghost sm" data-cancel>Cancel</button>' : '') + '</div>';
      listEl.innerHTML = h;
      function edit() { if (!order) order = cur.slice(); return order; }
      Array.prototype.forEach.call(listEl.querySelectorAll('[data-on]'), function (c) {
        c.onchange = function () {
          var o = edit(), n = c.getAttribute('data-on'), i = o.indexOf(n);
          if (c.checked && i < 0) o.push(n); else if (!c.checked && i >= 0) o.splice(i, 1);
          drawList();
        };
      });
      function move(n, d) { var o = edit(), i = o.indexOf(n), j = i + d; if (j < 0 || j >= o.length) return; o.splice(i, 1); o.splice(j, 0, n); drawList(); }
      Array.prototype.forEach.call(listEl.querySelectorAll('[data-up]'), function (b) { b.onclick = function () { move(b.getAttribute('data-up'), -1); }; });
      Array.prototype.forEach.call(listEl.querySelectorAll('[data-down]'), function (b) { b.onclick = function () { move(b.getAttribute('data-down'), 1); }; });
      listEl.querySelector('[data-save]').onclick = function () {
        var o = order || cur;
        if (!o.length) { say('sh-err', 'Tick at least one, or choose Play everything.'); return; }
        post({ list: o });
      };
      listEl.querySelector('[data-default]').onclick = function () { post({ list: null }); };
      var c = listEl.querySelector('[data-cancel]');
      if (c) c.onclick = function () { order = null; drawList(); };
    }

    function load() { api('/api/shows?uid=' + encodeURIComponent(uid)).then(took).catch(failed); }
    load();
    return { reload: load };
  }
  return { create: create };
})();
