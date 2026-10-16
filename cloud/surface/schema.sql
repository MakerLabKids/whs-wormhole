-- Wormhole Surface: D1 schema. Idempotent; run with
--   npx wrangler d1 execute wormhole --remote --file schema.sql
-- Timestamps are unix seconds (INTEGER). JSON columns are TEXT.

-- One row per Burrow: its latest snapshot (bins + status), upserted every 60 s.
CREATE TABLE IF NOT EXISTS edges (
  edge_id    TEXT PRIMARY KEY,
  room       INTEGER,
  ts         INTEGER,          -- the Burrow's clock at snapshot time
  clk        TEXT,             -- ntp | peer | free
  snapshot   TEXT,             -- JSON {uid: entry}
  status     TEXT,             -- JSON status block
  roster_at  INTEGER,          -- last time this edge sent a roster
  updated_at INTEGER           -- Worker clock when the row was written
);

-- Roster: what we know about each Bin (upsert on change only).
CREATE TABLE IF NOT EXISTS bins (
  uid        TEXT PRIMARY KEY,
  name       TEXT,
  team       TEXT,
  period     INTEGER,
  bin        INTEGER,
  room       INTEGER,
  first_seen INTEGER,
  last_seen  INTEGER
);

-- Immutable casting blocks mirrored to R2; verified_at is set only after a read-back hash match.
CREATE TABLE IF NOT EXISTS castings (
  id          TEXT PRIMARY KEY,
  room        INTEGER,
  edge        TEXT,             -- edge named in the meta (sealer)
  origin      TEXT,             -- origin edge if the meta carries one
  t0          INTEGER,
  t1          INTEGER,
  rows        INTEGER,
  sha256      TEXT,
  size        INTEGER,
  r2_key      TEXT,
  received_at INTEGER,
  uploaded_by TEXT,             -- the Burrow whose token did the PUT
  rollups_at  INTEGER,
  verified_at INTEGER
);
CREATE INDEX IF NOT EXISTS castings_room_t0 ON castings (room, t0);

-- Per-Bin aggregates: data = JSON {metric: [min, avg, max, n]}.
CREATE TABLE IF NOT EXISTS rollups (
  uid  TEXT NOT NULL,
  step TEXT NOT NULL,           -- 5m | 1h
  ts   INTEGER NOT NULL,        -- bucket start
  data TEXT,
  PRIMARY KEY (uid, step, ts)
);
CREATE INDEX IF NOT EXISTS rollups_step_ts ON rollups (step, ts);

-- Logins: team accounts (shared passphrase) plus teacher/admin accounts.
CREATE TABLE IF NOT EXISTS teams (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT UNIQUE NOT NULL,
  period     INTEGER,
  bin        INTEGER,
  room       INTEGER,
  role       TEXT NOT NULL DEFAULT 'team' CHECK (role IN ('team', 'teacher', 'admin')),
  pass_hash  TEXT,              -- hex PBKDF2-SHA256, 100000 iterations, 32 bytes
  pass_salt  TEXT,              -- hex, 16 bytes
  created_at INTEGER,
  disabled   INTEGER NOT NULL DEFAULT 0
);

-- Cookie sessions, keyed by sha256(sessionId) so a D1 leak does not leak cookies.
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  team_id    INTEGER NOT NULL,
  first_name TEXT,
  created_at INTEGER,
  last_seen  INTEGER,
  ua         TEXT
);
CREATE INDEX IF NOT EXISTS sessions_last_seen ON sessions (last_seen);

-- One row per HTML page load by a logged-in viewer (API polls do not count).
CREATE TABLE IF NOT EXISTS visits (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         INTEGER,
  team_id    INTEGER,
  first_name TEXT,
  path       TEXT,
  ip_hash    TEXT
);
CREATE INDEX IF NOT EXISTS visits_ts ON visits (ts);
CREATE INDEX IF NOT EXISTS visits_team ON visits (team_id);

-- Login rate limiting: attempts per hashed IP per 10-minute window.
CREATE TABLE IF NOT EXISTS login_attempts (
  ip_hash      TEXT NOT NULL,
  window_start INTEGER NOT NULL,
  n            INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (ip_hash, window_start)
);
