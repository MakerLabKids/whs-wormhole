// Logins, sessions and the cookie. Roles: team | teacher | admin.
//
// Password hashing: PBKDF2-SHA256, 100000 iterations (the Workers maximum),
// 16-byte salt, 32-byte hash, hex in D1.
// Cookie: wh_session=<sessionId>.<hmac-sha256-base64url(sessionId, SESSION_SECRET)>
// The D1 row is keyed by sha256(sessionId), so a database dump cannot forge cookies.

import { err, hex, hmacB64url, ipHash, json, now, parseCookies, randomHex, readJson, sha256Hex, timingSafeEqual } from "./util.js";

export const COOKIE = "wh_session";
const COOKIE_MAX_AGE = 180 * 86400;      // a semester, roughly
const SESSION_BUMP_S = 300;              // last_seen bumped at most every 5 min
const LOGIN_WINDOW_S = 600;
const LOGIN_MAX_ATTEMPTS = 10;
const PBKDF2_ITER = 100000;
const enc = new TextEncoder();

export async function pbkdf2Hex(password, saltHex) {
  const salt = new Uint8Array(saltHex.match(/../g).map((h) => parseInt(h, 16)));
  const key = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: PBKDF2_ITER }, key, 256);
  return hex(bits);
}

export async function hashPassword(password) {
  const pass_salt = randomHex(16);
  return { pass_salt, pass_hash: await pbkdf2Hex(password, pass_salt) };
}

export async function verifyPassword(password, team) {
  if (!team.pass_hash || !team.pass_salt) return false;
  return timingSafeEqual(await pbkdf2Hex(password, team.pass_salt), team.pass_hash);
}

// Kids type passphrases from a printed card: ignore case, stray spaces, and
// whether they used spaces or hyphens between the words.
export function normalizePassphrase(s) {
  return String(s).trim().toLowerCase().replace(/[\s_]+/g, "-").replace(/-+/g, "-");
}

const NAME_RE = /^\p{L}[\p{L}' -]*$/u;
export function cleanFirstName(v) {
  if (typeof v !== "string") return null;
  const s = v.trim().replace(/\s+/g, " ");
  if (!s || s.length > 24 || !NAME_RE.test(s)) return null;
  return s;
}

function publicTeam(t) {
  return { id: t.id, name: t.name, period: t.period, bin: t.bin, room: t.room, role: t.role };
}

function cookieHeader(value, maxAge) {
  return `${COOKIE}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
}

// Resolve the cookie to {role, team, first_name, token_hash} or null.
// Bumps sessions.last_seen in the background when it is older than 5 min.
export async function getSession(request, env, ctx) {
  const raw = parseCookies(request)[COOKIE];
  if (!raw || !env.SESSION_SECRET) return null;
  const dot = raw.indexOf(".");
  if (dot <= 0) return null;
  const sid = raw.slice(0, dot), sig = raw.slice(dot + 1);
  if (!/^[0-9a-f]{32,64}$/.test(sid)) return null;
  if (!timingSafeEqual(sig, await hmacB64url(sid, env.SESSION_SECRET))) return null;

  const token_hash = await sha256Hex(sid);
  const row = await env.DB.prepare(
    `SELECT s.token_hash, s.first_name, s.last_seen, t.id, t.name, t.period, t.bin, t.room, t.role, t.disabled
     FROM sessions s JOIN teams t ON t.id = s.team_id WHERE s.token_hash = ?1`,
  ).bind(token_hash).first();
  if (!row || row.disabled) return null;

  const t = now();
  if (t - (row.last_seen || 0) > SESSION_BUMP_S) {
    const p = env.DB.prepare("UPDATE sessions SET last_seen = ?1 WHERE token_hash = ?2").bind(t, token_hash).run();
    if (ctx) ctx.waitUntil(p); else await p;
  }
  return { role: row.role, team: publicTeam(row), first_name: row.first_name, token_hash };
}

export function meBody(s) {
  return { ok: true, role: s.role, team: s.team, first_name: s.first_name };
}

// GET /api/teams (public): what the login dropdown shows.
export async function listTeams(env) {
  const { results } = await env.DB.prepare(
    "SELECT id, name, period FROM teams WHERE role = 'team' AND disabled = 0 ORDER BY period, name",
  ).all();
  return json(results, 200, { "cache-control": "public, max-age=60" });
}

// Count this attempt and tell whether the IP is over the limit for the window.
async function overLimit(env, ip_hash) {
  const win = now() - (now() % LOGIN_WINDOW_S);
  const [, cnt] = await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO login_attempts (ip_hash, window_start, n) VALUES (?1, ?2, 1)
       ON CONFLICT(ip_hash, window_start) DO UPDATE SET n = n + 1`,
    ).bind(ip_hash, win),
    env.DB.prepare("SELECT n FROM login_attempts WHERE ip_hash = ?1 AND window_start = ?2").bind(ip_hash, win),
  ]);
  return (cnt.results[0]?.n || 0) > LOGIN_MAX_ATTEMPTS;
}

// POST /api/login {team_id | name, passphrase, first_name}
export async function login(request, env) {
  const body = await readJson(request, 16 << 10);
  const ip_hash = await ipHash(request, env);
  if (await overLimit(env, ip_hash)) return err(429, "too many attempts; try again in 10 minutes");

  const passphrase = typeof body.passphrase === "string" ? body.passphrase : (typeof body.password === "string" ? body.password : "");
  let team = null;
  if (body.team_id !== undefined && body.team_id !== null && body.team_id !== "") {
    team = await env.DB.prepare("SELECT * FROM teams WHERE id = ?1").bind(Number(body.team_id)).first();
  } else if (typeof body.name === "string") {
    team = await env.DB.prepare("SELECT * FROM teams WHERE name = ?1").bind(body.name.trim()).first();
  } else {
    return err(400, "team_id required");
  }
  if (!team || team.disabled) return err(401, "wrong team or passphrase");

  // Students must type a first name; staff accounts default to their own name.
  let first_name = cleanFirstName(body.first_name);
  if (!first_name) {
    if (team.role === "team") return err(400, "first name required (letters, spaces, - or ', max 24)");
    first_name = team.name.slice(0, 24);
  }

  const candidate = team.role === "team" ? normalizePassphrase(passphrase) : passphrase;
  if (!candidate || !(await verifyPassword(candidate, team))) return err(401, "wrong team or passphrase");

  const sid = randomHex(32);
  const sig = await hmacB64url(sid, env.SESSION_SECRET);
  const t = now();
  await env.DB.prepare(
    "INSERT INTO sessions (token_hash, team_id, first_name, created_at, last_seen, ua) VALUES (?1, ?2, ?3, ?4, ?4, ?5)",
  ).bind(await sha256Hex(sid), team.id, first_name, t, (request.headers.get("user-agent") || "").slice(0, 200)).run();

  const me = { ok: true, me: { role: team.role, team: publicTeam(team), first_name } };
  return json(me, 200, { "set-cookie": cookieHeader(`${sid}.${sig}`, COOKIE_MAX_AGE) });
}

// POST /api/logout: forget the session and clear the cookie.
export async function logout(request, env, session) {
  if (session) await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?1").bind(session.token_hash).run();
  return json({ ok: true }, 200, { "set-cookie": cookieHeader("", 0) });
}
