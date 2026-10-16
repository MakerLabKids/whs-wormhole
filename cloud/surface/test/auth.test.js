import { env } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { applySchema, bootstrapAdmin, cookieOf, createTeam, get, loginTeam, postJson } from "./helpers.js";

describe("bootstrap + login flow", () => {
  beforeAll(applySchema);

  it("bootstrap needs the one-time secret and works only once", async () => {
    let r = await postJson("/api/admin/bootstrap", { name: "x", password: "longenough1", bootstrap: "wrong" });
    expect(r.status).toBe(403);
    r = await postJson("/api/admin/bootstrap", { name: "x", password: "short", bootstrap: env.ADMIN_BOOTSTRAP });
    expect(r.status).toBe(400);
    r = await postJson("/api/admin/bootstrap", { name: "ms-teacher", password: "correct horse battery", bootstrap: env.ADMIN_BOOTSTRAP });
    expect(r.status).toBe(200);
    const j = await r.json();
    expect(j.team.role).toBe("admin");
    r = await postJson("/api/admin/bootstrap", { name: "again", password: "longenough1", bootstrap: env.ADMIN_BOOTSTRAP });
    expect(r.status).toBe(403);
    // Only hash + salt are stored, never the password.
    const row = await env.DB.prepare("SELECT pass_hash, pass_salt FROM teams WHERE name = 'ms-teacher'").first();
    expect(row.pass_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(row.pass_salt).toMatch(/^[0-9a-f]{32}$/);
  });

  it("creates a team, lists it publicly, logs in with the passphrase, /api/me, logout", async () => {
    const login = await postJson("/api/login", { name: "ms-teacher", passphrase: "correct horse battery" });
    expect(login.status).toBe(200);
    const adminCookie = cookieOf(login);
    const sc = login.headers.get("set-cookie");
    expect(sc).toMatch(/^wh_session=[0-9a-f]{64}\.[A-Za-z0-9_-]{43}; Path=\/; HttpOnly; Secure; SameSite=Lax; Max-Age=15552000$/);

    const created = await createTeam(adminCookie, { name: "Dirt Vader", period: 3, bin: 7, room: 1 });
    expect(created.passphrase).toMatch(/^[a-z]+-[a-z]+-[a-z]+$/);
    expect(created.team).toMatchObject({ name: "Dirt Vader", period: 3, bin: 7, room: 1, role: "team" });

    // Public dropdown lists teams only (not the admin), and needs no cookie.
    let r = await get("/api/teams");
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual([{ id: created.team.id, name: "Dirt Vader", period: 3 }]);

    // Wrong passphrase, bad first name, then success.
    r = (await loginTeam(created.team.id, "wiggle-wrong-words")).res;
    expect(r.status).toBe(401);
    r = (await loginTeam(created.team.id, created.passphrase, "R2D2!")).res;
    expect(r.status).toBe(400);
    r = (await loginTeam(created.team.id, created.passphrase, "")).res;
    expect(r.status).toBe(400);
    // Sloppy typing is fine: capitals and spaces instead of hyphens.
    const sloppy = created.passphrase.toUpperCase().replace(/-/g, " ");
    const ok = await loginTeam(created.team.id, ` ${sloppy} `, "  Mary-Jo O'Neil ");
    expect(ok.res.status).toBe(200);
    const body = await ok.res.json();
    expect(body).toEqual({ ok: true, me: { role: "team", first_name: "Mary-Jo O'Neil",
      team: { id: created.team.id, name: "Dirt Vader", period: 3, bin: 7, room: 1, role: "team" } } });

    r = await get("/api/me", { cookie: ok.cookie });
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual({ ok: true, role: "team", first_name: "Mary-Jo O'Neil",
      team: { id: created.team.id, name: "Dirt Vader", period: 3, bin: 7, room: 1, role: "team" } });

    // Sessions are stored hashed; the cookie value itself never appears in D1.
    const sid = ok.cookie.split("=")[1].split(".")[0];
    const sess = await env.DB.prepare("SELECT token_hash, first_name FROM sessions").all();
    expect(sess.results.length).toBe(2);
    expect(sess.results.some((s) => s.token_hash === sid)).toBe(false);

    // A forged signature is rejected.
    r = await get("/api/me", { cookie: `wh_session=${sid}.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA` });
    expect(r.status).toBe(401);
    expect(await r.json()).toEqual({ ok: false });

    r = await postJson("/api/logout", {}, { cookie: ok.cookie });
    expect(r.status).toBe(200);
    expect(r.headers.get("set-cookie")).toMatch(/^wh_session=; .*Max-Age=0$/);
    r = await get("/api/me", { cookie: ok.cookie });
    expect(r.status).toBe(401);
    expect(await r.json()).toEqual({ ok: false });
  });

  it("rate-limits logins per IP: 10 per 10 minutes", async () => {
    const admin = await bootstrapAdmin();
    const { team } = await createTeam(admin.cookie, { name: "Worm Riders", period: 2, bin: 3, room: 2 });
    for (let i = 0; i < 10; i++) {
      const { res } = await loginTeam(team.id, "bad-bad-bad", "Ada", "203.0.113.9");
      expect(res.status).toBe(401);
    }
    const { res } = await loginTeam(team.id, "bad-bad-bad", "Ada", "203.0.113.9");
    expect(res.status).toBe(429);
    // A different IP is unaffected.
    expect((await loginTeam(team.id, "bad-bad-bad", "Ada", "203.0.113.10")).res.status).toBe(401);
  });
});
