import { env, SELF } from "cloudflare:test";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { applySchema, bootstrapAdmin, createTeam, edgeFetch, get, loginTeam, postJson, sha256Hex } from "./helpers.js";

const TARBALL = new TextEncoder().encode("fake tarball bytes for abcdef1");

async function snapshot(edge, status = {}) {
  const body = { edge, room: 1, ts: Math.floor(Date.now() / 1000), clk: "ntp", bins: {}, status };
  const r = await edgeFetch(edge, "/v1/edge/snapshot", { method: "POST", body: JSON.stringify(body) });
  expect(r.status).toBe(200);
  return r.json();
}

describe("rollouts: one Burrow at a time, by a click", () => {
  let admin, teacherCookie, realFetch;
  beforeAll(async () => {
    await applySchema();
    admin = await bootstrapAdmin();
    const t = await createTeam(admin.cookie, { name: "Mr Soil", role: "teacher", password: "teacher-pass-123" });
    teacherCookie = (await loginTeam(t.team.id, "teacher-pass-123")).cookie;
    // GitHub, stubbed: the worker's outbound fetch is this isolate's global
    realFetch = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("codeload.github.com")) {
        return url.endsWith("/abcdef1") ? new Response(TARBALL, { status: 200 }) : new Response("nope", { status: 404 });
      }
      return realFetch(input, init);
    };
  });
  afterAll(() => { globalThis.fetch = realFetch; });

  it("admin only; needs a Burrow and a commit; GitHub must have the commit", async () => {
    expect((await postJson("/api/admin/rollout", { edge: "burrow1", build: "abcdef1" }, { cookie: teacherCookie })).status).toBe(403);
    expect((await postJson("/api/admin/rollout", { edge: "nope", build: "abcdef1" }, { cookie: admin.cookie })).status).toBe(400);
    expect((await postJson("/api/admin/rollout", { edge: "burrow1", build: "0000000" }, { cookie: admin.cookie })).status).toBe(502);
  });

  it("hands the update to that Burrow in its snapshot reply, closes when it reports the build, refuses a second Burrow meanwhile", async () => {
    let r = await postJson("/api/admin/rollout", { edge: "burrow1", build: "abcdef1" }, { cookie: admin.cookie });
    expect(r.status).toBe(200);
    let j = await r.json();
    expect(j.open).toBe("burrow1");
    expect(j.rollouts[0]).toMatchObject({ edge: "burrow1", build: "abcdef1", sha256: await sha256Hex(TARBALL) });
    // burrow2 cannot start while burrow1 is updating
    r = await postJson("/api/admin/rollout", { edge: "burrow2", build: "abcdef1" }, { cookie: admin.cookie });
    expect(r.status).toBe(409);
    // burrow1's snapshot gets the instruction; burrow2's does not
    j = await snapshot("burrow1", { version: "0.1.0", build: "1111111 2026-10-31T20:00:00Z" });
    expect(j.update_to).toEqual({ build: "abcdef1", sha256: await sha256Hex(TARBALL), url: "https://example.com/v1/edge/rollout/abcdef1" });
    // the Burrow downloads it from us, with its token
    expect((await SELF.fetch("https://example.com/v1/edge/rollout/abcdef1")).status).toBe(401);
    const dl = await edgeFetch("burrow1", "/v1/edge/rollout/abcdef1");
    expect(dl.status).toBe(200);
    expect(new Uint8Array(await dl.arrayBuffer())).toEqual(TARBALL);
    expect((await edgeFetch("burrow1", "/v1/edge/rollout/1234567")).status).toBe(404);
    j = await snapshot("burrow2", { build: "1111111" });
    expect(j.update_to).toBeUndefined();
    // it reports the new build: closed, and burrow2 may go next
    j = await snapshot("burrow1", { build: "abcdef1 2026-10-31T22:00:00Z" });
    expect(j.update_to).toBeUndefined();
    j = await (await get("/api/admin/rollout", { cookie: teacherCookie })).json();
    expect(j.open).toBeNull();
    expect(j.rollouts[0].done_at).toBeGreaterThan(0);
    r = await postJson("/api/admin/rollout", { edge: "burrow2", build: "abcdef1" }, { cookie: admin.cookie });
    expect(r.status).toBe(200);
    r = await postJson("/api/admin/rollout/cancel", { edge: "burrow2" }, { cookie: admin.cookie });
    expect((await r.json()).open).toBeNull();
  });
});
