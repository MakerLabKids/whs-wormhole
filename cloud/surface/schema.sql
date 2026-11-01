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

-- Events: what a Burrow reports the moment it happens (bin quiet/back, Opal rebooted,
-- cloud back after an outage, service start). level: info | warn | alert.
CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          INTEGER,          -- the Burrow's clock when it happened
  edge        TEXT,
  kind        TEXT,
  level       TEXT,
  text        TEXT,
  data        TEXT,             -- JSON, optional
  received_at INTEGER           -- Worker clock
);
CREATE INDEX IF NOT EXISTS events_received ON events (received_at);
CREATE INDEX IF NOT EXISTS events_edge_ts ON events (edge, ts);

-- Alerts: one row per condition the Surface itself watches (a silent Burrow) or an
-- alert-level event it relayed; closed_at is set when the condition clears.
CREATE TABLE IF NOT EXISTS alerts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  key           TEXT NOT NULL,  -- edge:burrow1 | event:burrow1:opal ...
  edge          TEXT,
  text          TEXT,
  opened_at     INTEGER,
  closed_at     INTEGER,
  last_notified INTEGER,
  notify_error  TEXT
);
CREATE INDEX IF NOT EXISTS alerts_key_open ON alerts (key, closed_at);

-- Messages for a Bin's screen, set on the website: one row per (bin, slot), seq bumped on every
-- change. Listed to every Burrow (snapshot reply) until the Bin acks the seq in its push data
-- (msg_seq), which the next snapshot brings back; result is 'ok' or 'refused' (wrong PIN).
CREATE TABLE IF NOT EXISTS messages (
  uid          TEXT NOT NULL,
  slot         INTEGER NOT NULL,   -- 1-3 the team's, 4-5 the teacher's
  seq          INTEGER NOT NULL,
  title        TEXT,
  lines        TEXT,               -- JSON array of strings
  start_ts     INTEGER,
  end_ts       INTEGER,
  count        INTEGER NOT NULL DEFAULT 0,
  boot         INTEGER NOT NULL DEFAULT 0,
  cleared      INTEGER NOT NULL DEFAULT 0,
  pin          TEXT,
  set_by       TEXT,
  set_at       INTEGER,
  delivered_at INTEGER,
  result       TEXT,
  PRIMARY KEY (uid, slot)
);

-- What each Bin says is on its screen (its message slots), as the Burrows relay it; rev is the
-- Bin's own revision counter. The website shows this as the current state and refuses a save
-- based on an older rev.
CREATE TABLE IF NOT EXISTS bin_messages (
  uid     TEXT PRIMARY KEY,
  rev     INTEGER,
  slots   TEXT,               -- JSON array
  edge    TEXT,
  seen_at INTEGER
);

-- Rollouts: the admin asks ONE Burrow at a time to move to a commit. The Surface fetches that
-- commit's tarball from GitHub once to learn its sha256; the Burrow's snapshot reply carries
-- {build, sha256, url} while the request is open; the Burrow downloads, verifies, installs,
-- restarts and reports its build; the row closes when the reported build matches.
CREATE TABLE IF NOT EXISTS rollouts (
  edge         TEXT PRIMARY KEY,
  build        TEXT NOT NULL,     -- the commit (short or full sha)
  sha256       TEXT NOT NULL,     -- of the tarball
  url          TEXT NOT NULL,
  requested_by TEXT,
  requested_at INTEGER,
  done_at      INTEGER,
  error        TEXT
);

-- Enrolled Burrows: a fresh Pi (a cloned card, "needs identity") calls POST /v1/enrol with the
-- fleet secret (ENROL_SECRET), its hardware serial and the room its Opal's subnet says it is in;
-- it gets the name burrow<room>, a fresh upload token (only its sha256 is kept here) and the
-- room's tunnel token (TUNNEL_TOKENS secret). A new Pi in a room replaces the old one: the old
-- token stops working. EDGE_TOKENS (the original static tokens) still work alongside.
CREATE TABLE IF NOT EXISTS enrolled (
  edge        TEXT PRIMARY KEY,
  token_hash  TEXT NOT NULL,
  serial      TEXT NOT NULL,
  room        INTEGER,
  eth_mac     TEXT,
  wlan_mac    TEXT,
  ip          TEXT,
  enrolled_at INTEGER,
  replaced    TEXT              -- the serial this Pi replaced, if any
);

-- Shows for a Bin's screen, sent from the website (lib/pbmshow.py plays them): show_files holds
-- each PBM (base64, small: <= 128x64, <= 100 frames); show_lists the bin's playlist and a revision
-- that bumps on every change. A Burrow's snapshot reply lists the bins whose board has not
-- reported the newest rev; the Burrow fetches the files by sha256 (GET /v1/edge/shows/<sha>) and
-- hands them to the Bin, which reports shows_rev in its data once it has them.
CREATE TABLE IF NOT EXISTS show_files (
  uid     TEXT NOT NULL,
  name    TEXT NOT NULL,          -- [a-z0-9-], the file is shows/<name>.pbm on the board
  sha256  TEXT NOT NULL,
  size    INTEGER,
  frames  INTEGER,
  w       INTEGER,
  h       INTEGER,
  data    TEXT,                   -- base64 of the PBM
  set_by  TEXT,
  set_at  INTEGER,
  PRIMARY KEY (uid, name)
);
CREATE INDEX IF NOT EXISTS show_files_sha ON show_files (sha256);
CREATE TABLE IF NOT EXISTS show_lists (
  uid       TEXT PRIMARY KEY,
  rev       INTEGER NOT NULL,     -- bumps on every upload, delete or playlist change
  list      TEXT,                 -- JSON array of show names in order, NULL = the board's default
  set_by    TEXT,
  set_at    INTEGER,
  board_rev INTEGER,              -- what the board last reported having
  board_at  INTEGER
);
