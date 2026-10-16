// Burrow -> Surface: /v1/edge/*  (PROTOCOL.md "Burrow -> Surface").
// Auth: Authorization: Bearer <token>; EDGE_TOKENS is a JSON map edge -> token.

import { chunks, err, hex, isInt, json, now, readJson, safeParse, timingSafeEqual } from "./util.js";

const CASTING_CAP = 8 * 1024 * 1024;   // gz bytes per PUT
const VERIFY_CAP = 40;                 // R2 reads per verify (free Workers: 50 subrequests)
const ROLLUP_CAP = 5000;               // rows per POST
const ROLLUP_ROWS_PER_STMT = 25;       // 4 params each -> 100 bound params (the D1 limit)
const BIN_ROWS_PER_STMT = 12;          // 8 params each
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;

// Returns the edge name owning the bearer token, or null. Compared in
// constant time against every configured token so timing says nothing.
export function authEdge(request, env) {
  const h = request.headers.get("authorization") || "";
  if (!h.startsWith("Bearer ")) return null;
  const token = h.slice(7).trim();
  const map = safeParse(env.EDGE_TOKENS, null);
  if (!map || typeof map !== "object" || !token) return null;
  let owner = null;
  for (const [edge, t] of Object.entries(map)) {
    if (typeof t === "string" && t && timingSafeEqual(t, token)) owner = edge;
  }
  return owner;
}

export async function handleEdge(request, env, ctx, path) {
  const edge = authEdge(request, env);
  if (!edge) return err(401, "unauthorized");
  const m = request.method;

  if (path === "/v1/edge/ping" && m === "GET") return json({ ok: true, ts: now() });
  if (path === "/v1/edge/snapshot" && m === "POST") return snapshot(request, env, edge);
  if (path === "/v1/edge/rollups" && m === "POST") return rollups(request, env);
  if (path === "/v1/edge/verify" && m === "POST") return verify(request, env);
  if (path.startsWith("/v1/edge/castings/")) {
    const id = path.slice("/v1/edge/castings/".length);
    if (m === "PUT") return putCasting(request, env, edge, id);
    return err(405, "method not allowed");
  }
  if (["/v1/edge/ping", "/v1/edge/snapshot", "/v1/edge/rollups", "/v1/edge/verify"].includes(path)) {
    return err(405, "method not allowed");
  }
  return err(404, "not found");
}

// R2 key: castings/r<room>/<YYYY>/<MM>/<DD>/<id>.jsonl.gz, date from t0 (UTC).
export function r2Key(room, t0, id) {
  const d = new Date(t0 * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `castings/r${room}/${d.getUTCFullYear()}/${p(d.getUTCMonth() + 1)}/${p(d.getUTCDate())}/${id}.jsonl.gz`;
}

async function putCasting(request, env, edge, id) {
  if (!ID_RE.test(id)) return err(400, "bad casting id");
  const meta = safeParse(request.headers.get("x-casting-meta"), null);
  if (!meta || typeof meta !== "object") return err(400, "missing or invalid X-Casting-Meta");
  if (meta.id !== undefined && meta.id !== id) return err(400, "meta id does not match path");
  if (typeof meta.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(meta.sha256)) return err(400, "meta.sha256 required");
  if (!isInt(meta.t0)) return err(400, "meta.t0 required");
  // room: from the meta, else from the id prefix r<room>-...
  const room = isInt(meta.room) ? meta.room : Number((id.match(/^r(\d+)-/) || [])[1]);
  if (!isInt(room)) return err(400, "meta.room required");

  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > CASTING_CAP) return err(413, "casting too large");
  const bytes = await request.arrayBuffer();
  if (bytes.byteLength > CASTING_CAP) return err(413, "casting too large");
  if (bytes.byteLength === 0) return err(400, "empty body");

  // Hash only; we never parse the rows here (CPU budget).
  const sha256 = hex(await crypto.subtle.digest("SHA-256", bytes));
  if (!timingSafeEqual(sha256, meta.sha256)) return err(400, "hash mismatch", { sha256 });

  const key = r2Key(room, meta.t0, id);
  await env.CASTINGS.put(key, bytes, {
    httpMetadata: { contentType: "application/gzip" },
    customMetadata: { sha256 },
  });

  // Idempotent upsert: keep the earliest received_at and the first uploader;
  // never touch verified_at here (only the read-back in /verify sets it).
  await env.DB.prepare(
    `INSERT INTO castings (id, room, edge, origin, t0, t1, rows, sha256, size, r2_key, received_at, uploaded_by)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)
     ON CONFLICT(id) DO UPDATE SET
       room = excluded.room, edge = excluded.edge, origin = COALESCE(excluded.origin, castings.origin),
       t0 = excluded.t0, t1 = excluded.t1, rows = excluded.rows, sha256 = excluded.sha256,
       size = excluded.size, r2_key = excluded.r2_key,
       received_at = MIN(castings.received_at, excluded.received_at),
       uploaded_by = COALESCE(castings.uploaded_by, excluded.uploaded_by)`,
  ).bind(
    id, room, typeof meta.edge === "string" ? meta.edge : edge, typeof meta.origin === "string" ? meta.origin : null,
    meta.t0, isInt(meta.t1) ? meta.t1 : null, isInt(meta.rows) ? meta.rows : null, sha256,
    bytes.byteLength, key, now(), edge,
  ).run();

  return json({ ok: true, sha256 });
}

