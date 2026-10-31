// Messages for a Bin's screen, set on the website.
//   GET  /api/messages?uid=   the bin's five slots and their delivery status
//   POST /api/messages        {uid, slot, pin, title, lines[], start, end, count, boot} or {uid, slot, pin, clear: true}
// A team may fill slots 1-3 of its own bin; a teacher or admin any slot of any bin. The board's
// PIN travels with the message and the board checks it (the Surface never knows PINs). Every
// Burrow gets the undelivered list in its snapshot reply and hands a Bin its items on the next
// push; the Bin answers with msg_seq {slot: seq} (negative: refused) in its data, which the next
// snapshot brings back here (edge.js -> ackMessages).
import { err, isInt, json, now, readJson, safeParse, toInt } from "./util.js";

export const SLOTS = 5;
export const TEAM_SLOTS = 3;
const LINES = 5;
const WIDTH = 16;
const PENDING_DAYS = 30;
const clean = (s) => String(s ?? "").replace(/[^\x20-\x7e]/g, "").trim().slice(0, WIDTH);

async function mayMessage(env, session, uid, slot) {
  if (session.role === "teacher" || session.role === "admin") return null;
  if (slot && slot > TEAM_SLOTS) return err(403, "slots 4 and 5 are the teacher's");
  const b = await env.DB.prepare("SELECT bin, room FROM bins WHERE uid = ?1").bind(uid).first();
  if (!b) return err(404, "unknown bin");
  const t = session.team || {};
  const sameBin = isInt(b.bin) && b.bin === t.bin;
  const sameRoom = b.room == null || t.room == null || b.room === t.room;
  if (!sameBin || !sameRoom) return err(403, "not your bin");
  return null;
}

async function slotsOf(env, uid) {
  const { results } = await env.DB.prepare(
    "SELECT slot, seq, title, lines, start_ts, end_ts, count, boot, cleared, set_by, set_at, delivered_at, result FROM messages WHERE uid = ?1",
  ).bind(uid).all();
  const slots = new Array(SLOTS).fill(null);
  const status = {};
  for (const r of results) {
    if (r.slot < 1 || r.slot > SLOTS) continue;
    status[r.slot] = { seq: r.seq, set_by: r.set_by, set_at: r.set_at, delivered_at: r.delivered_at, result: r.result, pending: r.delivered_at == null };
    if (!r.cleared) {
      slots[r.slot - 1] = { title: r.title || "", lines: safeParse(r.lines, []), start: r.start_ts, end: r.end_ts, count: r.count || 0, boot: !!r.boot };
    }
  }
  return { slots, status };
}

export async function apiMessages(request, env, session) {
  if (!session) return err(401, "login required");
  if (request.method === "GET") {
    const uid = new URL(request.url).searchParams.get("uid") || "";
    if (!uid) return err(400, "uid required");
    const deny = await mayMessage(env, session, uid, 0);
    if (deny) return deny;
    return json({ ok: true, uid, now: now(), role: session.role, ...(await slotsOf(env, uid)) });
  }
  if (request.method !== "POST") return err(405, "method not allowed");
  const body = await readJson(request, 64 << 10);
  const uid = typeof body.uid === "string" ? body.uid.slice(0, 64) : "";
  const slot = toInt(body.slot, 0);
  if (!uid || slot < 1 || slot > SLOTS) return err(400, `uid and slot 1-${SLOTS} required`);
  const deny = await mayMessage(env, session, uid, slot);
  if (deny) return deny;
  const pin = String(body.pin ?? "").replace(/\D/g, "").slice(0, 6);
  if (!pin) return err(400, "the board's PIN is required");
  let row;
  if (body.clear) {
    row = { cleared: 1, title: "", lines: "[]", start: null, end: null, count: 0, boot: 0 };
  } else {
    const title = clean(body.title);
    const lines = (Array.isArray(body.lines) ? body.lines : []).slice(0, LINES).map(clean);
    while (lines.length && !lines[lines.length - 1]) lines.pop();
    if (!title && !lines.some(Boolean)) return err(400, "an empty message");
    const start = isInt(body.start) && body.start > 0 ? body.start : null;
    const end = isInt(body.end) && body.end > 0 ? body.end : null;
    if (start && end && end <= start) return err(400, "the end is before the start");
    row = { cleared: 0, title, lines: JSON.stringify(lines), start, end, count: isInt(body.count) && body.count > 0 ? body.count : 0, boot: body.boot ? 1 : 0 };
  }
  const t = now();
  const seq = ((await env.DB.prepare("SELECT seq FROM messages WHERE uid = ?1 AND slot = ?2").bind(uid, slot).first("seq")) || 0) + 1;
  const who = session.first_name ? `${session.first_name} (${session.team?.name})` : session.team?.name || session.role;
  await env.DB.prepare(
    `INSERT INTO messages (uid, slot, seq, title, lines, start_ts, end_ts, count, boot, cleared, pin, set_by, set_at, delivered_at, result)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, NULL, NULL)
     ON CONFLICT(uid, slot) DO UPDATE SET seq = excluded.seq, title = excluded.title, lines = excluded.lines,
       start_ts = excluded.start_ts, end_ts = excluded.end_ts, count = excluded.count, boot = excluded.boot,
       cleared = excluded.cleared, pin = excluded.pin, set_by = excluded.set_by, set_at = excluded.set_at,
       delivered_at = NULL, result = NULL`,
  ).bind(uid, slot, seq, row.title, row.lines, row.start, row.end, row.count, row.boot, row.cleared, pin, who, t).run();
  return json({ ok: true, uid, now: t, role: session.role, ...(await slotsOf(env, uid)) });
}

// The Bins' acks, as a snapshot carries them: bins[uid].d.msg_seq = {slot: seq} (negative: the
// board refused it, wrong PIN). Returns the UPDATE statements for the snapshot's batch.
export function ackStatements(env, bins, t) {
  const out = [];
  for (const uid of Object.keys(bins)) {
    const ms = bins[uid]?.d?.msg_seq;
    if (!ms || typeof ms !== "object") continue;
    for (const k of Object.keys(ms)) {
      const slot = toInt(k, 0), seq = toInt(ms[k], 0);
      if (slot < 1 || slot > SLOTS || !seq) continue;
      out.push(env.DB.prepare(
        "UPDATE messages SET delivered_at = ?1, result = ?2 WHERE uid = ?3 AND slot = ?4 AND seq = ?5 AND delivered_at IS NULL",
      ).bind(t, seq < 0 ? "refused" : "ok", uid, slot, Math.abs(seq)));
    }
  }
  return out;
}

// Everything not yet acked, for the Burrows (each item as the Bin wants it).
export async function pendingMessages(env) {
  const { results } = await env.DB.prepare(
    "SELECT uid, slot, seq, title, lines, start_ts, end_ts, count, boot, cleared, pin FROM messages WHERE delivered_at IS NULL AND set_at > ?1 ORDER BY set_at LIMIT 200",
  ).bind(now() - PENDING_DAYS * 86400).all();
  return results.map((r) => {
    const it = { uid: r.uid, slot: r.slot, seq: r.seq, pin: r.pin };
    if (r.cleared) return { ...it, clear: true };
    it.title = r.title || "";
    it.lines = safeParse(r.lines, []);
    if (r.start_ts) it.start = r.start_ts;
    if (r.end_ts) it.end = r.end_ts;
    if (r.count) it.count = r.count;
    if (r.boot) it.boot = true;
    return it;
  });
}
