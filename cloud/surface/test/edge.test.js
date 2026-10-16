import { env, SELF } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { applySchema, bootstrapAdmin, createTeam, edgeFetch, get, loginTeam, makeCasting, putCasting, sampleRows, sha256Hex } from "./helpers.js";

const T0 = Date.UTC(2026, 9, 16, 14, 15) / 1000; // 2026-10-16T14:15Z

describe("edge token auth", () => {
  beforeAll(applySchema);

  it("rejects missing and wrong tokens", async () => {
    let r = await SELF.fetch("https://example.com/v1/edge/ping");
    expect(r.status).toBe(401);
    expect(await r.json()).toEqual({ ok: false, error: "unauthorized" });
    r = await SELF.fetch("https://example.com/v1/edge/ping", { headers: { authorization: "Bearer nope" } });
    expect(r.status).toBe(401);
  });

  it("pings with a valid token", async () => {
    const r = await edgeFetch("burrow1", "/v1/edge/ping");
    expect(r.status).toBe(200);
    const j = await r.json();
    expect(j.ok).toBe(true);
    expect(Math.abs(j.ts - Date.now() / 1000)).toBeLessThan(5);
  });

  it("refuses a snapshot whose edge does not match the token", async () => {
    const r = await edgeFetch("burrow2", "/v1/edge/snapshot", {
      method: "POST", body: JSON.stringify({ edge: "burrow1", room: 1, ts: 1, bins: {}, status: {} }),
    });
    expect(r.status).toBe(403);
    expect((await r.json()).ok).toBe(false);
  });

  it("returns JSON 404/405 for unknown edge paths", async () => {
    expect((await edgeFetch("burrow1", "/v1/edge/nope")).status).toBe(404);
    expect((await edgeFetch("burrow1", "/v1/edge/snapshot")).status).toBe(405);
  });
});

describe("castings: PUT + verify", () => {
  beforeAll(applySchema);

  it("rejects a hash mismatch with 400 and stores nothing", async () => {
    const { gz, meta } = await makeCasting("r1-20261016T1415", T0);
    const r = await putCasting("burrow1", "r1-20261016T1415", gz, { ...meta, sha256: "0".repeat(64) });
    expect(r.status).toBe(400);
    const j = await r.json();
    expect(j.ok).toBe(false);
    expect(j.error).toBe("hash mismatch");
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM castings").first("n")).toBe(0);
  });

  it("rejects a missing meta header", async () => {
    const { gz } = await makeCasting("r1-20261016T1415", T0);
    const r = await edgeFetch("burrow1", "/v1/edge/castings/r1-20261016T1415", { method: "PUT", body: gz });
    expect(r.status).toBe(400);
  });

  it("stores, is idempotent, verifies, and reports tampering as missing", async () => {
    const id = "r1-20261016T1415";
    const { gz, meta } = await makeCasting(id, T0);

    let r = await putCasting("burrow1", id, gz, meta);
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual({ ok: true, sha256: meta.sha256 });

    // R2 key is dated from t0 in UTC and carries the hash as metadata.
    const key = `castings/r1/2026/10/16/${id}.jsonl.gz`;
    const obj = await env.CASTINGS.get(key);
    expect(obj).not.toBeNull();
    expect(obj.customMetadata.sha256).toBe(meta.sha256);
    expect(obj.httpMetadata.contentType).toBe("application/gzip");
    expect(await sha256Hex(new Uint8Array(await obj.arrayBuffer()))).toBe(meta.sha256);

    const row = await env.DB.prepare("SELECT * FROM castings WHERE id = ?").bind(id).first();
    expect(row.r2_key).toBe(key);
    expect(row.uploaded_by).toBe("burrow1");
    expect(row.size).toBe(gz.length);
    expect(row.verified_at).toBeNull();

    // A mirror re-uploading the same casting is a no-op (earliest received_at kept).
    r = await putCasting("burrow2", id, gz, meta);
    expect(r.status).toBe(200);
    const row2 = await env.DB.prepare("SELECT * FROM castings WHERE id = ?").bind(id).first();
    expect(row2.received_at).toBe(row.received_at);
    expect(row2.uploaded_by).toBe("burrow1");
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM castings").first("n")).toBe(1);

    // Verify: read back from R2, hash, stamp.
    r = await edgeFetch("burrow1", "/v1/edge/verify", { method: "POST", body: JSON.stringify({ ids: [id, "r1-20000101T0000"] }) });
    expect(r.status).toBe(200);
    let v = await r.json();
    expect(v.verified).toEqual([id]);
    expect(v.rollups).toEqual([]);
    expect(v.missing).toEqual(["r1-20000101T0000"]);
    const stamped = await env.DB.prepare("SELECT verified_at FROM castings WHERE id = ?").bind(id).first("verified_at");
    expect(stamped).toBeGreaterThan(0);

    // Tamper with the object in R2: the next verify must say missing.
    await env.CASTINGS.put(key, new Uint8Array([1, 2, 3]));
    r = await edgeFetch("burrow1", "/v1/edge/verify", { method: "POST", body: JSON.stringify({ ids: [id] }) });
    v = await r.json();
    expect(v.missing).toEqual([id]);
    expect(v.verified).toEqual([]);

    // Delete it: still missing.
    await env.CASTINGS.delete(key);
    r = await edgeFetch("burrow1", "/v1/edge/verify", { method: "POST", body: JSON.stringify({ ids: [id] }) });
    expect((await r.json()).missing).toEqual([id]);

    // Re-upload heals it, and verified_at was never cleared by the PUT.
    await putCasting("burrow1", id, gz, meta);
    r = await edgeFetch("burrow1", "/v1/edge/verify", { method: "POST", body: JSON.stringify({ ids: [id] }) });
    expect((await r.json()).verified).toEqual([id]);
  });

  it("caps verify at 40 ids", async () => {
    const ids = Array.from({ length: 41 }, (_, i) => `r1-20261016T${String(i).padStart(4, "0")}`);
    const r = await edgeFetch("burrow1", "/v1/edge/verify", { method: "POST", body: JSON.stringify({ ids }) });
    expect(r.status).toBe(400);
  });
});