async function rollups(request, env) {
  const body = await readJson(request, 4 << 20);
  const casting = typeof body.casting === "string" ? body.casting : null;
  const rows = Array.isArray(body.rows) ? body.rows : null;
  if (!rows) return err(400, "rows required");
  if (rows.length > ROLLUP_CAP) return err(400, `too many rows (max ${ROLLUP_CAP})`);
  for (const r of rows) {
    if (!r || typeof r.uid !== "string" || !r.uid || (r.step !== "5m" && r.step !== "1h") || !isInt(r.ts)
        || !r.data || typeof r.data !== "object") {
      return err(400, "bad rollup row");
    }
  }
  const stmts = [];
  for (const part of chunks(rows, ROLLUP_ROWS_PER_STMT)) {
    const sql = "INSERT OR REPLACE INTO rollups (uid, step, ts, data) VALUES " + part.map(() => "(?, ?, ?, ?)").join(", ");
    const params = [];
    for (const r of part) params.push(r.uid, r.step, r.ts, JSON.stringify(r.data));
    stmts.push(env.DB.prepare(sql).bind(...params));
  }
  // Stamp the casting if we know it (a no-op UPDATE when we do not).
  if (casting) stmts.push(env.DB.prepare("UPDATE castings SET rollups_at = ?1 WHERE id = ?2 AND rollups_at IS NULL").bind(now(), casting));
  if (stmts.length) await env.DB.batch(stmts);
  return json({ ok: true, n: rows.length });
}

// Read-back verification: fetch each object from R2, hash it, compare with
// the stored sha256, and only then stamp verified_at.
async function verify(request, env) {
  const body = await readJson(request);
  const ids = Array.isArray(body.ids) ? body.ids : null;
  if (!ids) return err(400, "ids required");
  if (ids.length > VERIFY_CAP) return err(400, `too many ids (max ${VERIFY_CAP})`);
  if (!ids.every((x) => typeof x === "string" && ID_RE.test(x))) return err(400, "bad id");

  const verified = [], rollupsDone = [], missing = [];
  if (ids.length === 0) return json({ verified, rollups: rollupsDone, missing });

  const { results } = await env.DB.prepare(
    `SELECT id, sha256, r2_key, rollups_at, verified_at FROM castings WHERE id IN (${ids.map(() => "?").join(",")})`,
  ).bind(...ids).all();
  const rows = new Map(results.map((r) => [r.id, r]));

  const checks = ids.map(async (id) => {
    const row = rows.get(id);
    if (!row) return { id, ok: false };
    const obj = await env.CASTINGS.get(row.r2_key);
    if (!obj) return { id, row, ok: false };
    const sha = hex(await crypto.subtle.digest("SHA-256", await obj.arrayBuffer()));
    return { id, row, ok: timingSafeEqual(sha, row.sha256) };
  });
  const stamps = [];
  const ts = now();
  for (const c of await Promise.all(checks)) {
    if (c.row?.rollups_at) rollupsDone.push(c.id);
    if (!c.ok) { missing.push(c.id); continue; }
    verified.push(c.id);
    if (!c.row.verified_at) stamps.push(env.DB.prepare("UPDATE castings SET verified_at = ?1 WHERE id = ?2 AND verified_at IS NULL").bind(ts, c.id));
  }
  if (stamps.length) await env.DB.batch(stamps);
  return json({ verified, rollups: rollupsDone, missing });
}

async function snapshot(request, env, edge) {
  const body = await readJson(request, 2 << 20);
  // A token may only speak for its own Burrow.
  if (body.edge !== edge) return err(403, "edge does not match token");
  const ts = isInt(body.ts) ? body.ts : now();
  const bins = body.bins && typeof body.bins === "object" ? body.bins : {};
  const roster = Array.isArray(body.roster) ? body.roster.filter((r) => r && typeof r.uid === "string" && r.uid) : null;
  const t = now();

  const stmts = [
    env.DB.prepare(
      `INSERT INTO edges (edge_id, room, ts, clk, snapshot, status, roster_at, updated_at)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
       ON CONFLICT(edge_id) DO UPDATE SET
         room = excluded.room, ts = excluded.ts, clk = excluded.clk, snapshot = excluded.snapshot,
         status = excluded.status, roster_at = COALESCE(excluded.roster_at, edges.roster_at),
         updated_at = excluded.updated_at`,
    ).bind(edge, isInt(body.room) ? body.room : null, ts, typeof body.clk === "string" ? body.clk : null,
      JSON.stringify(bins), JSON.stringify(body.status ?? {}), roster ? t : null, t),
  ];
  if (roster && roster.length) {
    for (const part of chunks(roster, BIN_ROWS_PER_STMT)) {
      const sql = "INSERT INTO bins (uid, name, team, period, bin, room, first_seen, last_seen) VALUES "
        + part.map(() => "(?, ?, ?, ?, ?, ?, ?, ?)").join(", ")
        + ` ON CONFLICT(uid) DO UPDATE SET
             name = COALESCE(excluded.name, bins.name), team = COALESCE(excluded.team, bins.team),
             period = COALESCE(excluded.period, bins.period), bin = COALESCE(excluded.bin, bins.bin),
             room = COALESCE(excluded.room, bins.room), last_seen = MAX(COALESCE(bins.last_seen, 0), excluded.last_seen)`;
      const params = [];
      for (const r of part) {
        const seen = isInt(bins[r.uid]?.ts) ? bins[r.uid].ts : ts;
        params.push(r.uid, r.name ?? null, r.team ?? null, isInt(r.period) ? r.period : null,
          isInt(r.bin) ? r.bin : null, isInt(r.room) ? r.room : null, seen, seen);
      }
      stmts.push(env.DB.prepare(sql).bind(...params));
    }
  }
  await env.DB.batch(stmts);
  return json({ ok: true });
}

