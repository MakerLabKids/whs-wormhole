import { beforeAll, describe, expect, it } from "vitest";
import { applySchema, edgeFetch, get } from "./helpers.js";

describe("/api/public/now", () => {
  beforeAll(async () => {
    await applySchema();
    const r = await edgeFetch("burrow1", "/v1/edge/snapshot", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ edge: "burrow1", room: 1, ts: 1700000000, clk: "ntp", bins: {
        aaa: { ts: 1700000000, clk: "ntp", team: "Worm Rangers", period: 1, bin: 2, room: 1,
          d: { in_temp_c: 22.4, in_press_hpa: 982.6, in_hum_pct: null, ip: "192.168.80.140", rssi: -39,
            parts: [{ name: "BME280 in", ok: true }, { name: "DS18B20", ok: false }] } } } }),
    });
    expect(r.status).toBe(200);
  });

  it("answers anonymously with the readings but nothing personal", async () => {
    const r = await get("/api/public/now");
    expect(r.status).toBe(200);
    expect(r.headers.get("cache-control")).toContain("max-age=60");
    const j = await r.json();
    expect(j.bins.aaa.team).toBe("Worm Rangers");
    expect(j.bins.aaa.period).toBe(1);
    expect(j.bins.aaa.d.in_temp_c).toBe(22.4);
    expect(j.bins.aaa.d.parts_ok).toBe(1);
    expect(j.bins.aaa.d.parts_total).toBe(2);
    expect(j.bins.aaa.d.ip).toBeUndefined();
    expect(j.bins.aaa.d.rssi).toBeUndefined();
    expect(j.bins.aaa.d.parts).toBeUndefined();
    expect(j.edges.burrow1.room).toBe(1);
    expect(j.edges.burrow1.status).toBeUndefined();
  });

  it("sends CORS headers only to the project's own origins", async () => {
    let r = await get("/api/public/now", { origin: "https://makerlabkids.github.io" });
    expect(r.headers.get("access-control-allow-origin")).toBe("https://makerlabkids.github.io");
    r = await get("/api/public/now", { origin: "https://evil.example" });
    expect(r.headers.get("access-control-allow-origin")).toBeNull();
    r = await get("/api/public/now", { origin: "http://localhost:8080" });
    expect(r.headers.get("access-control-allow-origin")).toBe("http://localhost:8080");
  });

  it("still keeps the full /api/now behind a login", async () => {
    expect((await get("/api/now")).status).toBe(401);
  });
});