describe("rollups + history", () => {
  let cookie;
  beforeAll(async () => {
    await applySchema();
    const admin = await bootstrapAdmin();
    const t = await createTeam(admin.cookie, { name: "Dirt Vader", period: 3, bin: 7, room: 1 });
    cookie = (await loginTeam(t.team.id, t.passphrase)).cookie;
  });

  it("inserts rows in batches, stamps rollups_at, and serves history with auto step", async () => {
    const id = "r1-20261016T1415";
    const { gz, meta } = await makeCasting(id, T0);
    await putCasting("burrow1", id, gz, meta);

    // 60 rows at 5m (more than one 25-row statement) plus some hourly ones.
    const rows = [];
    for (let i = 0; i < 60; i++) rows.push({ uid: "aaa", step: "5m", ts: T0 + i * 300, data: { temp: [20, 20.5, 21, 5] } });
    for (let i = 0; i < 5; i++) rows.push({ uid: "aaa", step: "1h", ts: T0 - (T0 % 3600) + i * 3600, data: { temp: [19, 20.5, 22, 60] } });
    let r = await edgeFetch("burrow1", "/v1/edge/rollups", { method: "POST", body: JSON.stringify({ casting: id, rows }) });
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual({ ok: true, n: 65 });
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM rollups").first("n")).toBe(65);
    expect(await env.DB.prepare("SELECT rollups_at FROM castings WHERE id = ?").bind(id).first("rollups_at")).toBeGreaterThan(0);

    // Re-sending the same rows replaces, never duplicates.
    rows[0].data = { temp: [1, 2, 3, 4] };
    r = await edgeFetch("burrow1", "/v1/edge/rollups", { method: "POST", body: JSON.stringify({ casting: id, rows }) });
    expect(r.status).toBe(200);
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM rollups").first("n")).toBe(65);

    // verify now reports the casting under rollups too.
    r = await edgeFetch("burrow1", "/v1/edge/verify", { method: "POST", body: JSON.stringify({ ids: [id] }) });
    const v = await r.json();
    expect(v.verified).toEqual([id]);
    expect(v.rollups).toEqual([id]);

    // History, 1 day span -> 5m.
    r = await get(`/api/history?uid=aaa&from=${T0}&to=${T0 + 86400}`, { cookie });
    expect(r.status).toBe(200);
    let h = await r.json();
    expect(h.step).toBe("5m");
    expect(h.uid).toBe("aaa");
    expect(h.points.length).toBe(60);
    expect(h.points[0]).toEqual([T0, { temp: [1, 2, 3, 4] }]);

    // 10 day span -> 1h.
    r = await get(`/api/history?uid=aaa&from=${T0 - 5 * 86400}&to=${T0 + 5 * 86400}`, { cookie });
    h = await r.json();
    expect(h.step).toBe("1h");
    expect(h.points.length).toBe(5);

    // Explicit step wins; missing uid is a 400; no cookie is a 401.
    r = await get(`/api/history?uid=aaa&from=${T0 - 5 * 86400}&to=${T0 + 5 * 86400}&step=5m`, { cookie });
    expect((await r.json()).step).toBe("5m");
    expect((await get("/api/history", { cookie })).status).toBe(400);
    expect((await get(`/api/history?uid=aaa`)).status).toBe(401);
  });

  it("rejects malformed rows", async () => {
    const r = await edgeFetch("burrow1", "/v1/edge/rollups", {
      method: "POST", body: JSON.stringify({ casting: "x", rows: [{ uid: "a", step: "7m", ts: 1, data: {} }] }),
    });
    expect(r.status).toBe(400);
  });
});

