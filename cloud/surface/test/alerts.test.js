import { env } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { applySchema, bootstrapAdmin, edgeFetch, get, postJson } from "./helpers.js";
import { SILENT_S, watchEdges } from "../src/alerts.js";

const T = Math.floor(Date.now() / 1000);

describe("events from Burrows", () => {
  beforeAll(applySchema);

  it("stores a batch and rejects bad ones", async () => {
    let r = await edgeFetch("burrow1", "/v1/edge/events", { method: "POST", body: JSON.stringify({ edge: "burrow1", events: [
      { ts: T - 5, kind: "bin.quiet", level: "warn", text: "Dirt Vader (bin 7) silent for 10 min", data: { uid: "abc" } },
      { ts: T - 1, kind: "burrow.start", level: "info", text: "burrow1 v0.1.0 started" },
    ] }) });
    expect(r.status).toBe(200);
    expect(await r.json()).toEqual({ ok: true, n: 2, notified: 0 });
    const rows = (await env.DB.prepare("SELECT edge, kind, level, text, data FROM events ORDER BY id").all()).results;
    expect(rows.length).toBe(2);
    expect(rows[0]).toMatchObject({ edge: "burrow1", kind: "bin.quiet", level: "warn" });
    expect(JSON.parse(rows[0].data)).toEqual({ uid: "abc" });
    r = await edgeFetch("burrow2", "/v1/edge/events", { method: "POST", body: JSON.stringify({ edge: "burrow1", events: [] }) });
    expect(r.status).toBe(403);
    r = await edgeFetch("burrow1", "/v1/edge/events", { method: "POST", body: JSON.stringify({ edge: "burrow1", events: [{ kind: "x" }] }) });
    expect(r.status).toBe(400);
  });

  it("an alert-level event opens an alert row (unnotified without ALERT_URL) and a .back closes it", async () => {
    let r = await edgeFetch("burrow1", "/v1/edge/events", { method: "POST", body: JSON.stringify({ edge: "burrow1", events: [
      { ts: T, kind: "opal", level: "alert", text: "down 15 min: rebooted the Opal (#1)" }] }) });
    expect((await r.json()).ok).toBe(true);
    let open = (await env.DB.prepare("SELECT key, edge, text, closed_at, notify_error FROM alerts WHERE closed_at IS NULL").all()).results;
    expect(open.length).toBe(1);
    expect(open[0]).toMatchObject({ key: "event:burrow1:opal", edge: "burrow1", notify_error: "no ALERT_URL" });
    // same alert again within 15 min: no second row
    await edgeFetch("burrow1", "/v1/edge/events", { method: "POST", body: JSON.stringify({ edge: "burrow1", events: [
      { ts: T + 60, kind: "opal", level: "alert", text: "down 16 min: rebooted the Opal (#2)" }] }) });
    expect((await env.DB.prepare("SELECT COUNT(*) n FROM alerts").first("n"))).toBe(1);
  });

  it("admin can list events and alerts; teams cannot", async () => {
    const admin = (await bootstrapAdmin()).cookie;
    let r = await get("/api/admin/events?edge=burrow1", { cookie: admin });
    expect(r.status).toBe(200);
    const j = await r.json();
    expect(j.events.length).toBeGreaterThanOrEqual(3);
    expect(j.events[0].data === null || typeof j.events[0].data === "object").toBe(true);
    r = await get("/api/admin/alerts", { cookie: admin });
    const a = await r.json();
    expect(a.notifier).toBe("not configured");
    expect(a.open.length).toBe(1);
    r = await get("/api/admin/alerts");
    expect(r.status).toBe(401);
  });
});

