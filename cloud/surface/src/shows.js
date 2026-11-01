// Shows for a Bin's screen, sent from the website (phase 2 of "make your own show").
//   GET  /api/shows?uid=                 the bin's files, playlist, and whether the board has them
//   POST /api/shows {uid, name, pbm}     add or replace a show (pbm = base64 of a P4 PBM file)
//   POST /api/shows {uid, delete: name}  remove one
//   POST /api/shows {uid, list: [...]}   the playlist in order (built-in names or file names); null = default
// A team may change its own bin, a teacher or admin any (as for messages). Every change bumps the
// bin's rev. Burrows learn the pending bins from their snapshot reply (pendingShows), fetch files by
// sha256 (GET /v1/edge/shows/<sha>, edgeShowFile), and the board reports shows_rev in its data
// (ackShowStatements) once its shows/ folder matches.
import { mayMessage } from "./messages.js";
import { err, isInt, json, now, readJson, safeParse, sha256Hex } from "./util.js";

export const MAX_W = 128, MAX_H = 64, MAX_FRAMES = 100;
export const MAX_FILE = 110 * 1024;          // one show (100 full frames is ~102 KB)
export const MAX_TOTAL = 512 * 1024;         // a bin's shows together (the board keeps room for readings)
export const MAX_FILES = 20;
export const BUILTINS = ["Big Worm", "Worm Party", "Wormhole", "Underground", "Worm Pulse",
  "Compost", "Hello Worm", "Worm Lab", "Conga", "Worm Radar"];
const NAME_RE = /^[a-z0-9][a-z0-9-]{0,23}$/;
const key = (s) => String(s).toLowerCase().replace(/[^a-z0-9]/g, "");

// The same checks as lib/pbmshow.py's scan(): P4 frames back to back, one size, <= 128x64, <= 100.
export function scanPbm(bytes) {
  let i = 0, frames = 0, size = null;
  const tok = () => {
    let t = "";
    while (i < bytes.length) {
      const c = bytes[i];
      if (c === 35) { while (i < bytes.length && bytes[i] !== 10) i++; if (t) return t; continue; }   // '#' to end of line
      i++;
      if (c === 32 || c === 9 || c === 10 || c === 13) { if (t) return t; continue; }
      t += String.fromCharCode(c);
      if (t.length > 8) return t;
    }
    return t || null;
  };
  while (i < bytes.length) {
    const m = tok();
    if (m === null) break;
    if (m !== "P4") throw new Error(`not a show file (frame ${frames + 1} is not a P4 PBM)`);
    const w = Number(tok()), h = Number(tok());
    if (!Number.isInteger(w) || !Number.isInteger(h)) throw new Error(`bad size in frame ${frames + 1}`);
    if (w < 1 || h < 1 || w > MAX_W || h > MAX_H) throw new Error(`${w}x${h} is bigger than ${MAX_W}x${MAX_H}`);
    if (size && (size[0] !== w || size[1] !== h)) throw new Error(`frame ${frames + 1} is ${w}x${h}, the first was ${size[0]}x${size[1]}`);
    size = [w, h];
    i += Math.ceil(w / 8) * h;
    if (i > bytes.length) throw new Error("the last frame is cut short");
    if (++frames > MAX_FRAMES) throw new Error(`more than ${MAX_FRAMES} frames`);
  }
  if (!frames) throw new Error("empty file");
  return { frames, w: size[0], h: size[1] };
}

function fromB64(s) {
  const bin = atob(String(s || ""));
  const out = new Uint8Array(bin.length);
  for (let k = 0; k < bin.length; k++) out[k] = bin.charCodeAt(k);
  return out;
}

async function bump(env, uid, by, t, list) {
  // list: undefined keeps the playlist; null or an array sets it
  const cur = await env.DB.prepare("SELECT rev, list FROM show_lists WHERE uid = ?1").bind(uid).first();
  const rev = (cur?.rev || 0) + 1;
  const keep = list === undefined ? (cur?.list ?? null) : (list === null ? null : JSON.stringify(list));
  await env.DB.prepare(`INSERT INTO show_lists (uid, rev, list, set_by, set_at) VALUES (?1, ?2, ?3, ?4, ?5)
      ON CONFLICT(uid) DO UPDATE SET rev = excluded.rev, list = excluded.list, set_by = excluded.set_by, set_at = excluded.set_at`)
    .bind(uid, rev, keep, by, t).run();
  return rev;
}

async function showsOf(env, uid) {
  const { results } = await env.DB.prepare(
    "SELECT name, sha256, size, frames, w, h, set_by, set_at FROM show_files WHERE uid = ?1 ORDER BY name").bind(uid).all();
  const l = await env.DB.prepare("SELECT rev, list, set_by, set_at, board_rev, board_at FROM show_lists WHERE uid = ?1").bind(uid).first();
  return {
    files: results, list: l ? safeParse(l.list, null) : null, rev: l?.rev || 0,
    board_rev: l?.board_rev ?? null, board_at: l?.board_at ?? null,
    on_board: !l || l.board_rev === l.rev, builtins: BUILTINS,
    used: results.reduce((a, r) => a + (r.size || 0), 0), limit: MAX_TOTAL,
  };
}

