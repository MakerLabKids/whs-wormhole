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
// An open alert notifies once, then a reminder once a day while it stays open, and once
// when it closes. It is retried sooner only while the notifier has never managed to deliver
// it. (Until 2026-10-30 it re-sent every 15 min, which with four unplugged Burrows was a
// buzz every few minutes around the clock.)
const REMIND_S = 24 * 3600;

export function alertUrl(env) {
  const u = (env.ALERT_URL || "").trim();
  if (!u) return null;
  if (/^https?:\/\//i.test(u)) return u;
  if (!u.includes("/") && !u.includes(".")) return "https://ntfy.sh/" + u;   // just a topic name: ntfy.sh is the default server
  return "https://" + u;                                               // "ntfy.sh/topic" is what people type
}

// ALERT_TOKEN (secret, optional): an ntfy access token. ntfy.sh counts anonymous
// messages per source IP, and a Worker shares its IPs with everyone else's Workers, so
// the free anonymous quota is gone before we send a thing (seen 2026-10-29: "daily
// message quota reached"). A signed-in account has its own quota. "https://user:pass@host/topic"
// in ALERT_URL works too (Basic auth).
export function alertHeaders(env, title, priority, tags) {
  const h = { Title: title, Priority: priority, Tags: tags, "Content-Type": "text/plain" };
  const tok = (env.ALERT_TOKEN || "").trim();
  if (tok) h.Authorization = "Bearer " + tok;
  return h;
}
function stripUserinfo(url) {
  const m = url.match(/^(https?:\/\/)([^/@]+)@(.*)$/);
  return m ? { url: m[1] + m[3], basic: "Basic " + btoa(decodeURIComponent(m[2])) } : { url, basic: null };
}
// Three notifier shapes, told apart by the URL (ntfy.sh's free tier meters anonymous AND
// free-account posts per source IP, and a Worker's IPs are shared, so ntfy.sh only works
// from here with a paid tier; Discord and Telegram are free):
//   ntfy      https://ntfy.sh/<topic>                      text body + Title/Priority/Tags headers
//   Discord   https://discord.com/api/webhooks/<id>/<tok>   {"content": "**title**\ntext"}
//   Telegram  https://api.telegram.org/bot<tok>/sendMessage?chat_id=<id>   {"chat_id", "text"}
export function notifierKind(url) {
  if (/^https:\/\/(discord\.com|discordapp\.com)\/api\/webhooks\//i.test(url)) return "discord";
  if (/^https:\/\/api\.telegram\.org\/bot/i.test(url)) return "telegram";
  return "ntfy";
}
export function buildRequest(url, headers, title, text) {
  const kind = notifierKind(url);
  if (kind === "discord") {
    return { url, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: `**${title}**\n${text}`.slice(0, 1900) }) };
  }
  if (kind === "telegram") {
    const u = new URL(url);
    const chat_id = u.searchParams.get("chat_id");
    u.search = "";
    return { url: u.toString(), headers: { "Content-Type": "application/json" }, body: JSON.stringify({ chat_id, text: `${title}\n${text}`.slice(0, 4000) }) };
  }
  return { url, headers, body: text };
}
export async function notify(env, title, text, priority = "high", tags = "warning", sleep = (ms) => new Promise((r) => setTimeout(r, ms))) {
  const raw = alertUrl(env);
  if (!raw) return { ok: false, error: "no ALERT_URL" };
  const { url, basic } = stripUserinfo(raw);
  const headers = alertHeaders(env, title, priority, tags);
  if (basic && !headers.Authorization) headers.Authorization = basic;
  const req = buildRequest(url, headers, title, text);
  let last = null;
  for (let attempt = 0; attempt < 2; attempt++) {          // one retry: ntfy.sh's front door gave a 522 once
    if (attempt) await sleep(2000);
    try {
      const r = await fetch(req.url, { method: "POST", body: req.body, headers: req.headers });
      if (r.ok) return { ok: true };
      const body = (await r.text().catch(() => "")).replace(/\s+/g, " ").trim().slice(0, 100);
      last = { ok: false, error: `HTTP ${r.status}${body ? " " + body : ""}` };
      if (r.status < 500) return last;
    } catch (e) {
      last = { ok: false, error: String(e?.message || e).slice(0, 120) };
    }
  }
  return last;
}
// Where alerts go, with the topic mostly hidden (anyone who knows it can subscribe):
// "https://ntfy.sh/w…ncy (15 chars)".
export function describeTarget(env) {
  const url = alertUrl(env);
  if (!url) return null;
  const kind = notifierKind(url);
  if (kind === "discord") return "Discord webhook (" + url.length + " chars)";
  if (kind === "telegram") return "Telegram bot, chat " + (new URL(url).searchParams.get("chat_id") || "?");
  const m = url.match(/^(https?:\/\/[^/]+\/)(.*)$/);
  if (!m) return url.slice(0, 12) + "…";
  const topic = m[2];
  const shown = topic.length > 6 ? topic[0] + "…" + topic.slice(-3) : "…";
  return `${m[1]}${shown} (${topic.length} chars)`;
}
// POST /api/admin/alerts/test: send one notification now and report exactly what the
// notifier answered, so a dead phone can be debugged from the Devices page.
// "tk_abc…xyz (32 chars)": enough to compare with the ntfy account page, not enough to use.
export function fingerprint(secret) {
  const v = (secret || "").trim();
  if (!v) return null;
  return (v.length > 10 ? v.slice(0, 4) + "…" + v.slice(-3) : "…") + ` (${v.length} chars)`;
}
// Ask the ntfy server who the stored token is (GET /v1/account): a wrong token is a 401,
// a right one returns the username, tier and the day's message count and remainder.
export async function ntfyAccount(env, fetcher = fetch) {
  const url = alertUrl(env);
  const tok = (env.ALERT_TOKEN || "").trim();
  if (!url || !tok || notifierKind(url) !== "ntfy") return null;
  try {
    const r = await fetcher(new URL(url).origin + "/v1/account", { headers: { Authorization: "Bearer " + tok } });
    if (!r.ok) return { status: r.status, error: (await r.text().catch(() => "")).replace(/\s+/g, " ").slice(0, 100) };
    const a = await r.json();
    return { status: 200, username: a.username, role: a.role, tier: a.tier?.name || a.tier?.code || null,
             messages: a.stats?.messages, messages_remaining: a.stats?.messages_remaining, messages_limit: a.limits?.messages };
  } catch (e) {
    return { status: 0, error: String(e?.message || e).slice(0, 100) };
  }
}
export async function testNotify(env) {
  const t = now();
  const n = await notify(env, "Wormhole test", "Test alert from the Surface. If you read this on your phone, alerts work.", "default", "white_check_mark");
  const url = alertUrl(env) || "";
  const stored = { url, url_raw_length: (env.ALERT_URL || "").length, token: fingerprint(env.ALERT_TOKEN), account: await ntfyAccount(env) };
  return json({ ok: n.ok, target: describeTarget(env), stored, kind: notifierKind(alertUrl(env) || ""), auth: env.ALERT_TOKEN ? "token" : (/^https?:\/\/[^/]*@/.test(alertUrl(env) || "") ? "basic" : "none"), error: n.error || null, ts: t });
}