describe("a neighbour reports a dead Burrow", () => {
  beforeAll(applySchema);

  it("opens one alert per dead Burrow however many neighbours report it, and closes on peer.back", async () => {
    for (const who of ["burrow1", "burrow3"]) {
      const r = await edgeFetch(who, "/v1/edge/events", { method: "POST", body: JSON.stringify({ edge: who, events: [
        { ts: T, kind: "peer.down", level: "alert", text: "burrow2 unreachable for 30 s (timed out)", data: { peer: "burrow2" } }] }) });
      expect((await r.json()).ok).toBe(true);
    }
    const open = (await env.DB.prepare("SELECT key, edge FROM alerts WHERE closed_at IS NULL AND key LIKE 'edge:%'").all()).results;
    expect(open).toEqual([{ key: "edge:burrow2", edge: "burrow2" }]);
    await edgeFetch("burrow3", "/v1/edge/events", { method: "POST", body: JSON.stringify({ edge: "burrow3", events: [
      { ts: T + 90, kind: "peer.back", level: "info", text: "burrow2 reachable again after 1 min", data: { peer: "burrow2" } }] }) });
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM alerts WHERE closed_at IS NULL AND key = 'edge:burrow2'").first("n")).toBe(0);
  });

  it("a bare host in ALERT_URL gets https:// in front", async () => {
    const { alertUrl } = await import("../src/alerts.js");
    expect(alertUrl({ ALERT_URL: "ntfy.sh/wormhole-quincy" })).toBe("https://ntfy.sh/wormhole-quincy");
    expect(alertUrl({ ALERT_URL: " https://ntfy.sh/x " })).toBe("https://ntfy.sh/x");
    expect(alertUrl({ ALERT_URL: "wormhole-quincy" })).toBe("https://ntfy.sh/wormhole-quincy");   // a bare topic (what was in the secret tonight)
    expect(alertUrl({})).toBe(null);
  });
});

describe("silent Burrow watch (the cron)", () => {
  beforeAll(async () => { await applySchema(); await env.DB.prepare("UPDATE alerts SET closed_at = 1 WHERE closed_at IS NULL").run(); });

  it("opens an alert for a silent edge and closes it when it reports again", async () => {
    await env.DB.prepare("INSERT OR REPLACE INTO edges (edge_id, room, ts, clk, snapshot, status, updated_at) VALUES ('burrow2', 2, ?1, 'ntp', '{}', '{}', ?1)").bind(T - SILENT_S - 120).run();
    await env.DB.prepare("INSERT OR REPLACE INTO edges (edge_id, room, ts, clk, snapshot, status, updated_at) VALUES ('burrow3', 3, ?1, 'ntp', '{}', '{}', ?1)").bind(T - 30).run();
    const fine = async () => ({ ok: true, status: 200 });
    let out = await watchEdges(env, T, fine);
    expect(out.silent).toEqual(["burrow2"]);
    expect(out.opened).toEqual(["burrow2"]);
    out = await watchEdges(env, T + 60, fine);           // still silent: no second alert row
    expect(out.opened).toEqual([]);
    expect((await env.DB.prepare("SELECT COUNT(*) n FROM alerts WHERE key = 'edge:burrow2' AND closed_at IS NULL").first("n"))).toBe(1);
    await env.DB.prepare("UPDATE edges SET updated_at = ?1 WHERE edge_id = 'burrow2'").bind(T + 600).run();
    out = await watchEdges(env, T + 610, fine);
    expect(out.closed[0].edge).toBe("burrow2");
    expect(out.closed[0].minutes).toBeGreaterThanOrEqual(9);
    const row = await env.DB.prepare("SELECT closed_at FROM alerts WHERE key = 'edge:burrow2' ORDER BY id DESC").first();
    expect(row.closed_at).toBeTruthy();
  });

  it("a live Burrow whose tunnel answers 530 gets its own alert, closed when the tunnel is back", async () => {
    await env.DB.prepare("UPDATE edges SET updated_at = ?1 WHERE edge_id = 'burrow3'").bind(T + 600).run();   // alive: worth a probe
    const dead = async (env, id) => (id === "burrow3" ? { ok: false, status: 530 } : { ok: true, status: 200 });
    let out = await watchEdges(env, T + 620, dead);
    expect(out.tunnel_down).toEqual(["burrow3"]);
    expect(out.opened).toContain("burrow3:tunnel");
    const open = await env.DB.prepare("SELECT text FROM alerts WHERE key = 'tunnel:burrow3' AND closed_at IS NULL").first();
    expect(open.text).toContain("530");
    out = await watchEdges(env, T + 700, async () => ({ ok: true, status: 200 }));
    expect(out.closed.map((c) => c.edge)).toContain("burrow3:tunnel");
  });
});

