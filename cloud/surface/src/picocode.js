// Pico code over Wi-Fi: releases, targets, and the snapshot reply that carries them.
//   GET  /api/admin/pico                      releases, targets, what each bin reports running
//   POST /api/admin/pico/release {commit}     fetch that commit's worm-bin code files from GitHub, keep them
//   POST /api/admin/pico/target {uid, version}  one bin ("*" = every bin), version null = stop
//   GET  /v1/edge/code/<sha>                  a file, for a Burrow to cache and hand to its Bins
// A Bin reports d.code (the version it runs), d.code_trial, d.code_error ("<version>: why" after a
// roll-back); a version that failed on a bin is not offered to it again. Only code paths travel
// (the same rule as lib/ota.py code_path_ok): never boot.py, never a data file.
import { err, json, now, readJson, safeParse, sha256Hex } from "./util.js";

const RAW = (env, commit, path) => `${env.GITHUB_RAW_BASE || "https://raw.githubusercontent.com/MakerLabKids/whs-wormhole"}/${commit}/${path}`;
const PROJECT = "projects/worm-bin";

export function codePathOk(p) {
  if (typeof p !== "string" || !p || p.includes("..") || p.startsWith("/") || p.includes("//")) return false;
  if (["main.py", "index.html", "cal.js", "msg.js", "toc.txt"].includes(p)) return true;
  return /^lib\/[A-Za-z0-9_]+\.py$/.test(p);
}

function b64(buf) {
  const u = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
  return btoa(s);
}

export async function makeRelease(request, env, session) {
  const body = await readJson(request, 8 << 10);
  const commit = typeof body.commit === "string" && /^[0-9a-f]{7,40}$/.test(body.commit) ? body.commit : null;
  if (!commit) return err(400, "commit (a sha from git log on main) required");
  const version = commit.slice(0, 7);
  let pkg;
  try {
    const r = await fetch(RAW(env, commit, `${PROJECT}/package.json`), { headers: { "user-agent": "wormhole-surface" } });
    if (!r.ok) return err(502, `GitHub answered ${r.status} for ${PROJECT}/package.json at ${version}`);
    pkg = await r.json();
  } catch (e) {
    return err(502, "could not read the package list: " + (e.message || e));
  }
  const files = [], blobs = [];
  for (const pair of pkg.urls || []) {
    const dest = String(pair[0] || "").replace(/^fs:/, "");
    const src = String(pair[1] || "").replace(/^github:MakerLabKids\/whs-wormhole\//, "");
    if (!codePathOk(dest)) continue;                       // boot.py and anything else stay off the air
    const r = await fetch(RAW(env, commit, src), { headers: { "user-agent": "wormhole-surface" } });
    if (!r.ok) return err(502, `GitHub answered ${r.status} for ${src} at ${version}`);
    const buf = await r.arrayBuffer();
    const sha = await sha256Hex(buf);
    files.push({ path: dest, sha256: sha, size: buf.byteLength });
    blobs.push([sha, b64(buf)]);
  }
  if (!files.some((f) => f.path === "main.py")) return err(502, "that commit's worm-bin has no main.py");
  const stmts = blobs.map(([sha, data]) => env.DB.prepare("INSERT OR IGNORE INTO pico_blobs (sha256, data) VALUES (?1, ?2)").bind(sha, data));
  stmts.push(env.DB.prepare(`INSERT INTO pico_releases (version, files, created_by, created_at) VALUES (?1, ?2, ?3, ?4)
      ON CONFLICT(version) DO UPDATE SET files = excluded.files`).bind(version, JSON.stringify(files), session?.team?.name || session?.role || "admin", now()));
  await env.DB.batch(stmts);
  return json({ ok: true, version, files });
}

export async function setTarget(request, env, session) {
  const body = await readJson(request, 8 << 10);
  const uid = typeof body.uid === "string" && /^(\*|[0-9a-f]{8,32})$/.test(body.uid) ? body.uid : null;
  if (!uid) return err(400, "uid (a bin's uid, or * for every bin) required");
  if (body.version === null) {
    await env.DB.prepare("DELETE FROM pico_targets WHERE uid = ?1").bind(uid).run();
    return picoStatus(env);
  }
  const rel = await env.DB.prepare("SELECT version FROM pico_releases WHERE version = ?1").bind(String(body.version || "")).first();
  if (!rel) return err(404, "no release " + body.version + " (make it first)");
  await env.DB.prepare(`INSERT INTO pico_targets (uid, version, set_by, set_at) VALUES (?1, ?2, ?3, ?4)
      ON CONFLICT(uid) DO UPDATE SET version = excluded.version, set_by = excluded.set_by, set_at = excluded.set_at`)
    .bind(uid, rel.version, session?.team?.name || session?.role || "admin", now()).run();
  return picoStatus(env);
}

export async function picoStatus(env) {
  const releases = (await env.DB.prepare("SELECT version, files, created_by, created_at FROM pico_releases ORDER BY created_at DESC LIMIT 20").all()).results
    .map((r) => ({ ...r, files: safeParse(r.files, []).length }));
  const targets = (await env.DB.prepare("SELECT uid, version, set_by, set_at FROM pico_targets").all()).results;
  // what every bin reports, from the Burrows' latest snapshots (the newest reading of each bin wins)
  const bins = {};
  for (const e of (await env.DB.prepare("SELECT edge_id, snapshot FROM edges").all()).results) {
    for (const [uid, x] of Object.entries(safeParse(e.snapshot, {}) || {})) {
      if (!x || typeof x !== "object") continue;
      if (bins[uid] && (bins[uid].ts || 0) >= (x.ts || 0)) continue;
      const d = x.d || {};
      bins[uid] = { uid, name: x.name || d.name || null, bin: x.bin ?? d.bin?.bin ?? null, ts: x.ts || null, edge: x.edge || e.edge_id,
        code: d.code || null, trial: !!d.code_trial, error: d.code_error || null };
    }
  }
  return json({ ok: true, releases, targets, bins: Object.values(bins).sort((a, b) => (a.bin ?? 999) - (b.bin ?? 999)) });
}

// For a snapshot reply: the bins in THIS snapshot that should run another release.
export async function pendingCode(env, bins) {
  const uids = Object.keys(bins || {});
  if (!uids.length) return [];
  const targets = {};
  for (const t of (await env.DB.prepare("SELECT uid, version FROM pico_targets").all()).results) targets[t.uid] = t.version;
  const want = {};
  for (const uid of uids) {
    const v = targets[uid] || targets["*"];
    const d = bins[uid]?.d || {};
    if (!v || d.code === v) continue;
    if (typeof d.code_error === "string" && d.code_error.startsWith(v + ":")) continue;   // it failed there: not again
    want[uid] = v;
  }
  const versions = [...new Set(Object.values(want))];
  if (!versions.length) return [];
  const rel = {};
  for (const r of (await env.DB.prepare(`SELECT version, files FROM pico_releases WHERE version IN (${versions.map(() => "?").join(", ")})`).bind(...versions).all()).results) {
    rel[r.version] = safeParse(r.files, []);
  }
  return Object.entries(want).filter(([, v]) => rel[v]).map(([uid, v]) => ({ uid, version: v, files: rel[v] }));
}

export async function edgeCodeFile(env, sha) {
  if (!/^[0-9a-f]{64}$/.test(sha)) return err(400, "bad sha256");
  const r = await env.DB.prepare("SELECT data FROM pico_blobs WHERE sha256 = ?1").bind(sha).first();
  if (!r) return err(404, "no such file");
  const bin = atob(r.data), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return new Response(out, { headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } });
}
