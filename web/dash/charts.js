/* charts.js: a small canvas chart helper for the deep view and the live sparklines.
   No dependencies. Two exports on window: LineChart and sparkline.

   LineChart draws one or more series of rollup buckets. Each point is a bucket
   {t, min, avg, max}: the avg becomes a 2px line and the min..max becomes a
   translucent band behind it, so a 1-hour bucket still shows how much the
   reading wobbled. Gaps (a missing bucket) break the line instead of being
   interpolated: a straight line across a two-hour outage would be a lie. */
(function () {
  'use strict';

  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function hhmm(d) { return pad2(d.getHours()) + ':' + pad2(d.getMinutes()); }
  function mmdd(d) { return MONTHS[d.getMonth()] + ' ' + d.getDate(); }

  /* "nice" tick step for a value axis: 1, 2, 5 x 10^k that gives ~n ticks */
  function niceStep(span, n) {
    if (span <= 0) return 1;
    var raw = span / n, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var r = raw / mag;
    return (r < 1.5 ? 1 : r < 3.5 ? 2 : r < 7.5 ? 5 : 10) * mag;
  }

  /* time ticks: pick an interval that yields 4-8 labels, aligned to local wall time */
  var TIME_STEPS = [10, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 2 * 86400, 7 * 86400];
  function timeTicks(t0, t1) {
    var span = t1 - t0, step = TIME_STEPS[TIME_STEPS.length - 1];
    for (var i = 0; i < TIME_STEPS.length; i++) { if (span / TIME_STEPS[i] <= 8) { step = TIME_STEPS[i]; break; } }
    var out = [], d = new Date(t0 * 1000);
    // align to the local day, then step forward (so midnight labels land on midnight)
    var dayStart = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000;
    var t = dayStart + Math.ceil((t0 - dayStart) / step) * step;
    for (; t <= t1; t += step) out.push(t);
    return { ticks: out, step: step };
  }
  function hhmmss(d) { return hhmm(d) + ':' + pad2(d.getSeconds()); }
  function tickLabel(t, step) {
    var d = new Date(t * 1000);
    if (step >= 86400) return mmdd(d);
    if (d.getHours() === 0 && d.getMinutes() === 0 && step >= 3600) return mmdd(d);
    if (step < 60) return hhmmss(d);          // the live view: seconds matter
    return hhmm(d);
  }
  function fullTime(t, seconds) {
    var d = new Date(t * 1000);
    return mmdd(d) + ' ' + (seconds ? hhmmss(d) : hhmm(d));
  }
  function fmt(v, unit, decimals) {
    if (v === null || v === undefined || isNaN(v)) return '–';
    var d = decimals !== undefined ? decimals : (Math.abs(v) >= 1000 ? 0 : 1);
    return v.toFixed(d) + (unit || '');
  }
  /* least-squares line through the bucket averages: {a, b, n} with v = a + b * t (t in seconds).
     Needs two distinct times; weights buckets by their sample count so a sparse hour does
     not outvote a busy one. Exposed as window.linearFit so the legend can quote the slope. */
  function linearFit(points) {
    var n = 0, st = 0, sv = 0, stt = 0, stv = 0, t0 = points.length ? points[0].t : 0;
    points.forEach(function (p) {
      var w = p.n || 1, t = p.t - t0;
      n += w; st += w * t; sv += w * p.avg; stt += w * t * t; stv += w * t * p.avg;
    });
    var den = n * stt - st * st;
    if (n < 2 || den <= 0) return null;
    var b = (n * stv - st * sv) / den, a = (sv - b * st) / n;
    return { a: a - b * t0, b: b, n: n };
  }
  /* "+0.4 °C/h" or "−1.2 %/day": slope in the unit that gives a readable number for the span */
  function trendLabel(fit, spanS, unit) {
    if (!fit) return '';
    var perHour = fit.b * 3600, perDay = fit.b * 86400, useDay = spanS > 2 * 86400;
    var v = useDay ? perDay : perHour, abs = Math.abs(v);
    var dec = abs >= 10 ? 0 : abs >= 1 ? 1 : 2;
    return (v >= 0 ? '+' : '−') + abs.toFixed(dec) + (unit || '').trim() + (useDay ? '/day' : '/h');
  }
  window.linearFit = linearFit;
  window.trendLabel = trendLabel;

  /* axis labels need as many decimals as the tick step has (1009.05 vs 1009.10), no more */
  function stepDecimals(step) { return Math.max(0, Math.min(3, -Math.floor(Math.log10(step) + 1e-9))); }

  /* opts: {unit, gapS (seconds; a hole longer than this breaks the line)}
     series: [{name, color, dash, points:[{t,min,avg,max}]}] */
  function LineChart(box, opts) {
    opts = opts || {};
    var canvas = document.createElement('canvas');
    var tip = document.createElement('div');
    tip.className = 'tip'; tip.hidden = true;
    box.appendChild(canvas); box.appendChild(tip);
    var ctx = canvas.getContext('2d');
    var series = [], range = null, hoverX = null, layout = null;

    function cssW() { return box.clientWidth || 300; }
    function cssH() { return box.clientHeight || 200; }

    /* retina: size the backing store to devicePixelRatio, draw in CSS pixels */
    function fit() {
      var dpr = window.devicePixelRatio || 1, w = cssW(), h = cssH();
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function draw() {
      fit();
      var W = cssW(), H = cssH();
      ctx.clearRect(0, 0, W, H);
      var text = cssVar('--text', '#222'), muted = cssVar('--muted', '#6B7280'), grid = cssVar('--grid', '#E1E8EF');
      var padL = 46, padR = 14, padT = 10, padB = 24;

      var t0 = range ? range.from : null, t1 = range ? range.to : null;
      var lo = Infinity, hi = -Infinity, any = false;
      series.forEach(function (s) {
        s.points.forEach(function (p) {
          any = true;
          if (t0 === null || p.t < t0) t0 = p.t;
          if (t1 === null || p.t > t1) t1 = p.t;
          if (p.min < lo) lo = p.min; if (p.max > hi) hi = p.max;
        });
      });
      ctx.font = '12px Arial, Helvetica, sans-serif';
      if (!any) {
        ctx.fillStyle = muted; ctx.textAlign = 'center';
        ctx.fillText('no data in this range', W / 2, H / 2);
        layout = null;
        return;
      }
      if (t1 <= t0) t1 = t0 + 1;
      if (hi === lo) { hi += 1; lo -= 1; }
      // breathe a little so the band never touches the frame
      var padV = (hi - lo) * 0.08; lo -= padV; hi += padV;
      if (opts.min0 && lo < 0) lo = 0;
      var ystep = niceStep(hi - lo, 4), ydec = stepDecimals(ystep);
      var yA = Math.floor(lo / ystep) * ystep, yB = Math.ceil(hi / ystep) * ystep;
      // the left pad follows the widest y label ("1009.32" needs more room than "22")
      padL = Math.max(padL, Math.ceil(Math.max(ctx.measureText(fmt(yA, '', ydec)).width, ctx.measureText(fmt(yB, '', ydec)).width)) + 10);
      var pw = W - padL - padR, ph = H - padT - padB;
      if (pw < 20 || ph < 20) return;
      var X = function (t) { return padL + (t - t0) / (t1 - t0) * pw; };
      var Y = function (v) { return padT + (yB - v) / (yB - yA) * ph; };
      layout = { X: X, Y: Y, t0: t0, t1: t1, padL: padL, padT: padT, pw: pw, ph: ph };

      // grid + y labels (recessive)
      ctx.strokeStyle = grid; ctx.lineWidth = 1; ctx.fillStyle = muted; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      for (var v = yA; v <= yB + 1e-9; v += ystep) {
        var y = Math.round(Y(v)) + 0.5;
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
        ctx.fillText(fmt(v, '', ydec), padL - 6, y);
      }
      // x labels
      var tt = timeTicks(t0, t1);
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      tt.ticks.forEach(function (t) {
        var x = Math.round(X(t)) + 0.5, label = tickLabel(t, tt.step), half = ctx.measureText(label).width / 2;
        ctx.strokeStyle = grid; ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + ph); ctx.stroke();
        // a label near either edge slides inward instead of being cut off
        var lx = Math.min(Math.max(x, padL + half), W - half - 2);
        ctx.fillStyle = muted; ctx.fillText(label, lx, padT + ph + 6);
      });

      var gap = opts.gapS || 900;
      // bands first (all of them), then lines, so no band hides another line
      series.forEach(function (s) {
        var pts = s.points; if (!pts.length) return;
        ctx.fillStyle = s.color; ctx.globalAlpha = 0.16;
        var i = 0;
        while (i < pts.length) {
          var j = i;
          while (j + 1 < pts.length && pts[j + 1].t - pts[j].t <= gap) j++;
          if (j > i) {
            ctx.beginPath();
            for (var k = i; k <= j; k++) ctx.lineTo(X(pts[k].t), Y(pts[k].max));
            for (k = j; k >= i; k--) ctx.lineTo(X(pts[k].t), Y(pts[k].min));
            ctx.closePath(); ctx.fill();
          }
          i = j + 1;
        }
        ctx.globalAlpha = 1;
      });
      series.forEach(function (s) {
        var pts = s.points; if (!pts.length) return;
        ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.lineJoin = 'round';
        ctx.setLineDash(s.dash ? [6, 4] : []);
        ctx.beginPath();
        var prev = null;
        pts.forEach(function (p) {
          if (prev && p.t - prev.t > gap) ctx.moveTo(X(p.t), Y(p.avg));
          else if (!prev) ctx.moveTo(X(p.t), Y(p.avg));
          else ctx.lineTo(X(p.t), Y(p.avg));
          prev = p;
        });
        ctx.stroke(); ctx.setLineDash([]);
        // a lone bucket has no line to see: give it a dot
        pts.forEach(function (p, idx) {
          var alone = (idx === 0 || p.t - pts[idx - 1].t > gap) && (idx === pts.length - 1 || pts[idx + 1].t - p.t > gap);
          if (alone) { ctx.fillStyle = s.color; ctx.beginPath(); ctx.arc(X(p.t), Y(p.avg), 3, 0, 7); ctx.fill(); }
        });
      });
      // trend: a thin dashed least-squares line across the whole range, one per series
      if (opts.trend !== false) {
        series.forEach(function (s) {
          var fit = linearFit(s.points); if (!fit) return;
          var ta = s.points[0].t, tb = s.points[s.points.length - 1].t; if (tb <= ta) return;
          ctx.save();
          ctx.strokeStyle = s.color; ctx.globalAlpha = 0.55; ctx.lineWidth = 1.5; ctx.setLineDash([2, 5]);
          ctx.beginPath(); ctx.moveTo(X(ta), Y(fit.a + fit.b * ta)); ctx.lineTo(X(tb), Y(fit.a + fit.b * tb)); ctx.stroke();
          ctx.restore();
        });
      }
      // direct label at each line's end, so identity is never color alone
      if (series.length > 1) {
        ctx.textAlign = 'right'; ctx.textBaseline = 'bottom'; ctx.font = 'bold 11px Arial, Helvetica, sans-serif';
        var used = [];
        series.forEach(function (s) {
          var last = s.points[s.points.length - 1]; if (!last) return;
          var y = Y(last.avg) - 3;
          // nudge labels apart if two lines end at the same height
          used.forEach(function (u) { if (Math.abs(u - y) < 12) y = u - 12; });
          used.push(y);
          ctx.fillStyle = text; ctx.fillText(s.name, X(last.t), y);
        });
      }
      // hover crosshair
      if (hoverX !== null) drawHover();
    }

    function nearest(t) {
      // nearest bucket across all series (buckets are aligned, so one t serves all)
      var best = null, bd = Infinity;
      series.forEach(function (s) { s.points.forEach(function (p) { var d = Math.abs(p.t - t); if (d < bd) { bd = d; best = p.t; } }); });
      return best;
    }

    function drawHover() {
      if (!layout) return;
      var t = layout.t0 + (hoverX - layout.padL) / layout.pw * (layout.t1 - layout.t0);
      var bt = nearest(t);
      if (bt === null) { tip.hidden = true; return; }
      var x = Math.round(layout.X(bt)) + 0.5;
      ctx.strokeStyle = cssVar('--muted', '#6B7280'); ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, layout.padT); ctx.lineTo(x, layout.padT + layout.ph); ctx.stroke(); ctx.setLineDash([]);
      var html = '<div class="t">' + fullTime(bt, layout.t1 - layout.t0 < 3600) + '</div>';
      series.forEach(function (s) {
        var p = null;
        for (var i = 0; i < s.points.length; i++) if (s.points[i].t === bt) { p = s.points[i]; break; }
        if (!p) return;
        ctx.fillStyle = s.color; ctx.beginPath(); ctx.arc(layout.X(bt), layout.Y(p.avg), 4, 0, 7); ctx.fill();
        ctx.strokeStyle = cssVar('--card', '#fff'); ctx.lineWidth = 2; ctx.stroke();
        html += '<div><span class="sw" style="background:' + s.color + '"></span>' + s.name + ' <b>' + fmt(p.avg, opts.unit) + '</b>' +
          (p.min !== p.max ? ' <span class="muted">(' + fmt(p.min, '') + '–' + fmt(p.max, '') + ')</span>' : '') + '</div>';
      });
      tip.innerHTML = html; tip.hidden = false;
      var W = cssW(), tw = tip.offsetWidth;
      tip.style.left = (x + 12 + tw > W ? x - 12 - tw : x + 12) + 'px';
      tip.style.top = '8px';
    }

    function onMove(e) {
      var r = canvas.getBoundingClientRect();
      hoverX = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
      draw();
    }
    function onLeave() { hoverX = null; tip.hidden = true; draw(); }
    canvas.addEventListener('mousemove', onMove);
    canvas.addEventListener('touchstart', onMove, { passive: true });
    canvas.addEventListener('touchmove', onMove, { passive: true });
    canvas.addEventListener('mouseleave', onLeave);
    canvas.addEventListener('touchend', onLeave);

    var ro = null;
    if (window.ResizeObserver) { ro = new ResizeObserver(function () { draw(); }); ro.observe(box); }
    else window.addEventListener('resize', draw);

    return {
      set: function (s, r) { series = s || []; range = r || null; draw(); },
      redraw: draw,
      destroy: function () { if (ro) ro.disconnect(); else window.removeEventListener('resize', draw); box.innerHTML = ''; }
    };
  }

  /* sparkline(canvas, values, color): last-N values, no axes; flat line if constant */
  function sparkline(canvas, values, color) {
    var dpr = window.devicePixelRatio || 1;
    var w = canvas.clientWidth || 160, h = canvas.clientHeight || 40;
    if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    var ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    var vs = values.filter(function (v) { return typeof v === 'number' && !isNaN(v); });
    if (vs.length < 2) return;
    var lo = Math.min.apply(null, vs), hi = Math.max.apply(null, vs);
    if (hi === lo) { hi += 0.5; lo -= 0.5; }
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = 'round';
    ctx.beginPath();
    vs.forEach(function (v, i) {
      var x = 2 + i / (vs.length - 1) * (w - 4), y = 3 + (hi - v) / (hi - lo) * (h - 6);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    var lx = w - 2, ly = 3 + (hi - vs[vs.length - 1]) / (hi - lo) * (h - 6);
    ctx.fillStyle = color; ctx.beginPath(); ctx.arc(lx, ly, 3, 0, 7); ctx.fill();
  }

  window.LineChart = LineChart;
  window.sparkline = sparkline;
  window.chartFmt = fmt;
})();
