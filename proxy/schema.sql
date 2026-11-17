-- Licenses are stored as the SHA-256 of the key, so a database leak does not leak working keys.
CREATE TABLE IF NOT EXISTS licenses (
  key_hash    TEXT PRIMARY KEY,
  label       TEXT NOT NULL,              -- who it was issued to, e.g. "beta: wedding tester"
  status      TEXT NOT NULL DEFAULT 'active',  -- 'active' or 'revoked'
  monthly_cap INTEGER,                    -- NULL = the MONTHLY_CAP default
  created     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS usage (
  key_hash TEXT NOT NULL,
  month    TEXT NOT NULL,                 -- 'YYYY-MM', UTC
  calls    INTEGER NOT NULL,
  PRIMARY KEY (key_hash, month)
);
