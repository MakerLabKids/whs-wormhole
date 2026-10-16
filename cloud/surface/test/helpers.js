// Shared test plumbing: schema, gzip fixtures, auth shortcuts.
import { env, SELF } from "cloudflare:test";
import schemaSql from "../schema.sql?raw";

export const TOKENS = { burrow1: "tok1", burrow2: "tok2", burrow3: "tok3" };

// D1's exec() wants one statement per line; split the file on ';' instead.
export async function applySchema() {
  const stmts = schemaSql
    .split("\n").filter((l) => !l.trim().startsWith("--")).join("\n")
    .split(";").map((s) => s.trim()).filter(Boolean);
  await env.DB.batch(stmts.map((s) => env.DB.prepare(s)));
}

export async function gzip(text) {
  const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export async function sha256Hex(bytes) {
  const b = typeof bytes === "string" ? new TextEncoder().encode(bytes) : bytes;
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", b)), (x) => x.toString(16).padStart(2, "0")).join("");
}

export const bearer = (edge) => ({ authorization: `Bearer ${TOKENS[edge]}` });

export function edgeFetch(edge, path, init = {}) {
  return SELF.fetch(`https://example.com${path}`, {
    ...init,
    headers: { ...bearer(edge), ...(init.body && typeof init.body === "string" ? { "content-type": "application/json" } : {}), ...(init.headers || {}) },
  });
}

export function postJson(path, body, headers = {}) {
  return SELF.fetch(`https://example.com${path}`, {
    method: "POST", body: JSON.stringify(body),
    headers: { "content-type": "application/json", ...headers },
  });
}

export const get = (path, headers = {}) => SELF.fetch(`https://example.com${path}`, { headers });

export function cookieOf(res) {
  const sc = res.headers.get("set-cookie") || "";
  return sc.split(";")[0];
}

// Rows of a casting: 3 bins, one row per minute.
export function sampleRows(t0, uids = ["aaa", "bbb", "ccc"], minutes = 15) {
  const rows = [];
  for (let i = 0; i < minutes; i++) {
    for (const uid of uids) {
      rows.push({ ts: t0 + i * 60, clk: "ntp", uid, name: `Team ${uid}`, room: 1, edge: "burrow1", src: "push",
        d: { temp: 20 + i * 0.1, moist: 50, bin: { team: `Team ${uid}`, period: 3, bin: 1, room: 1 } } });
    }
  }
  return rows;
}

export async function makeCasting(id, t0, rows = sampleRows(t0)) {
  const text = rows.map((r) => JSON.stringify(r)).join("\n") + "\n";
  const gz = await gzip(text);
  const meta = { id, room: 1, edge: "burrow1", origin: "burrow1", t0, t1: t0 + 899, rows: rows.length,
    sha256: await sha256Hex(gz), size: gz.length, created: t0 + 920 };
  return { gz, meta, rows };
}

export function putCasting(edge, id, gz, meta) {
  return edgeFetch(edge, `/v1/edge/castings/${id}`, {
    method: "PUT", body: gz,
    headers: { "content-type": "application/gzip", "x-casting-meta": JSON.stringify(meta) },
  });
}

// Bootstrap the first admin, or log in as it if an earlier beforeAll in this
// file already did (storage set up in beforeAll persists across describes).
export async function bootstrapAdmin(name = "ms-teacher", password = "correct horse battery") {
  const res = await postJson("/api/admin/bootstrap", { name, password, bootstrap: env.ADMIN_BOOTSTRAP });
  if (res.status !== 200 && !(await res.text()).includes("already exists")) throw new Error("bootstrap failed");
  const login = await postJson("/api/login", { name, passphrase: password });
  if (login.status !== 200) throw new Error("admin login failed: " + (await login.text()));
  return { cookie: cookieOf(login), team: (await login.json()).me.team };
}

// Create a team and return {team, passphrase}; if it already exists, reset
// its passphrase so the caller still gets a working one.
export async function createTeam(adminCookie, body) {
  const res = await postJson("/api/admin/teams", body, { cookie: adminCookie });
  if (res.status === 200) return res.json();
  if (res.status !== 409) throw new Error("create team failed: " + (await res.text()));
  const { teams } = await (await get("/api/admin/teams", { cookie: adminCookie })).json();
  const existing = teams.find((t) => t.name === body.name);
  const reset = await postJson(`/api/admin/teams/${existing.id}/reset`, {}, { cookie: adminCookie });
  return reset.json();
}

export async function loginTeam(team_id, passphrase, first_name = "Ada", ip = "10.0.0.1") {
  const res = await postJson("/api/login", { team_id, passphrase, first_name }, { "cf-connecting-ip": ip });
  return { res, cookie: res.status === 200 ? cookieOf(res) : null };
}
