// Admin API: team management, visitors, sessions, castings export, stats,
// and the one-time bootstrap. Roles are enforced here.
// teacher: read-only endpoints. admin: everything.

import { listAlerts, listEvents, testNotify } from "./alerts.js";
import { hashPassword, normalizePassphrase } from "./auth.js";
import { HttpError, err, json, now, readJson, safeParse, timingSafeEqual, toInt } from "./util.js";

// Kid-friendly worm/compost words for printed passphrases (3 words, hyphenated).
export const WORDS = [
  "wiggle", "squirm", "wriggle", "humus", "tunnel", "compost", "mulch", "leaf", "soil", "loam",
  "moist", "cocoon", "segment", "bristle", "redworm", "burrow", "casting", "scrap", "peel", "apple",
  "banana", "melon", "coffee", "eggshell", "cardboard", "paper", "bedding", "damp", "dark", "cool",
  "shade", "garden", "sprout", "seed", "root", "stem", "petal", "bloom", "clover", "moss",
  "fern", "pebble", "stone", "dirt", "mud", "puddle", "rain", "dew", "earth", "acorn",
  "pumpkin", "carrot", "lettuce", "celery", "kale", "crumb", "nibble", "munch", "chew", "digest",
  "microbe", "fungi", "recycle", "harvest", "spade", "trowel", "bucket", "lid", "worm", "nutrient",
];

export function makePassphrase() {
  const r = new Uint32Array(3);
  crypto.getRandomValues(r);
  return Array.from(r, (x) => WORDS[x % WORDS.length]).join("-");
}

const ROLES = ["team", "teacher", "admin"];
const IMPORT_CAP = 60;   // PBKDF2 per row; keep one request well inside the CPU budget

function teamRow(t) {
  return { id: t.id, name: t.name, period: t.period, bin: t.bin, room: t.room, role: t.role, created_at: t.created_at, disabled: !!t.disabled };
}

// Returns a Response if access is denied, else null.
export function requireRole(session, roles) {
  if (!session) return err(401, "login required");
  if (!roles.includes(session.role)) return err(403, "forbidden");
  return null;
}

export async function handleAdmin(request, env, ctx, path, session) {
  const m = request.method;
  const sub = path.slice("/api/admin".length);   // "" or "/..."

  if (sub === "/bootstrap" && m === "POST") return bootstrap(request, env);

  const readOnly = requireRole(session, ["admin", "teacher"]);
  const adminOnly = requireRole(session, ["admin"]);

  if (sub === "/edges" && m === "GET") return readOnly || edges(env);
  if (sub === "/visits" && m === "GET") return readOnly || visits(request, env);
  if (sub === "/sessions" && m === "GET") return readOnly || sessions(env);
  if (sub === "/stats" && m === "GET") return readOnly || stats(env);
  if (sub === "/alerts" && m === "GET") return readOnly || listAlerts(env);
  if (sub === "/alerts/test" && m === "POST") return adminOnly || testNotify(env);
  if (sub === "/events" && m === "GET") return readOnly || listEvents(request, env);

  if (sub === "/teams" && m === "GET") return adminOnly || listTeams(env);
  if (sub === "/teams" && m === "POST") return adminOnly || createTeam(request, env);
  if (sub === "/teams/import" && m === "POST") return adminOnly || importTeams(request, env);
  let mt = sub.match(/^\/teams\/(\d+)\/reset$/);
  if (mt && m === "POST") return adminOnly || resetTeam(request, env, Number(mt[1]));
  mt = sub.match(/^\/teams\/(\d+)$/);
  if (mt && m === "DELETE") return adminOnly || deleteTeam(env, Number(mt[1]), session);

  if (sub === "/castings" && m === "GET") return adminOnly || listCastings(request, env);
  mt = sub.match(/^\/castings\/([A-Za-z0-9][A-Za-z0-9_.-]{0,63})$/);
  if (mt && m === "GET") return adminOnly || getCasting(env, mt[1]);

  // Unknown admin path: hide its existence from anonymous callers.
  return readOnly || err(404, "not found");
}

// POST /api/admin/bootstrap {name, password, bootstrap}: creates the first
// admin. Allowed only while no admin exists and the one-time secret matches.
async function bootstrap(request, env) {
  const body = await readJson(request, 16 << 10);
  if (!env.ADMIN_BOOTSTRAP || typeof body.bootstrap !== "string" || !timingSafeEqual(body.bootstrap, env.ADMIN_BOOTSTRAP)) {
    return err(403, "forbidden");
  }
  const existing = await env.DB.prepare("SELECT COUNT(*) AS n FROM teams WHERE role = 'admin'").first();
  if (existing.n > 0) return err(403, "an admin already exists");
  const name = typeof body.name === "string" ? body.name.trim() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!name || name.length > 40) return err(400, "name required");
  if (password.length < 8) return err(400, "password must be at least 8 characters");
  const { pass_hash, pass_salt } = await hashPassword(password);
  const r = await env.DB.prepare(
    "INSERT INTO teams (name, role, pass_hash, pass_salt, created_at) VALUES (?1, 'admin', ?2, ?3, ?4) RETURNING *",
  ).bind(name, pass_hash, pass_salt, now()).first();
  return json({ ok: true, team: teamRow(r) });
}

