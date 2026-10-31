import { env, SELF } from "cloudflare:test";
import { beforeAll, describe, expect, it } from "vitest";
import { applySchema, bootstrapAdmin, createTeam, edgeFetch, get, loginTeam, postJson } from "./helpers.js";

const UID = "e66118604b7c2b2a", OTHER = "0000000000000bbb";

async function snapshot(bins = {}, roster = null) {
  const body = { edge: "burrow1", room: 1, ts: Math.floor(Date.now() / 1000), clk: "ntp", bins, status: {} };
  if (roster) body.roster = roster;
  const r = await edgeFetch("burrow1", "/v1/edge/snapshot", { method: "POST", body: JSON.stringify(body) });
  expect(r.status).toBe(200);
  return r.json();
}

describe("messages for a bin's screen", () => {
  let admin, team, cookie;
  beforeAll(async () => {
    await applySchema();
    admin = await bootstrapAdmin();
    const made = await createTeam(admin.cookie, { name: "Dirt Vader", period: 3, bin: 7, room: 1 });
    team = made.team;
    cookie = (await loginTeam(team.id, made.passphrase)).cookie;
    await snapshot({}, [{ uid: UID, name: "Dirt Vader", team: "Dirt Vader", period: 3, bin: 7, room: 1 },
      { uid: OTHER, name: "Worm Riders", team: "Worm Riders", period: 2, bin: 8, room: 1 }]);
  });

  it("needs a login", async () => {
    expect((await get(`/api/messages?uid=${UID}`)).status).toBe(401);
    expect((await postJson("/api/messages", { uid: UID, slot: 1, title: "x", pin: "1" })).status).toBe(401);
  });

  it("a team fills its own slots 1-3, with the board's PIN", async () => {
    let r = await postJson("/api/messages", { uid: UID, slot: 1, title: "Go Worms!", lines: ["feed us", "", "please", ""], pin: "1612", count: 3 }, { cookie });
    expect(r.status).toBe(200);
    let j = await r.json();
    expect(j.slots[0]).toEqual({ title: "Go Worms!", lines: ["feed us", "", "please"], start: null, end: null, count: 3, boot: false });
    expect(j.status[1]).toMatchObject({ seq: 1, pending: true, result: null, set_by: "Ada (Dirt Vader)" });
    r = await postJson("/api/messages", { uid: UID, slot: 1, title: "x" }, { cookie });
    expect(r.status).toBe(400);
    expect((await r.json()).error).toMatch(/PIN/);
    r = await postJson("/api/messages", { uid: UID, slot: 2, title: "", lines: [""], pin: "1612" }, { cookie });
    expect(r.status).toBe(400);
    r = await postJson("/api/messages", { uid: UID, slot: 4, title: "nope", pin: "1612" }, { cookie });
    expect(r.status).toBe(403);
    r = await postJson("/api/messages", { uid: OTHER, slot: 1, title: "not mine", pin: "1612" }, { cookie });
    expect(r.status).toBe(403);
    r = await postJson("/api/messages", { uid: "nobody", slot: 1, title: "?", pin: "1612" }, { cookie });
    expect(r.status).toBe(404);
    r = await get(`/api/messages?uid=${OTHER}`, { cookie });
    expect(r.status).toBe(403);
  });

  it("a teacher or admin fills any slot of any bin, and the teacher's slots can be power-on ones", async () => {
    const r = await postJson("/api/messages", { uid: OTHER, slot: 4, title: "Welcome back", lines: ["from Ms T"], pin: "2718", boot: true, start: 1800000000, end: 1800003600 }, { cookie: admin.cookie });
    expect(r.status).toBe(200);
    const j = await r.json();
    expect(j.slots[3]).toMatchObject({ title: "Welcome back", boot: true, start: 1800000000, end: 1800003600 });
    const bad = await postJson("/api/messages", { uid: OTHER, slot: 5, title: "x", pin: "1", start: 10, end: 5 }, { cookie: admin.cookie });
    expect(bad.status).toBe(400);
  });

  it("every Burrow gets the undelivered list in its snapshot reply, as the Bin wants it", async () => {
    const j = await snapshot();
    expect(j.ok).toBe(true);
    expect(j.messages).toEqual([
      { uid: UID, slot: 1, seq: 1, pin: "1612", by: "Ada (Dirt Vader)", title: "Go Worms!", lines: ["feed us", "", "please"], count: 3 },
      { uid: OTHER, slot: 4, seq: 1, pin: "2718", by: "ms-teacher", title: "Welcome back", lines: ["from Ms T"], start: 1800000000, end: 1800003600, boot: true },
    ]);
  });

  it("the Bin's ack (msg_seq in its data) takes a message off the list; a refusal is recorded", async () => {
    let j = await snapshot({ [UID]: { ts: 1, d: { msg_seq: { 1: 1 } } }, [OTHER]: { ts: 1, d: { msg_seq: { 4: -1 } } } });
    expect(j.messages).toEqual([]);
    j = await (await get(`/api/messages?uid=${UID}`, { cookie })).json();
    expect(j.status[1]).toMatchObject({ pending: false, result: "ok" });
    expect(j.slots[0].title).toBe("Go Worms!");
    j = await (await get(`/api/messages?uid=${OTHER}`, { cookie: admin.cookie })).json();
    expect(j.status[4]).toMatchObject({ pending: false, result: "refused" });
    // an old ack for a newer seq changes nothing
    await postJson("/api/messages", { uid: UID, slot: 1, title: "Newer", pin: "1612" }, { cookie });
    j = await snapshot({ [UID]: { ts: 2, d: { msg_seq: { 1: 1 } } } });
    expect(j.messages.map((m) => [m.uid, m.slot, m.seq, m.title])).toEqual([[UID, 1, 2, "Newer"]]);
  });

  it("clearing a slot is a message too", async () => {
    const r = await postJson("/api/messages", { uid: UID, slot: 1, clear: true, pin: "1612" }, { cookie });
    const j = await r.json();
    expect(j.slots[0]).toBeNull();
    expect(j.status[1]).toMatchObject({ seq: 3, pending: true });
    const s = await snapshot();
    expect(s.messages).toEqual([{ uid: UID, slot: 1, seq: 3, pin: "1612", by: "Ada (Dirt Vader)", clear: true }]);
  });
});
