import { env, SELF } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { applySchema, bootstrapAdmin, createTeam, edgeFetch, get, loginTeam, postJson, sha256Hex } from "./helpers.js";
import { codePathOk } from "../src/picocode.js";

const COMMIT = "abc1234def5678";
const PKG = { urls: [["fs:main.py", "github:MakerLabKids/whs-wormhole/projects/worm-bin/main.py"],
  ["fs:lib/picolab.py", "github:MakerLabKids/whs-wormhole/lib/picolab.py"],
  ["fs:boot.py", "github:MakerLabKids/whs-wormhole/projects/worm-bin/boot.py"],
  ["fs:index.html", "github:MakerLabKids/whs-wormhole/projects/worm-bin/index.html"]] };
const SRC = { "projects/worm-bin/main.py": "# main v2\n", "lib/picolab.py": "VERSION = '2'\n",
  "projects/worm-bin/boot.py": "# boot\n", "projects/worm-bin/index.html": "<h1>v2</h1>" };

function withGitHub(fn) {
  const real = globalThis.fetch, seen = [];
  globalThis.fetch = async (url, init) => {
    const u = String(url);
    const m = u.match(/^https:\/\/raw\.githubusercontent\.com\/MakerLabKids\/whs-wormhole\/([0-9a-f]+)\/(.+)$/);
    if (!m) return real(url, init);
    seen.push(m[2]);
    if (m[2] === "projects/worm-bin/package.json") return new Response(JSON.stringify(PKG));
    return SRC[m[2]] != null ? new Response(SRC[m[2]]) : new Response("nf", { status: 404 });
  };
  return fn(seen).finally(() => { globalThis.fetch = real; });
}

const snapshot = async (bins) => {
  const r = await edgeFetch("burrow1", "/v1/edge/snapshot", { method: "POST", body: JSON.stringify({ edge: "burrow1", room: 1, ts: Math.floor(Date.now() / 1000), clk: "ntp", bins, status: {} }) });
  expect(r.status).toBe(200);
  return r.json();
};

describe("Pico code over Wi-Fi: releases and targets", () => {
  let admin, team;
  beforeAll(async () => {
    await applySchema();
    admin = await bootstrapAdmin();
    const made = await createTeam(admin.cookie, { name: "Dirt Vader", period: 3, bin: 7, room: 1 });
    team = (await loginTeam(made.team.id, made.passphrase)).cookie;
  });

  it("the same path rule as the board", () => {
    for (const p of ["main.py", "index.html", "cal.js", "msg.js", "toc.txt", "lib/picolab.py"]) expect(codePathOk(p)).toBe(true);
    for (const p of ["boot.py", "bin.json", "wifi.json", "shows/x.pbm", "lib/../x.py", "/main.py", "lib/a/b.py"]) expect(codePathOk(p)).toBe(false);
  });

  it("a release keeps the commit's code files (never boot.py), admins only", async () => {
    expect((await postJson("/api/admin/pico/release", { commit: COMMIT }, { cookie: team })).status).toBe(403);
    const j = await withGitHub(async (seen) => {
      const r = await postJson("/api/admin/pico/release", { commit: COMMIT }, { cookie: admin.cookie });
      expect(r.status).toBe(200);
      expect(seen).not.toContain("projects/worm-bin/boot.py");
      return r.json();
    });
    expect(j.version).toBe("abc1234");
    expect(j.files.map((f) => f.path)).toEqual(["main.py", "lib/picolab.py", "index.html"]);
    expect(j.files[0].sha256).toBe(await sha256Hex(new TextEncoder().encode("# main v2\n")));
    const r = await edgeFetch("burrow1", `/v1/edge/code/${j.files[1].sha256}`);
    expect(await r.text()).toBe("VERSION = '2'\n");
    expect((await get(`/v1/edge/code/${j.files[1].sha256}`)).status).toBe(401);
  });

  it("nothing is offered until a target is set; one bin, then every bin", async () => {
    const bins = { aaaa0000aaaa0001: { ts: 1, name: "A", d: { code: "old1111" } }, bbbb0000bbbb0002: { ts: 1, name: "B", d: { code: "old1111" } } };
    expect((await snapshot(bins)).code).toEqual([]);
    expect((await postJson("/api/admin/pico/target", { uid: "aaaa0000aaaa0001", version: "nope000" }, { cookie: admin.cookie })).status).toBe(404);
    let r = await postJson("/api/admin/pico/target", { uid: "aaaa0000aaaa0001", version: "abc1234" }, { cookie: admin.cookie });
    expect(r.status).toBe(200);
    let snap = await snapshot(bins);
    expect(snap.code.map((c) => c.uid)).toEqual(["aaaa0000aaaa0001"]);
    expect(snap.code[0].version).toBe("abc1234");
    expect(snap.code[0].files.map((f) => f.path)).toEqual(["main.py", "lib/picolab.py", "index.html"]);
    await postJson("/api/admin/pico/target", { uid: "*", version: "abc1234" }, { cookie: admin.cookie });
    snap = await snapshot(bins);
    expect(snap.code.map((c) => c.uid).sort()).toEqual(["aaaa0000aaaa0001", "bbbb0000bbbb0002"]);
  });

  it("a bin running it, or one where it failed, is not offered it again; status shows each bin", async () => {
    const snap = await snapshot({ aaaa0000aaaa0001: { ts: 2, name: "A", d: { code: "abc1234" } },
      bbbb0000bbbb0002: { ts: 2, name: "B", d: { code: "old1111", code_error: "abc1234: did not confirm in 2 starts" } } });
    expect(snap.code).toEqual([]);
    const st = await (await get("/api/admin/pico", { cookie: admin.cookie })).json();
    expect(st.releases[0]).toMatchObject({ version: "abc1234", files: 3 });
    expect(st.targets.map((t) => t.uid).sort()).toEqual(["*", "aaaa0000aaaa0001"]);
    const b = Object.fromEntries(st.bins.map((x) => [x.uid, x]));
    expect(b.aaaa0000aaaa0001.code).toBe("abc1234");
    expect(b.bbbb0000bbbb0002.error).toMatch(/did not confirm/);
    const r = await postJson("/api/admin/pico/target", { uid: "*", version: null }, { cookie: admin.cookie });
    expect((await r.json()).targets.map((t) => t.uid)).toEqual(["aaaa0000aaaa0001"]);
  });
});
