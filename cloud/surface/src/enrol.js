// Enrolment: a Burrow is cattle. A Pi booted from a cloned card asks to be told who it is.
//   POST /v1/enrol {secret, serial, room, eth_mac, wlan_mac}
// secret: the fleet enrolment secret (ENROL_SECRET); room: 0-3, from the subnet its Opal gave it
// (192.168.8<room>.x). Reply: {edge, room, token, tunnel_token?}. The token is new on every
// enrolment; only its sha256 is stored, and the previous Pi's token for that room stops working.
import { err, json, now, readJson, sha256Hex, timingSafeEqual } from "./util.js";

function randomToken() {
  const b = new Uint8Array(24);
  crypto.getRandomValues(b);
  return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
}

export async function enrol(request, env) {
  if (request.method !== "POST") return err(405, "method not allowed");
  if (!env.ENROL_SECRET) return err(503, "enrolment is not configured (ENROL_SECRET)");
  const body = await readJson(request, 16 << 10);
  if (typeof body.secret !== "string" || !timingSafeEqual(body.secret, env.ENROL_SECRET)) return err(403, "bad enrolment secret");
  const serial = typeof body.serial === "string" && /^[0-9a-fA-F]{8,32}$/.test(body.serial) ? body.serial.toLowerCase() : null;
  const room = Number.isInteger(body.room) && body.room >= 0 && body.room <= 9 ? body.room : null;
  if (!serial || room === null) return err(400, "serial (hex) and room (0-9) required");
  const edge = "burrow" + room;
  const token = randomToken();
  const prev = await env.DB.prepare("SELECT serial FROM enrolled WHERE edge = ?1").bind(edge).first();
  const replaced = prev && prev.serial !== serial ? prev.serial : null;
  const mac = (v) => (typeof v === "string" && /^[0-9a-fA-F:]{17}$/.test(v) ? v.toLowerCase() : null);
  const t = now();
  await env.DB.prepare(
    `INSERT INTO enrolled (edge, token_hash, serial, room, eth_mac, wlan_mac, ip, enrolled_at, replaced)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
     ON CONFLICT(edge) DO UPDATE SET token_hash = excluded.token_hash, serial = excluded.serial, room = excluded.room,
       eth_mac = excluded.eth_mac, wlan_mac = excluded.wlan_mac, ip = excluded.ip, enrolled_at = excluded.enrolled_at,
       replaced = excluded.replaced`,
  ).bind(edge, await sha256Hex(token), serial, room, mac(body.eth_mac), mac(body.wlan_mac),
    request.headers.get("cf-connecting-ip") || null, t, replaced).run();
  try {
    await env.DB.prepare("INSERT INTO events (ts, edge, kind, level, text, data, received_at) VALUES (?1, ?2, ?3, ?4, ?5, NULL, ?1)")
      .bind(t, edge, "burrow.enrolled", replaced ? "warn" : "info",
        replaced ? `a new Pi (${serial}) took over ${edge}, replacing ${replaced}` : `Pi ${serial} enrolled as ${edge}`).run();
  } catch (e) { /* the enrolment stands either way */ }
  const tunnels = (() => { try { return JSON.parse(env.TUNNEL_TOKENS || "{}"); } catch (e) { return {}; } })();
  const out = { ok: true, edge, room, token };
  if (typeof tunnels[edge] === "string" && tunnels[edge]) out.tunnel_token = tunnels[edge];
  return json(out);
}

// the edge owning an enrolled token, or null
export async function authEnrolled(request, env) {
  const h = request.headers.get("authorization") || "";
  if (!h.startsWith("Bearer ")) return null;
  const token = h.slice(7).trim();
  if (!token || token.length > 128) return null;
  try {
    const r = await env.DB.prepare("SELECT edge FROM enrolled WHERE token_hash = ?1").bind(await sha256Hex(token)).first();
    return r ? r.edge : null;
  } catch (e) {
    return null;          // no table yet (schema not applied): static tokens only
  }
}
