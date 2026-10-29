import { env } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { applySchema, bootstrapAdmin, edgeFetch, get } from "./helpers.js";
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
    expect(await env.DB.prepare("SELECT COUNT(*) n FROM alerts WHERE closed_at IS NULL").first("n")).toBe(0);
  });

  it("a bare host in ALERT_URL gets https:// in front", async () => {
    const { alertUrl } = await import("../src/alerts.js");
    expect(alertUrl({ ALERT_URL: "ntfy.sh/wormhole-quincy" })).toBe("https://ntfy.sh/wormhole-quincy");
    expect(alertUrl({ ALERT_URL: " https://ntfy.sh/x " })).toBe("https://ntfy.sh/x");
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
    expect((await env.DB.prepare("SELECT COUNT(*) n FROM alerts WHERE key = 'edge:burrow2'").first("n"))).toBe(1);
    await env.DB.prepare("UPDATE edges SET updated_at = ?1 WHERE edge_id = 'burrow2'").bind(T + 600).run();
    out = await watchEdges(env, T + 610, fine);
    expect(out.closed[0].edge).toBe("burrow2");
    expect(out.closed[0].minutes).toBeGreaterThanOrEqual(9);
    const row = await env.DB.prepare("SELECT closed_at FROM alerts WHERE key = 'edge:burrow2'").first();
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
