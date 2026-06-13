PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS employees (
    canonical_name TEXT PRIMARY KEY,          -- точное значение option из Assign_new
    chat_id        INTEGER UNIQUE,            -- NULL = ещё не привязан
    bound_at       TEXT,                      -- ISO-8601 UTC
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS invite_codes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL REFERENCES employees(canonical_name) ON DELETE CASCADE,
    code_hash      TEXT NOT NULL,             -- sha256(code)
    expires_at     TEXT NOT NULL,             -- ISO-8601 UTC, TTL 24h
    used_at        TEXT,                      -- NULL = не использован
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_invites_name ON invite_codes(canonical_name);

CREATE TABLE IF NOT EXISTS task_snapshots (
    page_id          TEXT PRIMARY KEY,        -- notion page uuid
    title            TEXT NOT NULL DEFAULT '',
    status           TEXT,                    -- NULL допустим (HR-6)
    assignees        TEXT NOT NULL DEFAULT '[]',  -- JSON array имён
    reporter         TEXT NOT NULL DEFAULT '[]',  -- JSON array имён («Постановщик»)
    project_ids      TEXT NOT NULL DEFAULT '[]',  -- JSON array page_id
    due_start        TEXT,                    -- date ISO
    due_end          TEXT,
    url              TEXT NOT NULL DEFAULT '',
    last_edited_time TEXT NOT NULL,
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_snapshots_edited ON task_snapshots(last_edited_time);

CREATE TABLE IF NOT EXISTS sent_notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key  TEXT NOT NULL UNIQUE,          -- см. формулу ниже
    page_id    TEXT NOT NULL,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('new_assignee','status_changed')),
    chat_id    INTEGER NOT NULL,
    sent_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_sent_page ON sent_notifications(page_id);

CREATE TABLE IF NOT EXISTS bot_state (        -- kv-singleton
    key   TEXT PRIMARY KEY,                   -- 'checkpoint' | 'paused'
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_cache (
    page_id      TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    refreshed_at TEXT NOT NULL
);
