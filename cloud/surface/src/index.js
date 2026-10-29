// Wormhole Surface: the Cloudflare Worker.
//   /v1/edge/*   Burrows (bearer token)          -> edge.js
//   /api/*       viewers + admin (cookie)         -> auth.js, viewer.js, admin.js
//   /live/<room> SSE proxied from a Burrow tunnel
//   everything else: the dashboard SPA from static assets (+ one visits row per HTML page view)

import { handleAdmin } from "./admin.js";
import { watchEdges } from "./alerts.js";
import { getSession, listTeams, login, logout, meBody } from "./auth.js";
import { handleEdge } from "./edge.js";
import { HttpError, err, ipHash, json, now } from "./util.js";
import { apiBins, apiHistory, apiNow, apiPublicNow } from "./viewer.js";

export default {
  // cron (wrangler.jsonc triggers): a Burrow that went silent, or came back -> alert
  async scheduled(event, env, ctx) {
    ctx.waitUntil(watchEdges(env).catch((e) => console.error("watchEdges", e?.stack || e)));
  },
  async fetch(request, env, ctx) {
    try {
      return await route(request, env, ctx);
    } catch (e) {
      if (e instanceof HttpError) return err(e.status, e.message, e.extra);
      console.error("unhandled", e?.stack || e);
      return err(500, "internal error");
    }
  },
};

async function route(request, env, ctx) {
  const url = new URL(request.url);
  const path = url.pathname;

  if (path.startsWith("/v1/edge/")) return handleEdge(request, env, ctx, path);
  if (path.startsWith("/v1/")) return err(404, "not found");
  if (path.startsWith("/api/edge/")) return handleEdgeProxy(request, env, ctx, path);
  if (path.startsWith("/api/")) return handleApi(request, env, ctx, path);
  if (path.startsWith("/live/")) return handleLive(request, env, ctx, path);
  if (path === "/live") return err(404, "not found");
  return handlePage(request, env, ctx, path);
}

async function handleApi(request, env, ctx, path) {
  const m = request.method;
  // Public: the login form needs these before there is a cookie.
  if (path === "/api/teams" && m === "GET") return listTeams(env);
  if (path === "/api/login" && m === "POST") return login(request, env);
  if (path === "/api/admin/bootstrap") return handleAdmin(request, env, ctx, path, null);
  // Public, anonymous, trimmed and cached: the wall skins on GitHub Pages.
  if (path === "/api/public/now") return apiPublicNow(request, env, ctx);

  const session = await getSession(request, env, ctx);
  if (path === "/api/me") return session ? json(meBody(session)) : json({ ok: false }, 401);
  if (path === "/api/logout" && m === "POST") return logout(request, env, session);
  if (path.startsWith("/api/admin")) return handleAdmin(request, env, ctx, path, session);

  if (!session) return err(401, "login required");
  if (m !== "GET") return err(405, "method not allowed");
  if (path === "/api/now") return apiNow(request, env, ctx);
  if (path === "/api/bins") return apiBins(env);
  if (path === "/api/history") return apiHistory(request, env);
  return err(404, "not found");
}

// GET /api/edge/<room>/(signal|status|events): read-only passthrough to a Burrow
// through its tunnel, for logged-in viewers: the walk-around signal meter polls
// /signal twice a second; the Devices page may read status/events live.
async function handleEdgeProxy(request, env, ctx, path) {
  if (request.method !== "GET") return err(405, "method not allowed");
  const m = path.match(/^\/api\/edge\/([0-3])\/(signal|status|events)$/);
  if (!m) return err(404, "not found");
  const session = await getSession(request, env, ctx);
  if (!session) return err(401, "login required");
  const upstream = env.LIVE_BASE
    ? `${env.LIVE_BASE.replace(/\/$/, "")}/burrow${m[1]}/api/${m[2]}`
    : `https://burrow${m[1]}.${env.TUNNEL_DOMAIN}/api/${m[2]}`;
  let up;
  try {
    up = await fetch(upstream, { headers: { "x-burrow-key": env.LIVE_KEY || "", accept: "application/json" }, signal: AbortSignal.timeout(6000) });
  } catch (e) {
    return err(503, "edge offline");
  }
  if (!up.ok) return err(503, "edge offline", { status: up.status });
  return new Response(up.body, { status: 200, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}

// GET /live/<room>[?watch=<uid,...>]: the Burrow's SSE stream, through its
// cloudflared tunnel, with the shared header the Burrow insists on. Bytes pass
// straight through; D1 is never touched. `watch` (uids, at most 8) is passed on:
// the Burrow then polls those Bins once a second for this client (the 1 Hz live
// view). LIVE_BASE (optional var) replaces the tunnel host for local
// development: "<LIVE_BASE>/burrow<room>/live".
async function handleLive(request, env, ctx, path) {
  if (request.method !== "GET") return err(405, "method not allowed");
  const m = path.match(/^\/live\/([0-3])$/);
  if (!m) return err(404, "not found");
  const session = await getSession(request, env, ctx);
  if (!session) return err(401, "login required");
  const room = m[1];
  const watch = (new URL(request.url).searchParams.get("watch") || "")
    .split(",").map((s) => s.trim()).filter((s) => /^[0-9a-f]{8,32}$/i.test(s)).slice(0, 8);
  const qs = watch.length ? "?watch=" + watch.join(",") : "";
  const upstream = (env.LIVE_BASE
    ? `${env.LIVE_BASE.replace(/\/$/, "")}/burrow${room}/live`
    : `https://burrow${room}.${env.TUNNEL_DOMAIN}/live`) + qs;
  let up;
  try {
    up = await fetch(upstream, {
      headers: { "x-burrow-key": env.LIVE_KEY || "", accept: "text/event-stream" },
      signal: request.signal,
    });
  } catch (e) {
    return err(503, "edge offline");
  }
  if (!up.ok || !up.body) return err(503, "edge offline");
  return new Response(up.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-store",
      "x-accel-buffering": "no",
    },
  });
}

// Static dashboard. Any HTML GET by a logged-in viewer writes one visits row
// (polls under /api do not). No redirects: the SPA shows its own login form
// and asks /api/me, so anonymous requests still get index.html.
async function handlePage(request, env, ctx, path) {
  if (request.method !== "GET" && request.method !== "HEAD") return err(405, "method not allowed");
  const wantsHtml = (request.headers.get("accept") || "").includes("text/html");
  if (request.method === "GET" && wantsHtml) {
    const session = await getSession(request, env, ctx);
    if (session) {
      ctx.waitUntil(recordVisit(request, env, session, path));
    }
  }
  return env.ASSETS.fetch(request);
}

async function recordVisit(request, env, session, path) {
  try {
    await env.DB.prepare(
      "INSERT INTO visits (ts, team_id, first_name, path, ip_hash) VALUES (?1, ?2, ?3, ?4, ?5)",
    ).bind(now(), session.team.id, session.first_name, path.slice(0, 200), await ipHash(request, env)).run();
  } catch (e) {
    console.error("visit insert failed", e?.message || e);
  }
}
