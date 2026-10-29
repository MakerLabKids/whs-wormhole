// Alerts: the Surface notices trouble and tells a human at once.
//   - Burrows POST /v1/edge/events as things happen (edge.js -> storeEvents): level
//     "alert" events are relayed to the notifier immediately.
//   - A cron (every minute, index.js scheduled -> watchEdges) notices a Burrow that has
//     stopped sending snapshots: an alert opens after SILENT_S, and closes (with a
//     second notification) when it is back. One notification per transition.
// Notifier: ALERT_URL (secret) is POSTed the text, ntfy-style (Title/Priority/Tags
// headers), e.g. https://ntfy.sh/<private topic> read by the ntfy app on a phone.
// ALERT_BINS=1 also notifies bin.quiet events (off by default: unplugged bins are normal).

import { chunks, err, isInt, json, now, readJson, safeParse } from "./util.js";

export const SILENT_S = 120;           // a Burrow snapshots every 60 s; two misses is trouble (the
                                       // neighbours' peer.down alert normally arrives well before this)
const EVENT_CAP = 100;                 // per POST
const LEVELS = new Set(["info", "warn", "alert"]);
const RENOTIFY_S = 15 * 60;            // same alert key again only after this

export function alertUrl(env) {
  const u = (env.ALERT_URL || "").trim();
  if (!u) return null;
  return /^https?:\/\//i.test(u) ? u : "https://" + u;      // "ntfy.sh/topic" is what people type
}

export async function notify(env, title, text, priority = "high", tags = "warning") {
  const url = alertUrl(env);
  if (!url) return { ok: false, error: "no ALERT_URL" };
  try {
    const r = await fetch(url, {
      method: "POST", body: text,
      headers: { Title: title, Priority: priority, Tags: tags, "Content-Type": "text/plain" },
    });
    return r.ok ? { ok: true } : { ok: false, error: `HTTP ${r.status}` };
  } catch (e) {
    return { ok: false, error: String(e?.message || e).slice(0, 120) };
  }
}

// Open (or refresh) an alert under `key`; notifies on open and when RENOTIFY_S has passed.
async function openAlert(env, key, edge, title, text, priority = "high", tags = "warning", t = now()) {
  const open = await env.DB.prepare("SELECT id, last_notified FROM alerts WHERE key = ?1 AND closed_at IS NULL").bind(key).first();
  if (open && open.last_notified && t - open.last_notified < RENOTIFY_S) return { id: open.id, notified: false };
  const n = await notify(env, title, text, priority, tags);
  if (open) {
    await env.DB.prepare("UPDATE alerts SET text = ?1, last_notified = ?2, notify_error = ?3 WHERE id = ?4")
      .bind(text, n.ok ? t : open.last_notified, n.ok ? null : n.error, open.id).run();
    return { id: open.id, notified: n.ok };
  }
  const r = await env.DB.prepare("INSERT INTO alerts (key, edge, text, opened_at, last_notified, notify_error) VALUES (?1, ?2, ?3, ?4, ?5, ?6)")
    .bind(key, edge, text, t, n.ok ? t : null, n.ok ? null : n.error).run();
  return { id: r.meta?.last_row_id, notified: n.ok, opened: true };
}

async function closeAlert(env, key, title, text, t = now()) {
  const open = await env.DB.prepare("SELECT id, opened_at FROM alerts WHERE key = ?1 AND closed_at IS NULL").bind(key).first();
  if (!open) return null;
  const n = await notify(env, title, text, "default", "white_check_mark");
  await env.DB.prepare("UPDATE alerts SET closed_at = ?1, notify_error = ?2 WHERE id = ?3").bind(t, n.ok ? null : n.error, open.id).run();
  return { id: open.id, minutes: Math.round((t - open.opened_at) / 60), notified: n.ok };
}

// POST /v1/edge/events {edge, events: [{ts, kind, level, text, data?}]}
export async function postEvents(request, env, edge) {
  const body = await readJson(request, 512 << 10);
  if (body.edge !== edge) return err(403, "edge does not match token");
  if (!Array.isArray(body.events)) return err(400, "events[] required");
  if (body.events.length > EVENT_CAP) return err(400, `at most ${EVENT_CAP} events per post`);
  const t = now();
  const rows = [];
  for (const e of body.events) {
    if (!e || typeof e !== "object" || typeof e.text !== "string" || !e.text) return err(400, "each event needs text");
    rows.push({
      ts: isInt(e.ts) ? e.ts : t, kind: String(e.kind || "note").slice(0, 40),
      level: LEVELS.has(e.level) ? e.level : "info", text: e.text.slice(0, 300),
      data: e.data && typeof e.data === "object" ? JSON.stringify(e.data).slice(0, 2000) : null,
    });
  }
  const stmts = [];
  for (const part of chunks(rows, 12)) {
    const sql = "INSERT INTO events (ts, edge, kind, level, text, data, received_at) VALUES " + part.map(() => "(?, ?, ?, ?, ?, ?, ?)").join(", ");
    const params = [];
    for (const r of part) params.push(r.ts, edge, r.kind, r.level, r.text, r.data, t);
    stmts.push(env.DB.prepare(sql).bind(...params));
  }
  if (stmts.length) await env.DB.batch(stmts);
  let notified = 0;
  for (const r of rows) {
    const data = r.data ? safeParse(r.data, {}) : {};
    // a dead Burrow is reported by every neighbour: one alert per dead Burrow, whoever saw it first
    if (r.kind === "peer.down" && data?.peer) {
      const res = await openAlert(env, `edge:${data.peer}`, data.peer, `${data.peer} down`, `${data.peer} is not answering ${edge} (${r.text}).`, "high", "rotating_light");
      if (res.notified) notified++;
      continue;
    }
    if (r.kind === "peer.back" && data?.peer) {
      await closeAlert(env, `edge:${data.peer}`, `${data.peer} back`, `${data.peer} answers ${edge} again.`);
      continue;
    }
    const wantsHuman = r.level === "alert" || (r.kind === "bin.quiet" && env.ALERT_BINS === "1");
    if (!wantsHuman) continue;
    const res = await openAlert(env, `event:${edge}:${r.kind}`, edge, `${edge}: ${r.kind}`, r.text,
      r.level === "alert" ? "high" : "default", r.level === "alert" ? "rotating_light" : "warning");
    if (res.notified) notified++;
    if (r.kind === "bin.back" || r.kind === "cloud.back") {
      await closeAlert(env, `event:${edge}:${r.kind.replace(".back", r.kind === "bin.back" ? ".quiet" : ".down")}`, `${edge}: back`, r.text);
    }
  }
  return json({ ok: true, n: rows.length, notified });
}

