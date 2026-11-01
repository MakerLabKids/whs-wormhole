import { env, SELF } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { applySchema } from "./helpers.js";

const enrol = (body) => SELF.fetch("https://example.com/v1/edge/enrol", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
const ping = (token) => SELF.fetch("https://example.com/v1/edge/ping", { headers: { authorization: "Bearer " + token } });

describe("enrolment: a fresh Pi is told who it is", () => {
  beforeAll(applySchema);

  it("needs the fleet secret and a serial and a room", async () => {
    expect((await enrol({ secret: "nope", serial: "abcdef0123456789", room: 2 })).status).toBe(403);
    expect((await enrol({ secret: "local-enrol-secret", serial: "zz", room: 2 })).status).toBe(400);
    expect((await enrol({ secret: "local-enrol-secret", serial: "abcdef0123456789" })).status).toBe(400);
  });

  it("names it by room, hands out a working token and the room's tunnel token", async () => {
    const r = await enrol({ secret: "local-enrol-secret", serial: "ABCDEF0123456789", room: 2, eth_mac: "88:a2:9e:88:4d:42" });
    expect(r.status).toBe(200);
    const j = await r.json();
    expect(j).toMatchObject({ ok: true, edge: "burrow2", room: 2, tunnel_token: "tunnel-token-2" });
    expect(j.token).toMatch(/^[0-9a-f]{48}$/);
    expect((await ping(j.token)).status).toBe(200);
    // the snapshot is accepted for its own edge name only
    const snap = (edge) => SELF.fetch("https://example.com/v1/edge/snapshot", { method: "POST", headers: { authorization: "Bearer " + j.token, "content-type": "application/json" },
      body: JSON.stringify({ edge, room: 2, ts: 1, bins: {}, status: {} }) });
    expect((await snap("burrow2")).status).toBe(200);
    expect((await snap("burrow1")).status).toBe(403);
    // no tunnel token configured for room 3: none returned
    const k = await (await enrol({ secret: "local-enrol-secret", serial: "1111222233334444", room: 3 })).json();
    expect(k.tunnel_token).toBeUndefined();
  });

  it("a replacement Pi takes over the room; the old token stops; an event says so", async () => {
    const old = await (await enrol({ secret: "local-enrol-secret", serial: "aaaa0000aaaa0000", room: 5 })).json();
    expect((await ping(old.token)).status).toBe(200);
    const fresh = await (await enrol({ secret: "local-enrol-secret", serial: "bbbb1111bbbb1111", room: 5 })).json();
    expect(fresh.edge).toBe("burrow5");
    expect((await ping(old.token)).status).toBe(401);
    expect((await ping(fresh.token)).status).toBe(200);
    const ev = await env.DB.prepare("SELECT level, text FROM events WHERE edge = 'burrow5' ORDER BY id DESC LIMIT 1").first();
    expect(ev.level).toBe("warn");
    expect(ev.text).toContain("replacing aaaa0000aaaa0000");
  });

  it("the static EDGE_TOKENS still work", async () => {
    expect((await ping("tok1")).status).toBe(200);
  });
});

describe("an extra Pi never breaks a room (standby, takeover, step-down)", () => {
  beforeAll(async () => {
    await applySchema();
    await env.DB.prepare("DELETE FROM enrolled WHERE edge LIKE 'burrow2%'").run();     // the tests above used room 2
    await env.DB.prepare("DELETE FROM edges WHERE edge_id LIKE 'burrow2%'").run();
  });
  const SECRET = "local-enrol-secret";
  const snap = (token, edge, room) => SELF.fetch("https://example.com/v1/edge/snapshot", { method: "POST",
    headers: { authorization: "Bearer " + token, "content-type": "application/json" },
    body: JSON.stringify({ edge, room, ts: Math.floor(Date.now() / 1000), bins: {}, status: {} }) });
  const age = (edge, s) => env.DB.prepare("UPDATE edges SET updated_at = ?1 WHERE edge_id = ?2").bind(Math.floor(Date.now() / 1000) - s, edge).run();

  it("a second Pi in a room whose Pi is alive becomes a standby; the room's Pi keeps everything", async () => {
    const a = await (await enrol({ secret: SECRET, serial: "aaaa0000000000a1", room: 2 })).json();
    expect(a).toMatchObject({ edge: "burrow2", role: "primary", tunnel_token: "tunnel-token-2" });
    expect((await snap(a.token, "burrow2", 2)).status).toBe(200);              // it reports: alive
    expect((await enrol({ secret: SECRET, serial: "bbbb0000000000b2", room: 2 })).status).toBe(409);   // an old card is turned away
    expect((await ping(a.token)).status).toBe(200);
    const b = await (await enrol({ secret: SECRET, serial: "bbbb0000000000b2", room: 2, standby_ok: true })).json();
    expect(b).toMatchObject({ edge: "burrow2-sb-00b2", role: "standby", primary: "burrow2", room: 2 });
    expect(b.tunnel_token).toBeUndefined();                                    // never the room's tunnel
    expect((await ping(a.token)).status).toBe(200);                            // the room's Pi is untouched
    expect((await ping(b.token)).status).toBe(200);
    expect((await snap(b.token, "burrow2-sb-00b2", 2)).status).toBe(200);       // the standby reports as itself
    expect((await snap(b.token, "burrow2", 2)).status).toBe(403);
    const ev = await env.DB.prepare("SELECT text FROM events WHERE kind = 'burrow.enrolled' ORDER BY id DESC").first();
    expect(ev.text).toMatch(/standby/);
  });

  it("the standby takes over only once the room's Pi has gone quiet; the old Pi's token stops", async () => {
    let r = await (await enrol({ secret: SECRET, serial: "bbbb0000000000b2", room: 2, promote: true, standby_ok: true })).json();
    expect(r.role).toBe("standby");                                            // burrow2 reported moments ago
    await age("burrow2", 11 * 60);                                             // quiet for 11 minutes
    r = await (await enrol({ secret: SECRET, serial: "bbbb0000000000b2", room: 2, promote: true, standby_ok: true })).json();
    expect(r).toMatchObject({ edge: "burrow2", role: "primary", tunnel_token: "tunnel-token-2" });
    const old = await env.DB.prepare("SELECT replaced FROM enrolled WHERE edge = 'burrow2'").first();
    expect(old.replaced).toBe("aaaa0000000000a1");
    expect((await snap(r.token, "burrow2", 2)).status).toBe(200);
  });

  it("the old Pi, back again, is told it is a standby now (it steps down instead of fighting)", async () => {
    const back = await (await enrol({ secret: SECRET, serial: "aaaa0000000000a1", room: 2, standby_ok: true })).json();
    expect(back).toMatchObject({ edge: "burrow2-sb-00a1", role: "standby", primary: "burrow2" });
  });

  it("a standby's name has no tunnel to probe", async () => {
    const { probeTunnel } = await import("../src/alerts.js");
    expect(await probeTunnel({ TUNNEL_DOMAIN: "x.example" }, "burrow2-sb-00a1")).toBe(null);
  });
});