async function edges(env) {
  const { results } = await env.DB.prepare(
    "SELECT edge_id, room, ts, clk, status, roster_at, updated_at FROM edges ORDER BY edge_id",
  ).all();
  return json({
    ok: true,
    edges: results.map((r) => {
      const status = safeParse(r.status, {}) || {};
      return { edge: r.edge_id, room: r.room, ts: r.ts, clk: r.clk, last_seen: r.updated_at, roster_at: r.roster_at,
        version: status.version ?? null, status };
    }),
  });
}

async function listTeams(env) {
  const { results } = await env.DB.prepare("SELECT * FROM teams ORDER BY role, period, name").all();
  return json({ ok: true, teams: results.map(teamRow) });
}

// A team gets a generated passphrase; staff may bring a real password (>= 8).
// The secret is returned exactly once, here; only hash+salt are stored.
async function credentials(role, givenPassword) {
  if (role === "team" || !givenPassword) {
    const passphrase = makePassphrase();
    return { passphrase, ...(await hashPassword(normalizePassphrase(passphrase))) };
  }
  if (givenPassword.length < 8) throw new HttpError(400, "password must be at least 8 characters");
  return { passphrase: null, ...(await hashPassword(givenPassword)) };
}

async function createTeam(request, env) {
  const b = await readJson(request, 16 << 10);
  const name = typeof b.name === "string" ? b.name.trim() : "";
  if (!name || name.length > 40) return err(400, "name required (max 40)");
  const role = b.role === undefined ? "team" : b.role;
  if (!ROLES.includes(role)) return err(400, "bad role");
  const dup = await env.DB.prepare("SELECT id FROM teams WHERE name = ?1").bind(name).first();
  if (dup) return err(409, "name already exists");
  const cred = await credentials(role, typeof b.password === "string" ? b.password : null);
  const row = await env.DB.prepare(
    `INSERT INTO teams (name, period, bin, room, role, pass_hash, pass_salt, created_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8) RETURNING *`,
  ).bind(name, toInt(b.period, null), toInt(b.bin, null), toInt(b.room, null), role, cred.pass_hash, cred.pass_salt, now()).first();
  return json({ ok: true, team: teamRow(row), passphrase: cred.passphrase });
}

async function resetTeam(request, env, id) {
  const team = await env.DB.prepare("SELECT * FROM teams WHERE id = ?1").bind(id).first();
  if (!team) return err(404, "no such team");
  const b = request.headers.get("content-length") ? await readJson(request, 16 << 10) : {};
  const cred = await credentials(team.role, typeof b.password === "string" ? b.password : null);
  // New secret: every existing session for this login is dropped too.
  await env.DB.batch([
    env.DB.prepare("UPDATE teams SET pass_hash = ?1, pass_salt = ?2 WHERE id = ?3").bind(cred.pass_hash, cred.pass_salt, id),
    env.DB.prepare("DELETE FROM sessions WHERE team_id = ?1").bind(id),
  ]);
  return json({ ok: true, team: teamRow(team), passphrase: cred.passphrase });
}

async function deleteTeam(env, id, session) {
  if (session.team.id === id) return err(400, "cannot delete your own account");
  const team = await env.DB.prepare("SELECT id FROM teams WHERE id = ?1").bind(id).first();
  if (!team) return err(404, "no such team");
  await env.DB.batch([
    env.DB.prepare("DELETE FROM sessions WHERE team_id = ?1").bind(id),
    env.DB.prepare("DELETE FROM teams WHERE id = ?1").bind(id),
  ]);
  return json({ ok: true });
}

// CSV: team,period,bin,room (header optional). Returns the passphrases once.
// Existing names are left alone and reported with passphrase null.
async function importTeams(request, env) {
  const text = await request.text();
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length && /^(team|name)\b/i.test(lines[0])) lines.shift();
  if (!lines.length) return err(400, "no rows");
  if (lines.length > IMPORT_CAP) return err(400, `too many rows (max ${IMPORT_CAP} per request)`);

  const out = [];
  const t = now();
  for (const line of lines) {
    const cells = line.split(",").map((c) => c.trim().replace(/^"(.*)"$/, "$1"));
    const name = cells[0];
    if (!name || name.length > 40) { out.push({ name, error: "bad name" }); continue; }
    const period = toInt(cells[1], null), bin = toInt(cells[2], null), room = toInt(cells[3], null);
    const dup = await env.DB.prepare("SELECT id FROM teams WHERE name = ?1").bind(name).first();
    if (dup) { out.push({ name, period, bin, room, passphrase: null, error: "exists" }); continue; }
    const cred = await credentials("team", null);
    await env.DB.prepare(
      "INSERT INTO teams (name, period, bin, room, role, pass_hash, pass_salt, created_at) VALUES (?1, ?2, ?3, ?4, 'team', ?5, ?6, ?7)",
    ).bind(name, period, bin, room, cred.pass_hash, cred.pass_salt, t).run();
    out.push({ name, period, bin, room, passphrase: cred.passphrase });
  }
  return json(out);
}