export async function apiShows(request, env, session) {
  if (!session) return err(401, "login required");
  const t = now();
  const by = session.first_name ? `${session.first_name} (${session.team?.name || session.role})` : (session.team?.name || session.role);
  if (request.method === "GET") {
    const uid = new URL(request.url).searchParams.get("uid") || "";
    const no = await mayMessage(env, session, uid, 0);
    if (no) return no;
    return json({ ok: true, uid, ...(await showsOf(env, uid)) });
  }
  if (request.method !== "POST") return err(405, "method not allowed");
  const body = await readJson(request, 200 * 1024);
  const uid = String(body.uid || "");
  const no = await mayMessage(env, session, uid, 0);
  if (no) return no;

  if (typeof body.delete === "string") {
    const r = await env.DB.prepare("DELETE FROM show_files WHERE uid = ?1 AND name = ?2").bind(uid, body.delete).run();
    if (!r.meta?.changes) return err(404, "no show called " + body.delete);
    const cur = await env.DB.prepare("SELECT list FROM show_lists WHERE uid = ?1").bind(uid).first();
    const list = safeParse(cur?.list, null);
    await bump(env, uid, by, t, Array.isArray(list) ? list.filter((n) => key(n) !== key(body.delete)) : undefined);
    return json({ ok: true, uid, ...(await showsOf(env, uid)) });
  }

  if (body.list !== undefined) {
    if (body.list !== null && !Array.isArray(body.list)) return err(400, "list must be an array of names, or null");
    let list = null;
    if (Array.isArray(body.list)) {
      const files = (await env.DB.prepare("SELECT name FROM show_files WHERE uid = ?1").bind(uid).all()).results.map((r) => r.name);
      const known = new Map([...BUILTINS, ...files].map((n) => [key(n), n]));
      list = [];
      for (const n of body.list.slice(0, 40)) {
        const k = known.get(key(n));
        if (!k) return err(400, `no show called "${n}"`);
        list.push(k);
      }
    }
    await bump(env, uid, by, t, list);
    return json({ ok: true, uid, ...(await showsOf(env, uid)) });
  }

  const name = String(body.name || "");
  if (!NAME_RE.test(name)) return err(400, "name: lowercase letters, numbers and dashes, up to 24");
  if (BUILTINS.some((b) => key(b) === key(name))) return err(400, `"${name}" is a built-in show's name`);
  let bytes;
  try { bytes = fromB64(body.pbm); } catch (e) { return err(400, "pbm must be base64"); }
  if (bytes.length > MAX_FILE) return err(413, `a show can be ${MAX_FILE / 1024} KB at most`);
  let info;
  try { info = scanPbm(bytes); } catch (e) { return err(400, e.message); }
  const others = (await env.DB.prepare("SELECT name, size FROM show_files WHERE uid = ?1 AND name != ?2").bind(uid, name).all()).results;
  if (others.length >= MAX_FILES) return err(413, `a bin can have ${MAX_FILES} shows`);
  const used = others.reduce((a, r) => a + (r.size || 0), 0);
  if (used + bytes.length > MAX_TOTAL) return err(413, `that would make ${Math.round((used + bytes.length) / 1024)} KB of shows; a bin has room for ${MAX_TOTAL / 1024} KB`);
  const sha = await sha256Hex(bytes);
  await env.DB.prepare(`INSERT INTO show_files (uid, name, sha256, size, frames, w, h, data, set_by, set_at)
      VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)
      ON CONFLICT(uid, name) DO UPDATE SET sha256 = excluded.sha256, size = excluded.size, frames = excluded.frames,
        w = excluded.w, h = excluded.h, data = excluded.data, set_by = excluded.set_by, set_at = excluded.set_at`)
    .bind(uid, name, sha, bytes.length, info.frames, info.w, info.h, body.pbm, by, t).run();
  await bump(env, uid, by, t, undefined);
  return json({ ok: true, uid, name, sha256: sha, ...info, ...(await showsOf(env, uid)) });
}

// For a snapshot reply: every bin whose board has not reported the newest rev.
export async function pendingShows(env) {
  const { results } = await env.DB.prepare(
    "SELECT uid, rev, list FROM show_lists WHERE board_rev IS NULL OR board_rev != rev ORDER BY set_at LIMIT 90").all();
  if (!results.length) return [];
  const files = (await env.DB.prepare(
    `SELECT uid, name, sha256, size FROM show_files WHERE uid IN (${results.map(() => "?").join(", ")}) ORDER BY name`)
    .bind(...results.map((r) => r.uid)).all()).results;          // one query for all of them (subrequest limits)
  return results.map((r) => ({ uid: r.uid, rev: r.rev, list: safeParse(r.list, null),
    files: files.filter((f) => f.uid === r.uid).map((f) => ({ name: f.name, sha256: f.sha256, size: f.size })) }));
}

// The boards' shows_rev, riding in their data in a snapshot.
export function ackShowStatements(env, bins, t) {
  const out = [];
  for (const uid of Object.keys(bins || {})) {
    const r = bins[uid]?.d?.shows_rev;
    if (!isInt(r) || r < 0) continue;
    out.push(env.DB.prepare("UPDATE show_lists SET board_rev = ?1, board_at = ?2 WHERE uid = ?3 AND (board_rev IS NULL OR board_rev != ?1)")
      .bind(r, t, uid));
  }
  return out;
}

// GET /v1/edge/shows/<sha256>: the file, for a Burrow to cache and hand to its Bins.
export async function edgeShowFile(env, sha) {
  if (!/^[0-9a-f]{64}$/.test(sha)) return err(400, "bad sha256");
  const r = await env.DB.prepare("SELECT data FROM show_files WHERE sha256 = ?1 LIMIT 1").bind(sha).first();
  if (!r) return err(404, "no such show");
  return new Response(fromB64(r.data), { headers: { "Content-Type": "image/x-portable-bitmap", "Cache-Control": "no-store" } });
}
