import { env } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { applySchema, bootstrapAdmin, createTeam, edgeFetch, get, loginTeam, postJson, sha256Hex } from "./helpers.js";
import { MAX_TOTAL, scanPbm } from "../src/shows.js";

const UID = "e66118604b7c2b2a", OTHER = "0000000000000bbb";

function pbm(w, h, frames = 1, fill = 0xff, notes = "") {
  const parts = [];
  for (let f = 0; f < frames; f++) {
    const head = new TextEncoder().encode(`P4\n${f === 0 ? notes : ""}${w} ${h}\n`);
    const body = new Uint8Array(Math.ceil(w / 8) * h).fill(fill);
    parts.push(head, body);
  }
  const out = new Uint8Array(parts.reduce((a, p) => a + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
const b64 = (u8) => btoa(String.fromCharCode(...u8));

async function snapshot(bins = {}, roster = null) {
  const body = { edge: "burrow1", room: 1, ts: Math.floor(Date.now() / 1000), clk: "ntp", bins, status: {} };
  if (roster) body.roster = roster;
  const r = await edgeFetch("burrow1", "/v1/edge/snapshot", { method: "POST", body: JSON.stringify(body) });
  expect(r.status).toBe(200);
  return r.json();
}

describe("scanPbm (the same rules as lib/pbmshow.py)", () => {
  it("reads stills and videos and refuses what the board would", () => {
    expect(scanPbm(pbm(128, 64))).toEqual({ frames: 1, w: 128, h: 64 });
    expect(scanPbm(pbm(10, 2, 3, 0, "# fps 5\n"))).toEqual({ frames: 3, w: 10, h: 2 });
    expect(() => scanPbm(new TextEncoder().encode("\x89PNG"))).toThrow(/not a show file/);
    expect(() => scanPbm(pbm(256, 64))).toThrow(/bigger than/);
    expect(() => scanPbm(pbm(128, 64).slice(0, 500))).toThrow(/cut short/);
    expect(() => scanPbm(pbm(8, 1, 101))).toThrow(/more than 100/);
    expect(() => scanPbm(new Uint8Array(0))).toThrow(/empty/);
  });
});

describe("shows from the website to a bin", () => {
  let admin, cookie;
  beforeAll(async () => {
    await applySchema();
    admin = await bootstrapAdmin();
    const made = await createTeam(admin.cookie, { name: "Dirt Vader", period: 3, bin: 7, room: 1 });
    cookie = (await loginTeam(made.team.id, made.passphrase)).cookie;
    await snapshot({}, [{ uid: UID, name: "Dirt Vader", team: "Dirt Vader", period: 3, bin: 7, room: 1 },
      { uid: OTHER, name: "Worm Riders", team: "Worm Riders", period: 2, bin: 8, room: 1 }]);
  });

  it("needs a login, and a team only changes its own bin", async () => {
    expect((await get(`/api/shows?uid=${UID}`)).status).toBe(401);
    expect((await postJson("/api/shows", { uid: OTHER, name: "x", pbm: b64(pbm(8, 8)) }, { cookie })).status).toBe(403);
    expect((await get(`/api/shows?uid=${OTHER}`, { cookie })).status).toBe(403);
    const r = await get(`/api/shows?uid=${UID}`, { cookie });
    expect(r.status).toBe(200);
    const j = await r.json();
    expect(j).toMatchObject({ files: [], list: null, rev: 0, on_board: true });
    expect(j.builtins).toContain("Worm Party");
  });

  it("uploads a show, checks it like the board would, and the snapshot reply carries it", async () => {
    const file = pbm(128, 64, 3, 0x0f, "# fps 5\n");
    let r = await postJson("/api/shows", { uid: UID, name: "wiggle", pbm: b64(file) }, { cookie });
    expect(r.status).toBe(200);
    let j = await r.json();
    expect(j).toMatchObject({ name: "wiggle", frames: 3, w: 128, h: 64, rev: 1, on_board: false });
    expect(j.sha256).toBe(await sha256Hex(file));
    expect(j.files[0]).toMatchObject({ name: "wiggle", size: file.length, set_by: "Ada (Dirt Vader)" });
    // refused: bad names, built-in names, not a PBM, too big
    for (const [body, code] of [[{ name: "Bad Name!", pbm: b64(file) }, 400], [{ name: "wormhole", pbm: b64(file) }, 400],
      [{ name: "png", pbm: btoa("\x89PNG\r\n") }, 400], [{ name: "huge", pbm: b64(pbm(256, 64)) }, 400]]) {
      r = await postJson("/api/shows", { uid: UID, ...body }, { cookie });
      expect(r.status).toBe(code);
    }
    // the Burrow's snapshot reply lists the bin, its files and rev; it fetches the file by sha256
    const snap = await snapshot();
    const mine = snap.shows.find((s) => s.uid === UID);
    expect(mine).toEqual({ uid: UID, rev: 1, list: null, files: [{ name: "wiggle", sha256: j.sha256, size: file.length }] });
    r = await edgeFetch("burrow1", `/v1/edge/shows/${j.sha256}`);
    expect(r.status).toBe(200);
    expect(new Uint8Array(await r.arrayBuffer())).toEqual(file);
    expect((await edgeFetch("burrow1", `/v1/edge/shows/${"0".repeat(64)}`)).status).toBe(404);
    expect((await get(`/v1/edge/shows/${j.sha256}`)).status).toBe(401);       // Burrows only
  });

  it("a playlist of built-in and own names; a delete drops it from the list too", async () => {
    let r = await postJson("/api/shows", { uid: UID, list: ["WIGGLE", "worm party", "nope"] }, { cookie });
    expect(r.status).toBe(400);
    r = await postJson("/api/shows", { uid: UID, list: ["WIGGLE", "worm party"] }, { cookie });
    let j = await r.json();
    expect(j).toMatchObject({ list: ["wiggle", "Worm Party"], rev: 2 });
    r = await postJson("/api/shows", { uid: UID, name: "sun", pbm: b64(pbm(16, 8)) }, { cookie });
    expect((await r.json()).list).toEqual(["wiggle", "Worm Party"]);              // a new file keeps the playlist
    r = await postJson("/api/shows", { uid: UID, delete: "wiggle" }, { cookie });
    j = await r.json();
    expect(j.files.map((f) => f.name)).toEqual(["sun"]);
    expect(j.list).toEqual(["Worm Party"]);
    expect((await postJson("/api/shows", { uid: UID, delete: "wiggle" }, { cookie })).status).toBe(404);
    r = await postJson("/api/shows", { uid: UID, list: null }, { cookie });
    expect((await r.json()).list).toBe(null);
  });

  it("the board's shows_rev in a snapshot marks it delivered, and it drops out of the reply", async () => {
    const rev = (await (await get(`/api/shows?uid=${UID}`, { cookie })).json()).rev;
    let snap = await snapshot({ [UID]: { ts: 1, d: { shows_rev: rev - 1 } } });
    expect(snap.shows.find((s) => s.uid === UID)).toBeTruthy();                  // an older rev: still pending
    snap = await snapshot({ [UID]: { ts: 1, d: { shows_rev: rev } } });
    expect(snap.shows.find((s) => s.uid === UID)).toBeUndefined();
    const j = await (await get(`/api/shows?uid=${UID}`, { cookie })).json();
    expect(j).toMatchObject({ board_rev: rev, on_board: true });
  });

  it("caps a bin's total, and teachers may change any bin", async () => {
    const big = pbm(128, 64, 100);                                               // ~103 KB
    let r;
    for (let i = 0; i < 5; i++) {                                                 // 5 x 101 KB fit in 512 KB
      r = await postJson("/api/shows", { uid: UID, name: "big" + i, pbm: b64(big) }, { cookie });
      expect(r.status).toBe(200);
    }
    r = await postJson("/api/shows", { uid: UID, name: "big5", pbm: b64(big) }, { cookie });
    expect(r.status).toBe(413);
    expect((await r.json()).error).toMatch(new RegExp(`${MAX_TOTAL / 1024} KB`));
    r = await postJson("/api/shows", { uid: OTHER, name: "hi", pbm: b64(pbm(8, 8)) }, { cookie: admin.cookie });
    expect(r.status).toBe(200);
  });
});
