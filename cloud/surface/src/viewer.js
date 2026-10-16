// Viewer API (cookie required): /api/now, /api/bins, /api/history.

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
