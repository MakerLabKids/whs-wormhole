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
