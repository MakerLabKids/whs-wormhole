// Viewer API (cookie required): /api/now, /api/bins, /api/history.
// Plus one anonymous, trimmed, 60 s-cached feed for the public wall skins:
// /api/public/now (CORS for the project's GitHub Pages site).

import { err, json, now, safeParse, toInt } from "./util.js";

const NOW_TTL_S = 10;
const STALE_S = 180;
const HISTORY_ROW_CAP = 10000;

// Merge the per-Burrow snapshots into one picture. For each uid the entry
// with the newest ts wins (a Bin that failed over to another room shows up
// in two snapshots). Cached 10 s at the edge: 200 pollers cost ~6 D1 reads a
// minute. Auth has already happened before we get here, on purpose.
export async function apiNow(request, env, ctx) {
  const cache = caches.default;
  const key = new Request(request.url, { method: "GET" });
  const hit = await cache.match(key);
  if (hit) return hit;

  const { results } = await env.DB.prepare(
    "SELECT edge_id, room, ts, clk, snapshot, status, updated_at FROM edges",
  ).all();
  const t = now();
  const edges = {}, bins = {};
  for (const r of results) {
    const status = safeParse(r.status, {}) || {};
    edges[r.edge_id] = { ...status, edge: r.edge_id, room: r.room, ts: r.ts, clk: r.clk, seen: r.updated_at };
    const snap = safeParse(r.snapshot, {}) || {};
    for (const [uid, e] of Object.entries(snap)) {
      if (!e || typeof e !== "object") continue;
      const cur = bins[uid];
      if (!cur || (e.ts || 0) > (cur.ts || 0)) {
        bins[uid] = { ...e, edge: e.edge || r.edge_id, stale: t - (e.ts || 0) > STALE_S };
      }
    }
  }
  const resp = json({ ts: t, edges, bins }, 200, { "cache-control": `public, max-age=${NOW_TTL_S}` });
  ctx.waitUntil(cache.put(key, resp.clone()));
  return resp;
}

// Roster: {uid: {name, team, period, bin, room, seen}}.
export async function apiBins(env) {
  const { results } = await env.DB.prepare("SELECT uid, name, team, period, bin, room, last_seen FROM bins").all();
  const out = {};
  for (const r of results) {
    out[r.uid] = { name: r.name, team: r.team, period: r.period, bin: r.bin, room: r.room, seen: r.last_seen };
  }
  return json(out);
}

// /api/history?uid=&from=&to=&step=5m|1h  -> {uid, step, from, to, points:[[ts, data], ...]}
// Step is picked from the span when not given: <= 3 days -> 5m, else 1h.
export async function apiHistory(request, env) {
  const q = new URL(request.url).searchParams;
  const uid = q.get("uid");
  if (!uid) return err(400, "uid required");
  const t = now();
  const to = toInt(q.get("to"), t);
  const from = toInt(q.get("from"), to - 86400);
  if (from > to) return err(400, "from must be <= to");
  let step = q.get("step");
  if (step !== "5m" && step !== "1h") step = (to - from) <= 3 * 86400 ? "5m" : "1h";

  const { results } = await env.DB.prepare(
    "SELECT ts, data FROM rollups WHERE uid = ?1 AND step = ?2 AND ts >= ?3 AND ts <= ?4 ORDER BY ts LIMIT ?5",
  ).bind(uid, step, from, to, HISTORY_ROW_CAP).all();
  const points = results.map((r) => [r.ts, safeParse(r.data, {})]);
  return json({ uid, step, from, to, points }, 200, { "cache-control": "private, max-age=60" });
}

// ---- public feed -----------------------------------------------------------
// The mission-control skins on makerlabkids.github.io run on real data through
// this. No cookie, no visit row, nothing per-person: team names, period, bin,
// room and the readings. IPs and anything about who is looking never leave.
const PUBLIC_TTL_S = 60;
const PUBLIC_ORIGINS = ["https://makerlabkids.github.io", "https://whs.makerlabkids.com"];
const PUBLIC_FIELDS = ["in_temp_c", "out_temp_c", "in_hum_pct", "out_hum_pct", "in_press_hpa", "moist1_pct",
  "moist2_pct", "light_pct", "lux", "sound_pct", "surface_mm", "probe_temps_c", "mode", "relay"];

export function publicCors(request, headers = {}) {
  const origin = request.headers.get("origin") || "";
  const ok = PUBLIC_ORIGINS.includes(origin) || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  return ok ? { ...headers, "access-control-allow-origin": origin, vary: "origin" } : headers;
}

export async function apiPublicNow(request, env, ctx) {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: publicCors(request, { "access-control-allow-methods": "GET", "access-control-max-age": "86400" }) });
  }
  if (request.method !== "GET") return err(405, "method not allowed");
  const cache = caches.default;
  const key = new Request(new URL(request.url).origin + "/api/public/now", { method: "GET" });
  const hit = await cache.match(key);
  if (hit) return new Response(hit.body, { status: hit.status, headers: publicCors(request, Object.fromEntries(hit.headers)) });

  const { results } = await env.DB.prepare("SELECT edge_id, room, ts, clk, snapshot, updated_at FROM edges").all();
  const t = now();
  const edges = {}, bins = {};
  for (const r of results) {
    edges[r.edge_id] = { edge: r.edge_id, room: r.room, ts: r.ts, clk: r.clk, seen: r.updated_at };
    const snap = safeParse(r.snapshot, {}) || {};
    for (const [uid, e] of Object.entries(snap)) {
      if (!e || typeof e !== "object") continue;
      const cur = bins[uid];
      if (cur && (cur.ts || 0) >= (e.ts || 0)) continue;
      const d = e.d && typeof e.d === "object" ? e.d : {};
      const parts = Array.isArray(d.parts) ? d.parts : [];
      const dd = {};
      for (const k of PUBLIC_FIELDS) if (d[k] !== undefined) dd[k] = d[k];
      dd.parts_ok = parts.filter((p) => p && p.ok).length;
      dd.parts_total = parts.length;
      bins[uid] = { ts: e.ts, clk: e.clk, edge: e.edge || r.edge_id, room: e.room ?? r.room,
        team: e.team || e.name || null, period: e.period ?? null, bin: e.bin ?? null,
        stale: t - (e.ts || 0) > STALE_S, d: dd };
    }
  }
  const resp = json({ ts: t, edges, bins }, 200, { "cache-control": `public, max-age=${PUBLIC_TTL_S}` });
  ctx.waitUntil(cache.put(key, resp.clone()));
  return new Response(resp.body, { status: 200, headers: publicCors(request, Object.fromEntries(resp.headers)) });
}
