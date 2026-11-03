import { env } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { applySchema, bootstrapAdmin, cookieOf, createTeam, get, loginTeam, postJson } from "./helpers.js";

const change = (cookie, body, ip = "10.9.9.9") => postJson("/api/me/password", body, { cookie, "cf-connecting-ip": ip });

describe("changing your own password", () => {
  let adminCookie, teacher;
  beforeAll(async () => {
    await applySchema();
    adminCookie = (await bootstrapAdmin("pw-admin", "correct horse battery")).cookie;
    const r = await postJson("/api/admin/teams", { name: "Mrs. Test", role: "teacher" }, { cookie: adminCookie });
    teacher = await r.json();
  });

  it("needs a sign-in", async () => {
    const r = await postJson("/api/me/password", { old: "x", new: "yyyy" });
    expect(r.status).toBe(401);
  });

  it("a teacher changes theirs; the old one stops working; other sessions are signed out, this one stays", async () => {
    const a = cookieOf(await postJson("/api/login", { name: "Mrs. Test", passphrase: teacher.passphrase }));
    const b = cookieOf(await postJson("/api/login", { name: "Mrs. Test", passphrase: teacher.passphrase }));
    let r = await change(a, { old: "not-it", new: "worms" });
    expect(r.status).toBe(403);                                  // not 401: the page would read that as signed out
    expect((await get("/api/me", { cookie: a })).status).toBe(200);
    r = await change(a, { old: teacher.passphrase, new: "abc" });
    expect(r.status).toBe(400);                                  // too short
    r = await change(a, { old: teacher.passphrase, new: teacher.passphrase });
    expect(r.status).toBe(400);                                  // the same
    r = await change(a, { old: teacher.passphrase, new: "worms" });
    expect(r.status).toBe(200);
    expect((await get("/api/me", { cookie: a })).status).toBe(200);   // this session stays
    expect((await get("/api/me", { cookie: b })).status).toBe(401);   // the other one is gone
    expect((await postJson("/api/login", { name: "Mrs. Test", passphrase: teacher.passphrase })).status).toBe(401);
    expect((await postJson("/api/login", { name: "Mrs. Test", passphrase: "worms" })).status).toBe(200);
    const row = await env.DB.prepare("SELECT pass_hash FROM teams WHERE name = 'Mrs. Test'").first();
    expect(row.pass_hash).toMatch(/^[0-9a-f]{64}$/);              // stored hashed, never as typed
  });

  it("an admin can change theirs too", async () => {
    const r = await change(adminCookie, { old: "correct horse battery", new: "new admin pw" });
    expect(r.status).toBe(200);
    expect((await postJson("/api/login", { name: "pw-admin", passphrase: "new admin pw" })).status).toBe(200);
  });

  it("a team's shared passphrase is not changed this way", async () => {
    const admin = cookieOf(await postJson("/api/login", { name: "pw-admin", passphrase: "new admin pw" }));
    const t = await createTeam(admin, { name: "Shared Team", period: 1, bin: 9, room: 1 });
    const tc = (await loginTeam(t.team.id, t.passphrase)).cookie;
    const r = await change(tc, { old: t.passphrase, new: "mine-now" });
    expect(r.status).toBe(403);
  });
});