describe("snapshot merge in /api/now", () => {
  let cookie;
  beforeAll(async () => {
    await applySchema();
    const admin = await bootstrapAdmin();
    const t = await createTeam(admin.cookie, { name: "Dirt Vader", period: 3, bin: 7, room: 1 });
    cookie = (await loginTeam(t.team.id, t.passphrase)).cookie;
  });

  const snap = (edge, room, ts, bins, roster) => edgeFetch(edge, "/v1/edge/snapshot", {
    method: "POST",
    body: JSON.stringify({ edge, room, ts, clk: "ntp", bins, status: { version: "0.1", up_s: 42, bins: Object.keys(bins).length }, ...(roster ? { roster } : {}) }),
  });

  it("newest ts wins across edges; edges carry status + ts + clk; roster fills bins", async () => {
    const t = Math.floor(Date.now() / 1000);
    let r = await snap("burrow1", 1, t, {
      aaa: { ts: t - 10, clk: "ntp", src: "push", name: "A", team: "Team A", period: 3, bin: 1, room: 1, d: { temp: 20 } },
      bbb: { ts: t - 5, clk: "ntp", src: "push", name: "B", team: "Team B", period: 3, bin: 2, room: 1, d: { temp: 21 } },
    }, [{ uid: "aaa", name: "A", team: "Team A", period: 3, bin: 1, room: 1 }, { uid: "bbb", name: "B", team: "Team B", period: 3, bin: 2, room: 1 }]);
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual({ ok: true });

    // bbb failed over to burrow2 and was seen there more recently.
    r = await snap("burrow2", 2, t, {
      bbb: { ts: t - 1, clk: "peer", src: "push", name: "B", team: "Team B", period: 3, bin: 2, room: 2, d: { temp: 22 } },
    });
    expect(r.status).toBe(200);

    r = await get("/api/now", { cookie });
    expect(r.status).toBe(200);
    expect(r.headers.get("cache-control")).toBe("public, max-age=10");
    const j = await r.json();
    expect(Object.keys(j.edges).sort()).toEqual(["burrow1", "burrow2"]);
    expect(j.edges.burrow1).toMatchObject({ ts: t, clk: "ntp", room: 1, version: "0.1", up_s: 42 });
    expect(j.bins.aaa.d.temp).toBe(20);
    expect(j.bins.aaa.edge).toBe("burrow1");
    expect(j.bins.bbb.d.temp).toBe(22);          // the newer entry from burrow2 won
    expect(j.bins.bbb.edge).toBe("burrow2");
    expect(j.bins.bbb.stale).toBe(false);

    // Roster landed in bins (upsert) and /api/bins serves it with "seen".
    r = await get("/api/bins", { cookie });
    const bins = await r.json();
    expect(bins.aaa).toEqual({ name: "A", team: "Team A", period: 3, bin: 1, room: 1, seen: t - 10 });
    expect(bins.bbb.seen).toBe(t - 5);

    // One edges row per Burrow, rewritten in place.
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM edges").first("n")).toBe(2);
    await snap("burrow1", 1, t + 1, {});
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM edges").first("n")).toBe(2);
    expect(await env.DB.prepare("SELECT ts FROM edges WHERE edge_id='burrow1'").first("ts")).toBe(t + 1);
  });

  it("/api/now needs a cookie, and the cached copy is never handed to an anonymous caller", async () => {
    let r = await get("/api/now", { cookie });
    expect(r.status).toBe(200);
    r = await get("/api/now");
    expect(r.status).toBe(401);
    expect(await r.json()).toEqual({ ok: false, error: "login required" });
  });
});
