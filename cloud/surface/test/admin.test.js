import { env, SELF } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { applySchema, bootstrapAdmin, createTeam, get, loginTeam, makeCasting, postJson, putCasting } from "./helpers.js";

const T0 = Date.UTC(2026, 9, 16, 14, 15) / 1000;

describe("admin api + roles", () => {
  let admin, teacherCookie, teamCookie, team;
  beforeAll(async () => {
    await applySchema();
    admin = await bootstrapAdmin();
    const t = await createTeam(admin.cookie, { name: "Mr Soil", role: "teacher", password: "teacher-pass-123" });
    expect(t.passphrase).toBeNull();
    teacherCookie = (await postJson("/api/login", { team_id: t.team.id, passphrase: "teacher-pass-123" }).then((r) => {
      expect(r.status).toBe(200); return r.headers.get("set-cookie").split(";")[0];
    }));
    team = await createTeam(admin.cookie, { name: "Dirt Vader", period: 3, bin: 7, room: 1 });
    teamCookie = (await loginTeam(team.team.id, team.passphrase)).cookie;
  });

  it("enforces roles: anonymous 401, team 403, teacher read-only, admin everything", async () => {
    expect((await get("/api/admin/edges")).status).toBe(401);
    expect((await get("/api/admin/edges", { cookie: teamCookie })).status).toBe(403);
    expect((await get("/api/admin/edges", { cookie: teacherCookie })).status).toBe(200);
    expect((await get("/api/admin/stats", { cookie: teacherCookie })).status).toBe(200);
    expect((await get("/api/admin/sessions", { cookie: teacherCookie })).status).toBe(200);
    expect((await get("/api/admin/visits", { cookie: teacherCookie })).status).toBe(200);
    // mutations and the teams/castings listings are admin only
    expect((await get("/api/admin/teams", { cookie: teacherCookie })).status).toBe(403);
    expect((await postJson("/api/admin/teams", { name: "Nope" }, { cookie: teacherCookie })).status).toBe(403);
    expect((await postJson("/api/admin/teams", { name: "Nope" }, { cookie: teamCookie })).status).toBe(403);
    expect((await get("/api/admin/castings", { cookie: teacherCookie })).status).toBe(403);
    expect((await get("/api/admin/teams", { cookie: admin.cookie })).status).toBe(200);
    // unknown admin paths are hidden from anonymous callers
    expect((await get("/api/admin/whatever")).status).toBe(401);
    expect((await get("/api/admin/whatever", { cookie: admin.cookie })).status).toBe(404);
  });

  it("lists teams without secrets, resets passphrases, deletes", async () => {
    let r = await get("/api/admin/teams", { cookie: admin.cookie });
    const { teams } = await r.json();
    expect(teams.length).toBe(3);
    for (const t of teams) { expect(t.pass_hash).toBeUndefined(); expect(t.pass_salt).toBeUndefined(); }

    r = await postJson(`/api/admin/teams/${team.team.id}/reset`, {}, { cookie: admin.cookie });
    expect(r.status).toBe(200);
    const reset = await r.json();
    expect(reset.passphrase).toMatch(/^[a-z]+-[a-z]+-[a-z]+$/);
    expect(reset.passphrase).not.toBe(team.passphrase);
    // old passphrase dead, old sessions dropped, new one works
    expect((await loginTeam(team.team.id, team.passphrase)).res.status).toBe(401);
    expect((await get("/api/me", { cookie: teamCookie })).status).toBe(401);
    const fresh = await loginTeam(team.team.id, reset.passphrase);
    expect(fresh.res.status).toBe(200);
    teamCookie = fresh.cookie;

    // duplicate names are a 409
    expect((await postJson("/api/admin/teams", { name: "Dirt Vader" }, { cookie: admin.cookie })).status).toBe(409);
    // cannot delete yourself; can delete others
    expect((await SELF.fetch(`https://example.com/api/admin/teams/${admin.team.id}`, { method: "DELETE", headers: { cookie: admin.cookie } })).status).toBe(400);
    const extra = await createTeam(admin.cookie, { name: "Temp", period: 1, bin: 1, room: 1 });
    r = await SELF.fetch(`https://example.com/api/admin/teams/${extra.team.id}`, { method: "DELETE", headers: { cookie: admin.cookie } });
    expect(r.status).toBe(200);
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM teams WHERE name='Temp'").first("n")).toBe(0);
  });

  it("imports a CSV and returns the passphrases once", async () => {
    const csv = "team,period,bin,room\nCompost Kings,1,1,1\nWorm Riders,2,3,2\nDirt Vader,3,7,1\n";
    const r = await SELF.fetch("https://example.com/api/admin/teams/import", { method: "POST", body: csv, headers: { cookie: admin.cookie, "content-type": "text/csv" } });
    expect(r.status).toBe(200);
    const out = await r.json();
    expect(out.length).toBe(3);
    expect(out[0]).toMatchObject({ name: "Compost Kings", period: 1, bin: 1, room: 1 });
    expect(out[0].passphrase).toMatch(/^[a-z]+-[a-z]+-[a-z]+$/);
    expect(out[1].name).toBe("Worm Riders");
    expect(out[2]).toMatchObject({ name: "Dirt Vader", passphrase: null, error: "exists" });
    // the passphrase logs in
    const ids = await env.DB.prepare("SELECT id FROM teams WHERE name='Worm Riders'").first("id");
    expect((await loginTeam(ids, out[1].passphrase, "Sam")).res.status).toBe(200);
    // and the public list now has them all
    expect((await (await get("/api/teams")).json()).map((t) => t.name)).toEqual(["Compost Kings", "Worm Riders", "Dirt Vader"]);
  });

  it("stats, edges, sessions, visits, castings list + download", async () => {
    const id = "r1-20261016T1415";
    const { gz, meta } = await makeCasting(id, T0);
    expect((await putCasting("burrow1", id, gz, meta)).status).toBe(200);
    await SELF.fetch("https://example.com/v1/edge/snapshot", { method: "POST", headers: { authorization: "Bearer tok1", "content-type": "application/json" },
      body: JSON.stringify({ edge: "burrow1", room: 1, ts: T0, clk: "ntp", bins: {}, status: { version: "0.1" } }) });

    let r = await get("/api/admin/stats", { cookie: admin.cookie });
    let j = await r.json();
    expect(j.ok).toBe(true);
    expect(j.counts).toMatchObject({ edges: 1, castings: 1, rollups: 0 });
    expect(j.counts.teams).toBeGreaterThanOrEqual(3);
    expect(j.r2_objects_estimate).toBe(1);
    expect(j.today.castings).toBe(1);

    r = await get("/api/admin/edges", { cookie: admin.cookie });
    j = await r.json();
    expect(j.edges[0]).toMatchObject({ edge: "burrow1", room: 1, ts: T0, clk: "ntp", version: "0.1" });
    expect(j.edges[0].last_seen).toBeGreaterThan(0);

    r = await get("/api/admin/sessions", { cookie: admin.cookie });
    j = await r.json();
    expect(j.sessions.some((s) => s.team === "Dirt Vader" && s.first_name === "Ada")).toBe(true);

    r = await get("/api/admin/visits?since=0", { cookie: admin.cookie });
    j = await r.json();
    expect(j.ok).toBe(true);
    expect(Array.isArray(j.visits)).toBe(true);
    expect(Array.isArray(j.teams)).toBe(true);

    r = await get("/api/admin/castings?room=1&day=2026-10-16", { cookie: admin.cookie });
    j = await r.json();
    expect(j.castings.length).toBe(1);
    expect(j.castings[0].id).toBe(id);
    r = await get("/api/admin/castings?room=2", { cookie: admin.cookie });
    expect((await r.json()).castings.length).toBe(0);
    r = await get("/api/admin/castings?day=2026-10-17", { cookie: admin.cookie });
    expect((await r.json()).castings.length).toBe(0);

    r = await get(`/api/admin/castings/${id}`, { cookie: admin.cookie });
    expect(r.status).toBe(200);
    expect(r.headers.get("content-type")).toBe("application/gzip");
    expect(r.headers.get("content-disposition")).toBe(`attachment; filename="${id}.jsonl.gz"`);
    const got = new Uint8Array(await r.arrayBuffer());
    expect(got).toEqual(gz);
    expect((await get(`/api/admin/castings/${id}`, { cookie: teacherCookie })).status).toBe(403);
    expect((await get(`/api/admin/castings/r9-19700101T0000`, { cookie: admin.cookie })).status).toBe(404);
  });
});
