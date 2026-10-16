// Small shared helpers: JSON replies, hashing, encoding, request parsing.
// Web APIs only (crypto.subtle, TextEncoder); nothing Node-specific.

const enc = new TextEncoder();

export const now = () => Math.floor(Date.now() / 1000);

export function json(obj, status = 200, headers = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers },
  });
}

// Every error is {ok:false, error} with a real status code, so clients never
// have to sniff HTML (the Burrow treats non-JSON as a captive portal).
export const err = (status, error, extra = {}) => json({ ok: false, error, ...extra }, status);

export class HttpError extends Error {
  constructor(status, message, extra) {
    super(message);
    this.status = status;
    this.extra = extra;
  }
}

export function hex(buf) {
  const b = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < b.length; i++) s += b[i].toString(16).padStart(2, "0");
  return s;
}

export function b64url(buf) {
  const b = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function sha256Hex(data) {
  const bytes = typeof data === "string" ? enc.encode(data) : data;
  return hex(await crypto.subtle.digest("SHA-256", bytes));
}

const hmacKeys = new Map(); // secret -> CryptoKey, per isolate
export async function hmacB64url(message, secret) {
  let key = hmacKeys.get(secret);
  if (!key) {
    key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    hmacKeys.set(secret, key);
  }
  return b64url(await crypto.subtle.sign("HMAC", key, enc.encode(message)));
}

// Compare two strings without leaking where they differ.
export function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const x = enc.encode(a), y = enc.encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

export function randomHex(nBytes) {
  const b = new Uint8Array(nBytes);
  crypto.getRandomValues(b);
  return hex(b);
}

// Parse a JSON body with a size cap; bad JSON is a 400, not a 500.
export async function readJson(request, cap = 1 << 20) {
  const len = Number(request.headers.get("content-length") || 0);
  if (len > cap) throw new HttpError(413, "body too large");
  const text = await request.text();
  if (text.length > cap) throw new HttpError(413, "body too large");
  if (!text) return {};
  try {
    const v = JSON.parse(text);
    if (v === null || typeof v !== "object") throw new Error();
    return v;
  } catch {
    throw new HttpError(400, "invalid json");
  }
}

export function parseCookies(request) {
  const out = {};
  const raw = request.headers.get("cookie") || "";
  for (const part of raw.split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

export function clientIp(request) {
  return request.headers.get("cf-connecting-ip") || request.headers.get("x-forwarded-for")?.split(",")[0].trim() || "0.0.0.0";
}

// IPs are never stored; they are hashed with a salt that rotates daily, so a
// week of visits cannot be joined back to one address.
export async function ipHash(request, env) {
  const day = new Date().toISOString().slice(0, 10);
  const salt = await sha256Hex(`${env.SESSION_SECRET || ""}:${day}`);
  return (await sha256Hex(salt + clientIp(request))).slice(0, 32);
}

export const isInt = (v) => Number.isInteger(v);
export const toInt = (v, dflt) => {
  if (v === undefined || v === null || v === "") return dflt;
  const n = Number(v);
  return Number.isFinite(n) ? Math.trunc(n) : dflt;
};

// Split an array into chunks of n (D1 allows 100 bound parameters per statement).
export function chunks(arr, n) {
  const out = [];
  for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n));
  return out;
}

export const safeParse = (s, dflt = null) => {
  if (s === null || s === undefined) return dflt;
  try { return JSON.parse(s); } catch { return dflt; }
};