describe("test alert from the Devices page", () => {
  beforeAll(applySchema);

  it("notify() reports the notifier's answer, and the target is shown masked", async () => {
    const { notify, describeTarget } = await import("../src/alerts.js");
    const real = globalThis.fetch;
    globalThis.fetch = async () => new Response('{"code":40301,"http":403,"error":"forbidden"}', { status: 403 });
    try {
      expect(await notify({ ALERT_URL: "https://ntfy.sh/wormhole-quincy" }, "t", "x"))
        .toEqual({ ok: false, error: 'HTTP 403 {"code":40301,"http":403,"error":"forbidden"}' });
    } finally {
      globalThis.fetch = real;
    }
    // ALERT_TOKEN rides along as a Bearer header; a 5xx is retried once, a 4xx is not
    const calls = [];
    let status = 503;
    globalThis.fetch = async (url, init) => { calls.push({ url, auth: init.headers.Authorization }); return new Response("bad gateway", { status: status++ }); };
    try {
      expect(await notify({ ALERT_URL: "ntfy.sh/t", ALERT_TOKEN: "tk_abc" }, "t", "x", "high", "warning", async () => {}))
        .toEqual({ ok: false, error: "HTTP 504 bad gateway" });
      expect(calls).toEqual([{ url: "https://ntfy.sh/t", auth: "Bearer tk_abc" }, { url: "https://ntfy.sh/t", auth: "Bearer tk_abc" }]);
      calls.length = 0; status = 429;
      await notify({ ALERT_URL: "https://me:pw@ntfy.sh/t" }, "t", "x", "high", "warning", async () => {});
      expect(calls).toEqual([{ url: "https://ntfy.sh/t", auth: "Basic " + btoa("me:pw") }]);
    } finally {
      globalThis.fetch = real;
    }
    // Discord webhooks and Telegram bots get JSON bodies
    const { buildRequest, notifierKind } = await import("../src/alerts.js");
    const d = buildRequest("https://discord.com/api/webhooks/1/abc", {}, "burrow2 down", "burrow2 is not answering");
    expect(d.url).toBe("https://discord.com/api/webhooks/1/abc");
    expect(JSON.parse(d.body)).toEqual({ content: "**burrow2 down**\nburrow2 is not answering" });
    const tg = buildRequest("https://api.telegram.org/botTOK/sendMessage?chat_id=42", {}, "t", "x");
    expect(tg.url).toBe("https://api.telegram.org/botTOK/sendMessage");
    expect(JSON.parse(tg.body)).toEqual({ chat_id: "42", text: "t\nx" });
    expect(notifierKind("https://ntfy.sh/x")).toBe("ntfy");
    expect(describeTarget({ ALERT_URL: "https://discord.com/api/webhooks/1/abc" })).toBe("Discord webhook (38 chars)");
    expect(describeTarget({ ALERT_URL: "https://api.telegram.org/botTOK/sendMessage?chat_id=42" })).toBe("Telegram bot, chat 42");
    const { fingerprint, ntfyAccount } = await import("../src/alerts.js");
    expect(fingerprint("tk_abcdefghijklmnopqrstuvwxyz")).toBe("tk_a…xyz (29 chars)");
    expect(fingerprint(" short ")).toBe("… (5 chars)");
    expect(fingerprint("")).toBe(null);
    const seen = [];
    const fake = async (u, init) => { seen.push([u, init.headers.Authorization]); return new Response(JSON.stringify({ username: "quincy", role: "user", tier: { code: "free", name: "Free" }, stats: { messages: 3, messages_remaining: 247 }, limits: { messages: 250 } }), { status: 200 }); };
    expect(await ntfyAccount({ ALERT_URL: "ntfy.sh/wormhole-quincy", ALERT_TOKEN: "tk_1" }, fake))
      .toEqual({ status: 200, username: "quincy", role: "user", tier: "Free", messages: 3, messages_remaining: 247, messages_limit: 250 });
    expect(seen).toEqual([["https://ntfy.sh/v1/account", "Bearer tk_1"]]);
    expect(await ntfyAccount({ ALERT_URL: "ntfy.sh/x", ALERT_TOKEN: "bad" }, async () => new Response("unauthorized", { status: 401 }))).toEqual({ status: 401, error: "unauthorized" });
    expect(await ntfyAccount({ ALERT_URL: "https://discord.com/api/webhooks/1/a", ALERT_TOKEN: "x" }, fake)).toBe(null);
    expect(describeTarget({ ALERT_URL: "ntfy.sh/wormhole-quincy" })).toBe("https://ntfy.sh/w…ncy (15 chars)");
    expect(describeTarget({ ALERT_URL: "https://ntfy.sh/abc" })).toBe("https://ntfy.sh/… (3 chars)");
    expect(describeTarget({})).toBe(null);
  });

  it("POST /api/admin/alerts/test needs an admin and says what happened", async () => {
    const { cookie } = await bootstrapAdmin();
    let r = await postJson("/api/admin/alerts/test", {});
    expect([401, 403]).toContain(r.status);
    r = await postJson("/api/admin/alerts/test", {}, { cookie });
    expect(r.status).toBe(200);
    expect(await r.json()).toMatchObject({ ok: false, error: "no ALERT_URL", target: null, auth: "none", stored: { url: "", token: null, account: null } });
  });
});