// Is this Burrow's Cloudflare tunnel answering? (The Live page, the signal meter and the
// 1 Hz view all ride on it; snapshots do not, so a dead tunnel is otherwise invisible.)
export async function probeTunnel(env, edgeId) {
  const room = (edgeId.match(/(\d)$/) || [])[1];
  if (room === undefined || !env.TUNNEL_DOMAIN || env.TUNNEL_PROBE === "0") return null;
  try {
    const r = await fetch(`https://burrow${room}.${env.TUNNEL_DOMAIN}/health`,
      { headers: { "x-burrow-key": env.LIVE_KEY || "" }, signal: AbortSignal.timeout(8000) });
    return { ok: r.ok, status: r.status };
  } catch (e) {
    return { ok: false, status: 0, error: String(e?.message || e).slice(0, 80) };
  }
}

// The cron: a Burrow that stopped reporting, and one that came back; a tunnel that died.
export async function watchEdges(env, t = now(), probe = probeTunnel) {
  const { results } = await env.DB.prepare("SELECT edge_id, room, updated_at FROM edges").all();
  const out = { opened: [], closed: [], silent: [], tunnel_down: [] };
  for (const r of results) {
    const age = t - (r.updated_at || 0);
    const key = `edge:${r.edge_id}`;
    if (age <= SILENT_S) {                       // only a live Burrow can have a dead tunnel worth a call
      const p = await probe(env, r.edge_id);
      if (p && !p.ok) {
        out.tunnel_down.push(r.edge_id);
        const res = await openAlert(env, `tunnel:${r.edge_id}`, r.edge_id, `${r.edge_id} tunnel down`,
          `${r.edge_id} (room ${r.room}) reports fine but its Cloudflare tunnel answers ${p.status || p.error}: no Live page, signal meter or 1/s view for that room.`,
          "default", "warning", t);
        if (res.opened) out.opened.push(r.edge_id + ":tunnel");
      } else if (p && p.ok) {
        const res = await closeAlert(env, `tunnel:${r.edge_id}`, `${r.edge_id} tunnel back`, `${r.edge_id} (room ${r.room}) tunnel answers again.`, t);
        if (res) out.closed.push({ edge: r.edge_id + ":tunnel", minutes: res.minutes });
      }
    }
    if (age > SILENT_S) {
      out.silent.push(r.edge_id);
      const last = r.updated_at ? new Date(r.updated_at * 1000).toISOString().slice(11, 16) + " UTC" : "never";
      const res = await openAlert(env, key, r.edge_id,
        `${r.edge_id} silent`, `${r.edge_id} (room ${r.room}) has not reported for ${Math.round(age / 60)} min; last snapshot ${last}.`,
        "high", "rotating_light", t);
      if (res.opened) out.opened.push(r.edge_id);
    } else {
      const res = await closeAlert(env, key, `${r.edge_id} back`, `${r.edge_id} (room ${r.room}) is reporting again.`, t);
      if (res) out.closed.push({ edge: r.edge_id, minutes: res.minutes });
    }
  }
  return out;
}

// GET /api/admin/alerts  -> open alerts first, then the last 50 closed
export async function listAlerts(env) {
  const open = (await env.DB.prepare("SELECT * FROM alerts WHERE closed_at IS NULL ORDER BY opened_at DESC").all()).results;
  const closed = (await env.DB.prepare("SELECT * FROM alerts WHERE closed_at IS NOT NULL ORDER BY closed_at DESC LIMIT 50").all()).results;
  return json({ ok: true, ts: now(), notifier: env.ALERT_URL ? "configured" : "not configured", open, closed });
}

// GET /api/admin/events?since=&edge=&level=&limit=
export async function listEvents(request, env) {
  const u = new URL(request.url);
  const since = Number(u.searchParams.get("since")) || now() - 7 * 86400;
  const edge = u.searchParams.get("edge") || null;
  const level = u.searchParams.get("level") || null;
  const limit = Math.min(500, Number(u.searchParams.get("limit")) || 200);
  const where = ["received_at >= ?1"]; const params = [since];
  if (edge) { where.push(`edge = ?${params.length + 1}`); params.push(edge); }
  if (level) { where.push(`level = ?${params.length + 1}`); params.push(level); }
  const { results } = await env.DB.prepare(`SELECT * FROM events WHERE ${where.join(" AND ")} ORDER BY ts DESC, id DESC LIMIT ${limit}`).bind(...params).all();
  return json({ ok: true, ts: now(), events: results.map((r) => ({ ...r, data: safeParse(r.data, null) })) });
}
