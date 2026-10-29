import { createExecutionContext, env, SELF, waitOnExecutionContext } from "cloudflare:test";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import worker from "../src/index.js";
import { applySchema, bootstrapAdmin, createTeam, get, loginTeam } from "./helpers.js";

describe("page views + live proxy", () => {
  let cookie, team;
  beforeAll(async () => {
    await applySchema();
    const admin = await bootstrapAdmin();
    team = await createTeam(admin.cookie, { name: "Dirt Vader", period: 3, bin: 7, room: 1 });
    cookie = (await loginTeam(team.team.id, team.passphrase, "Ada", "198.51.100.7")).cookie;
  });
  afterEach(() => vi.unstubAllGlobals());

  // The Worker runs in this isolate, so stubbing global fetch catches its
  // outbound call to the Burrow tunnel (bindings such as SELF are unaffected).
  function stubUpstream(handler) {
    const calls = [];
    vi.stubGlobal("fetch", async (url, init) => {
      calls.push({ url: String(url), headers: new Headers(init?.headers) });
      return handler(String(url), init);
    });
    return calls;
  }

  // Drive the worker directly so waitUntil() work can be awaited.
  async function pageGet(path, headers = {}) {
    const ctx = createExecutionContext();
    const req = new Request(`https://example.com${path}`, { headers: { accept: "text/html,application/xhtml+xml", ...headers } });
    const res = await worker.fetch(req, env, ctx);
    await waitOnExecutionContext(ctx);
    return res;
  }

  it("serves the SPA to everyone, and records a visit only for a logged-in HTML GET", async () => {
    // anonymous: SPA served, no redirect, no visit
    let r = await pageGet("/");
    expect(r.status).toBe(200);
    expect(await r.text()).toContain("test SPA");
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM visits").first("n")).toBe(0);

    // SPA route (no extension) for an anonymous user still serves index.html
    r = await pageGet("/admin");
    expect(r.status).toBe(200);
    expect(await r.text()).toContain("test SPA");

    // logged in: one visits row, with the first name and a hashed IP
    r = await pageGet("/bin/aaa", { cookie, "cf-connecting-ip": "198.51.100.7" });
    expect(r.status).toBe(200);
    const v = await env.DB.prepare("SELECT * FROM visits").all();
    expect(v.results.length).toBe(1);
    expect(v.results[0]).toMatchObject({ team_id: team.team.id, first_name: "Ada", path: "/bin/aaa" });
    expect(v.results[0].ip_hash).toMatch(/^[0-9a-f]{32}$/);
    expect(v.results[0].ip_hash).not.toContain("198.51");

    // a static asset is not a page view, and neither is an API poll
    const asset = await pageGet("/app.js", { cookie, accept: "*/*" });
    expect(asset.status).toBe(200);
    await get("/api/me", { cookie });
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM visits").first("n")).toBe(1);
  });

  it("the whole route also works through the asset router (SELF)", async () => {
    const r = await SELF.fetch("https://example.com/", { headers: { accept: "text/html", cookie } });
    expect(r.status).toBe(200);
    expect(await r.text()).toContain("test SPA");
  });

  it("proxies /live/<room> from the Burrow tunnel with the shared key", async () => {
    const calls = stubUpstream(() => new Response("event: hello\ndata: {}\n\n", { headers: { "content-type": "text/event-stream" } }));
    const r = await get("/live/1", { cookie });
    expect(r.status).toBe(200);
    expect(r.headers.get("content-type")).toContain("text/event-stream");
    expect(r.headers.get("cache-control")).toBe("no-store");
    expect(await r.text()).toBe("event: hello\ndata: {}\n\n");
    expect(calls.length).toBe(1);
    expect(calls[0].url).toBe("https://burrow1.whs.makerlabkids.com/live");
    expect(calls[0].headers.get("x-burrow-key")).toBe("local-live-key");
  });

  it("returns 503 edge offline when the tunnel fails, 401 without a cookie, 404 for a bad room", async () => {
    stubUpstream(() => new Response("bad gateway", { status: 502 }));
    let r = await get("/live/2", { cookie });
    expect(r.status).toBe(503);
    expect(await r.json()).toEqual({ ok: false, error: "edge offline" });

    const calls = stubUpstream(() => { throw new TypeError("connect refused"); });
    r = await get("/live/3", { cookie });
    expect(r.status).toBe(503);
    expect(calls[0].url).toBe("https://burrow3.whs.makerlabkids.com/live");

    // No cookie: refused before any upstream call is made.
    const anon = stubUpstream(() => new Response("x"));
    expect((await get("/live/1")).status).toBe(401);
    expect((await get("/live/4", { cookie })).status).toBe(404);
    expect(anon.length).toBe(0);

    // Room 0 is the Portal's own Burrow (burrow0): a real room for the live path.
    const r0 = stubUpstream(() => new Response("event: hello\ndata: {}\n\n", { headers: { "content-type": "text/event-stream" } }));
    expect((await get("/live/0", { cookie })).status).toBe(200);
    expect(r0[0].url).toBe("https://burrow0.whs.makerlabkids.com/live");
  });
});

describe("edge passthrough (/api/edge/<room>/signal)", () => {
  it("needs a login, knows only rooms 0-3 and the three read-only paths", async () => {
    const { SELF } = await import("cloudflare:test");
    expect((await SELF.fetch("https://example.com/api/edge/1/signal")).status).toBe(401);
    expect((await SELF.fetch("https://example.com/api/edge/7/signal")).status).toBe(404);
    expect((await SELF.fetch("https://example.com/api/edge/1/ingest")).status).toBe(404);
    expect((await SELF.fetch("https://example.com/api/edge/1/signal", { method: "POST" })).status).toBe(405);
  });
});
