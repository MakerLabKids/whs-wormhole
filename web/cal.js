// Shared two-point calibration widget for Wormhole dashboards.
//
// One component, every dashboard, one engine (picolab.Calibration on the
// board: cal.json + the /cal route). Capture two known points, tap Apply,
// and the board saves a linear fit and applies it to the readings.
//
// Two flavors, same widget:
//   * FIXED points  - the true values are known (moisture: dry = 0%,
//     wet = 100%). Just "set dry" / "set wet".
//   * ENTERED points - you type the true value at each point (distance:
//     put a target at a measured distance, type it, capture). Set
//     cfg.entered = true.
//
//   Cal.create(el, {
//     title, hint, unit,
//     lowName, lowVal, highName, highVal,   // *Val ignored when entered
//     entered: false,                       // true -> type the true value
//     itemsFrom: function (data) { return [{ id, label, raw }]; }
//   });
//   // each /data tick:  cal.update(data)
//
// The board reports raw fields, lists calibrated ids as data.cal_ids,
// and routes /cal to picolab.Calibration.handle.

window.Cal = (function () {
  var styled = false;
  function injectStyle() {
    if (styled) return; styled = true;
    var s = document.createElement('style');
    s.textContent =
      '.cal-head{font-size:12px;letter-spacing:1px;color:#94a3b8;font-weight:700;margin-bottom:4px}' +
      '.cal-hint{font-size:12px;color:#94a3b8;margin-bottom:8px}' +
      '.cal-row{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:13px;margin:5px 0}' +
      '.cal-lbl{font-weight:700;min-width:66px}' +
      '.cal-now{color:#94a3b8}.cal-now b{color:#e2e8f0}' +
      '.cal-b{background:#334155;color:#f8fafc;border:0;border-radius:8px;padding:5px 10px;font-size:12px;font-weight:700;cursor:pointer}' +
      '.cal-b.cal-apply{background:#14532d;color:#86efac}' +
      '.cal-in{width:52px;background:#0f172a;color:#f8fafc;border:1px solid #334155;border-radius:6px;padding:4px;font-size:12px}' +
      '.cal-cap{font-size:11px;color:#a3e635}' +
      '.cal-badge{font-size:10px;color:#86efac;margin-left:4px}' +
      '.cal-msg{font-size:12px;color:#86efac;min-height:14px;margin-top:4px}';
    document.head.appendChild(s);
  }
  // Every change to the board needs its PIN (its name + the address on its screen).
  function pinFetch(url, cb) {
    var k = 'pin:' + location.host, pin = null;
    try { pin = localStorage.getItem(k); } catch (e) {}
    if (!pin) { pin = prompt('This board is locked. Its PIN?'); if (!pin) { cb && cb(false); return; } try { localStorage.setItem(k, pin); } catch (e) {} }
    fetch(url + (url.indexOf('?') < 0 ? '?' : '&') + 'pin=' + encodeURIComponent(pin), { cache: 'no-store' })
      .then(function (r) {
        if (r.status === 403) { try { localStorage.removeItem(k); } catch (e) {} r.json().then(function (j) { alert(j.locked ? 'Too many wrong PINs: wait a minute.' : 'Wrong PIN.'); }).catch(function () {}); }
        cb && cb(r.ok);
      }).catch(function () { cb && cb(false); });
  }
  function post(q, cb) {
    pinFetch('/cal?' + q, cb);
  }
  function create(el, cfg) {
    injectStyle();
    var caps = {}, live = {}, calIds = [], sig = '', entered = !!cfg.entered;
    el.innerHTML = '';
    var head = document.createElement('div'); head.className = 'cal-head'; head.textContent = cfg.title || 'CALIBRATE';
    var hint = document.createElement('div'); hint.className = 'cal-hint'; hint.textContent = cfg.hint || '';
    var rows = document.createElement('div');
    var msg = document.createElement('div'); msg.className = 'cal-msg';
    el.appendChild(head); el.appendChild(hint); el.appendChild(rows); el.appendChild(msg);

    function point(id, which, name) {
      var inp = entered
        ? '<input class="cal-in" id="calin-' + id + '-' + which + '" placeholder="' + name + '">' : '';
      return inp + '<button class="cal-b" data-id="' + id + '" data-pt="' + which + '">set ' + name + '</button>';
    }
    function refreshCap(id) {
      var c = caps[id] || {}, e = document.getElementById('calcap-' + id);
      if (!e) return;
      var t = '';
      if (c.low) t += cfg.lowName + ' ' + c.low.raw + '→' + c.low.act + '  ';
      if (c.high) t += cfg.highName + ' ' + c.high.raw + '→' + c.high.act;
      e.textContent = t;
    }
    function build(items) {
      rows.innerHTML = '';
      items.forEach(function (it) {
        var row = document.createElement('div'); row.className = 'cal-row';
        row.innerHTML =
          '<span class="cal-lbl">' + it.label + '<span class="cal-badge" id="calbadge-' + it.id + '"></span></span>' +
          '<span class="cal-now">now <b id="calnow-' + it.id + '">--</b> ' + (cfg.unit || '') + '</span>' +
          point(it.id, 'low', cfg.lowName) + point(it.id, 'high', cfg.highName) +
          '<button class="cal-b cal-apply" data-id="' + it.id + '" data-apply="1">apply</button>' +
          '<button class="cal-b" data-id="' + it.id + '" data-reset="1">reset</button>' +
          '<span class="cal-cap" id="calcap-' + it.id + '"></span>';
        rows.appendChild(row);
      });
      var bs = rows.getElementsByTagName('button');
      for (var i = 0; i < bs.length; i++) bs[i].onclick = onClick;
    }
    function onClick() {
      var id = this.dataset.id;
      if (this.dataset.reset) {
        caps[id] = {}; refreshCap(id);
        post('id=' + id + '&reset=1', function () { msg.textContent = id + ' reset to default'; });
        return;
      }
      if (this.dataset.pt) {
        var pt = this.dataset.pt, name = pt === 'low' ? cfg.lowName : cfg.highName;
        if (live[id] == null) { msg.textContent = 'no reading yet'; return; }
        var act;
        if (entered) {
          var box = document.getElementById('calin-' + id + '-' + pt);
          act = box ? parseFloat(box.value) : NaN;
          if (isNaN(act)) { msg.textContent = 'type the ' + name + ' value first'; return; }
        } else {
          act = pt === 'low' ? cfg.lowVal : cfg.highVal;
        }
        caps[id] = caps[id] || {};
        caps[id][pt] = { raw: live[id], act: act };
        refreshCap(id);
        msg.textContent = 'captured ' + name + ': ' + live[id] + ' = ' + act;
        return;
      }
      var c = caps[id] || {};
      if (!c.low || !c.high) { msg.textContent = 'capture ' + cfg.lowName + ' and ' + cfg.highName + ' first'; return; }
      post('id=' + id + '&raw1=' + c.low.raw + '&act1=' + c.low.act + '&raw2=' + c.high.raw + '&act2=' + c.high.act,
        function (ok) { msg.textContent = ok ? (id + ' calibrated!') : 'failed'; });
    }
    function update(data) {
      calIds = data.cal_ids || [];
      var items = cfg.itemsFrom(data) || [];
      var s = items.map(function (i) { return i.id; }).join(',');
      if (s !== sig) { sig = s; build(items); items.forEach(function (i) { refreshCap(i.id); }); }
      items.forEach(function (it) {
        live[it.id] = it.raw;
        var nowEl = document.getElementById('calnow-' + it.id);
        if (nowEl) nowEl.textContent = it.raw == null ? '--' : it.raw;
        var bEl = document.getElementById('calbadge-' + it.id);
        if (bEl) bEl.innerHTML = calIds.indexOf(it.id) >= 0 ? '&#10003; calibrated' : '';
      });
    }
    return { update: update };
  }
  return { create: create };
})();