// Open (or refresh) an alert under `key`; notifies on open, again if that failed, else daily.
export async function openAlert(env, key, edge, title, text, priority = "high", tags = "warning", t = now()) {
  const open = await env.DB.prepare("SELECT id, last_notified, opened_at FROM alerts WHERE key = ?1 AND closed_at IS NULL").bind(key).first();
  if (open && open.last_notified && t - open.last_notified < REMIND_S) return { id: open.id, notified: false };
  const n = await notify(env, open?.last_notified ? `still: ${title}` : title,
                         open?.last_notified ? `${text} Open since ${new Date(open.opened_at * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC.` : text, priority, tags);
  if (open) {
    await env.DB.prepare("UPDATE alerts SET text = ?1, last_notified = ?2, notify_error = ?3 WHERE id = ?4")
      .bind(text, n.ok ? t : open.last_notified, n.ok ? null : n.error, open.id).run();
    return { id: open.id, notified: n.ok };
  }
  const r = await env.DB.prepare("INSERT INTO alerts (key, edge, text, opened_at, last_notified, notify_error) VALUES (?1, ?2, ?3, ?4, ?5, ?6)")
    .bind(key, edge, text, t, n.ok ? t : null, n.ok ? null : n.error).run();
  return { id: r.meta?.last_row_id, notified: n.ok, opened: true };
}

export async function closeAlert(env, key, title, text, t = now()) {
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