// GET /api/admin/visits?since=&team=  -> recent visits + per-team counts
async function visits(request, env) {
  const q = new URL(request.url).searchParams;
  const since = toInt(q.get("since"), now() - 7 * 86400);
  const team = toInt(q.get("team"), null);
  const where = team === null ? "v.ts >= ?1" : "v.ts >= ?1 AND v.team_id = ?2";
  const binds = team === null ? [since] : [since, team];
  const [recent, counts] = await env.DB.batch([
    env.DB.prepare(
      `SELECT v.id, v.ts, v.team_id, t.name AS team, v.first_name, v.path, v.ip_hash
       FROM visits v LEFT JOIN teams t ON t.id = v.team_id WHERE ${where} ORDER BY v.ts DESC LIMIT 500`,
    ).bind(...binds),
    env.DB.prepare(
      `SELECT v.team_id, t.name AS team, COUNT(*) AS n, COUNT(DISTINCT v.first_name) AS people, MAX(v.ts) AS last
       FROM visits v LEFT JOIN teams t ON t.id = v.team_id WHERE ${where} GROUP BY v.team_id ORDER BY n DESC`,
    ).bind(...binds),
  ]);
  return json({ ok: true, since, visits: recent.results, teams: counts.results });
}

// Who is looking right now: sessions seen within 10 min.
async function sessions(env) {
  const { results } = await env.DB.prepare(
    `SELECT s.team_id, t.name AS team, t.role, s.first_name, s.created_at, s.last_seen
     FROM sessions s JOIN teams t ON t.id = s.team_id WHERE s.last_seen >= ?1 ORDER BY s.last_seen DESC LIMIT 500`,
  ).bind(now() - 600).all();
  return json({ ok: true, sessions: results });
}

// GET /api/admin/castings?room=&day=YYYY-MM-DD (UTC)
async function listCastings(request, env) {
  const q = new URL(request.url).searchParams;
  const room = toInt(q.get("room"), null);
  const dayRaw = (q.get("day") || "").replace(/-/g, "");
  const conds = [], binds = [];
  if (room !== null) { binds.push(room); conds.push(`room = ?${binds.length}`); }
  if (dayRaw) {
    if (!/^\d{8}$/.test(dayRaw)) return err(400, "day must be YYYY-MM-DD");
    const t0 = Date.UTC(+dayRaw.slice(0, 4), +dayRaw.slice(4, 6) - 1, +dayRaw.slice(6, 8)) / 1000;
    binds.push(t0, t0 + 86400);
    conds.push(`t0 >= ?${binds.length - 1} AND t0 < ?${binds.length}`);
  }
  const where = conds.length ? "WHERE " + conds.join(" AND ") : "";
  const { results } = await env.DB.prepare(
    `SELECT id, room, edge, origin, t0, t1, rows, sha256, size, r2_key, received_at, uploaded_by, rollups_at, verified_at
     FROM castings ${where} ORDER BY t0 DESC LIMIT 500`,
  ).bind(...binds).all();
  return json({ ok: true, castings: results });
}

// Stream one raw casting from R2 as a download.
async function getCasting(env, id) {
  const row = await env.DB.prepare("SELECT r2_key FROM castings WHERE id = ?1").bind(id).first();
  if (!row) return err(404, "no such casting");
  const obj = await env.CASTINGS.get(row.r2_key);
  if (!obj) return err(404, "object missing in R2");
  return new Response(obj.body, {
    status: 200,
    headers: {
      "content-type": "application/gzip",
      "content-length": String(obj.size),
      "content-disposition": `attachment; filename="${id}.jsonl.gz"`,
      "cache-control": "private, no-store",
      "x-casting-sha256": obj.customMetadata?.sha256 || "",
    },
  });
}

// Row counts from every table in one batch, plus today's writes where we can tell.
async function stats(env) {
  const tables = ["edges", "bins", "castings", "rollups", "teams", "sessions", "visits", "login_attempts"];
  const midnight = Math.floor(Date.now() / 86400000) * 86400;
  const res = await env.DB.batch([
    ...tables.map((t) => env.DB.prepare(`SELECT COUNT(*) AS n FROM ${t}`)),
    env.DB.prepare("SELECT COUNT(*) AS n FROM castings WHERE r2_key IS NOT NULL"),
    env.DB.prepare("SELECT COUNT(*) AS n FROM castings WHERE received_at >= ?1").bind(midnight),
    env.DB.prepare("SELECT COUNT(*) AS n FROM visits WHERE ts >= ?1").bind(midnight),
    env.DB.prepare("SELECT COUNT(*) AS n FROM castings WHERE verified_at IS NULL"),
  ]);
  const counts = {};
  tables.forEach((t, i) => { counts[t] = res[i].results[0].n; });
  const [r2, castingsToday, visitsToday, unverified] = res.slice(tables.length).map((r) => r.results[0].n);
  return json({
    ok: true, ts: now(), counts, r2_objects_estimate: r2, unverified_castings: unverified,
    today: { castings: castingsToday, visits: visitsToday },
  });
}
