"""SQLite access. The auth service owns the better-auth tables (user, session, account,
verification); this module owns the platform tables below. Both use the same file."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id            TEXT PRIMARY KEY,               -- biz_<slug>_<nn>
    owner_id      TEXT NOT NULL,                  -- better-auth user.id (usr_...)
    type          TEXT NOT NULL,
    name          TEXT NOT NULL,
    address       TEXT NOT NULL DEFAULT '',
    lat           REAL,
    lng           REAL,
    phone         TEXT NOT NULL DEFAULT '',
    hours         TEXT NOT NULL DEFAULT '{}',     -- JSON: {"mon": {"closed": false, "open": "09:00", "close": "18:00"}, ...}
    website_url   TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'draft',  -- draft | live
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS businesses_owner ON businesses(owner_id);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    start_url       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',   -- queued | crawling | analyzing | done | failed
    max_pages       INTEGER NOT NULL,
    pages_found     INTEGER NOT NULL DEFAULT 0,
    pages_done      INTEGER NOT NULL DEFAULT 0,
    pages_analyzed  INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    ai_status       TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | skipped | failed
    ai_error        TEXT,
    summary         TEXT,                             -- JSON from the site_summary task
    documents       TEXT NOT NULL DEFAULT '[]',       -- JSON: linked files (PDF price lists, menus...) not crawled
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS crawl_runs_business ON crawl_runs(business_id, id);

CREATE TABLE IF NOT EXISTS crawl_pages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
    url              TEXT NOT NULL,
    depth            INTEGER NOT NULL,
    status_code      INTEGER,
    title            TEXT NOT NULL DEFAULT '',
    meta_description TEXT NOT NULL DEFAULT '',
    lang             TEXT NOT NULL DEFAULT '',
    text             TEXT NOT NULL DEFAULT '',
    headings         TEXT NOT NULL DEFAULT '[]',
    links            TEXT NOT NULL DEFAULT '[]',
    forms            TEXT NOT NULL DEFAULT '[]',
    buttons          TEXT NOT NULL DEFAULT '[]',
    json_ld          TEXT NOT NULL DEFAULT '[]',
    screenshot_path  TEXT,
    analysis         TEXT,                            -- JSON from the page_analysis task
    error            TEXT,
    fetched_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS crawl_pages_run ON crawl_pages(run_id, id);

CREATE TABLE IF NOT EXISTS recordings (
    id              TEXT PRIMARY KEY,                -- rec_...
    business_id     TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    flow_name       TEXT NOT NULL,                   -- snake_case, e.g. book_table
    title           TEXT NOT NULL,
    source          TEXT NOT NULL,                   -- browser | upload
    status          TEXT NOT NULL,                   -- recording | finished | failed
    file_path       TEXT,                            -- JSON file, relative to database/files
    steps_count     INTEGER NOT NULL DEFAULT 0,
    actions_count   INTEGER NOT NULL DEFAULT 0,
    requests_count  INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    created_by      TEXT,
    uploaded_at     TEXT NOT NULL,
    finished_at     TEXT,
    processed       INTEGER NOT NULL DEFAULT 0       -- turned into a tool yet (Part D)
);
CREATE INDEX IF NOT EXISTS recordings_business ON recordings(business_id, flow_name);

CREATE TABLE IF NOT EXISTS tools (
    id               TEXT PRIMARY KEY,               -- tool_...
    business_id      TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,                  -- snake_case, what an AI assistant calls
    enabled          INTEGER NOT NULL DEFAULT 1,     -- the owner's on/off switch
    current_version  INTEGER,                        -- the version in use
    removed_at       TEXT,                           -- only the owner removes tools; history is kept
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS tools_name ON tools(business_id, name) WHERE removed_at IS NULL;

CREATE TABLE IF NOT EXISTS tool_versions (
    id                     TEXT PRIMARY KEY,         -- tv_...
    tool_id                TEXT NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    version                INTEGER NOT NULL,
    title                  TEXT NOT NULL,
    description_for_ai     TEXT NOT NULL,
    description_for_owner  TEXT NOT NULL,
    input_schema           TEXT NOT NULL,            -- JSON Schema of the inputs
    runner                 TEXT NOT NULL,            -- JSON: how the tool runs (declarative, no code)
    sensitivity            TEXT NOT NULL,            -- read_only | booking (takes an action) | personal_data | payment
    badge                  TEXT NOT NULL DEFAULT 'unchecked',  -- set by the checks (Part E)
    created_from           TEXT NOT NULL,            -- crawl:<run id> | recording:<id> | owner
    proposal_id            TEXT,
    reason                 TEXT NOT NULL DEFAULT '',
    content_hash           TEXT NOT NULL,
    created_at             TEXT NOT NULL,
    UNIQUE (tool_id, version)
);

CREATE TABLE IF NOT EXISTS proposals (
    id           TEXT PRIMARY KEY,                   -- prop_...
    business_id  TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    source       TEXT NOT NULL,                      -- crawl | recording
    source_id    TEXT NOT NULL,
    status       TEXT NOT NULL,                      -- generating | pending | applied | dismissed | failed
    summary      TEXT NOT NULL DEFAULT '',
    items        TEXT NOT NULL DEFAULT '[]',         -- JSON: proposed changes, platform flags, decisions
    written_by   TEXT NOT NULL DEFAULT '',           -- ai | platform
    error        TEXT,
    created_by   TEXT,
    created_at   TEXT NOT NULL,
    decided_at   TEXT
);
CREATE INDEX IF NOT EXISTS proposals_business ON proposals(business_id, created_at);

CREATE TABLE IF NOT EXISTS tool_checks (
    id           TEXT PRIMARY KEY,                   -- chk_...
    tool_id      TEXT NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    version_id   TEXT NOT NULL REFERENCES tool_versions(id) ON DELETE CASCADE,
    version      INTEGER NOT NULL,
    trigger      TEXT NOT NULL,                      -- change | daily | owner | live_test
    mode         TEXT NOT NULL DEFAULT 'auto',       -- auto | live (the owner asked for one real test)
    inputs       TEXT,                               -- JSON: sample inputs chosen by the owner, if any
    status       TEXT NOT NULL DEFAULT 'queued',     -- queued | running | done | error
    badge        TEXT,
    verified     INTEGER NOT NULL DEFAULT 0,         -- the tool really ran and worked
    security     TEXT NOT NULL DEFAULT '[]',         -- JSON: one finding per rule
    test         TEXT,                               -- JSON: the test run
    error        TEXT,
    created_at   TEXT NOT NULL,
    finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS tool_checks_tool ON tool_checks(tool_id, created_at);

CREATE TABLE IF NOT EXISTS alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    tool_id      TEXT,
    version      INTEGER,
    level        TEXT NOT NULL,                      -- blocked | broken
    message      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    seen_at      TEXT
);
CREATE INDEX IF NOT EXISTS alerts_business ON alerts(business_id, created_at);

CREATE TABLE IF NOT EXISTS owner_rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    tool_id      TEXT NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    input        TEXT NOT NULL,                      -- which input the rule looks at, e.g. people
    kind         TEXT NOT NULL,                      -- max | min
    value        REAL NOT NULL,
    message      TEXT NOT NULL DEFAULT '',           -- what the customer's assistant is told instead
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calls_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  TEXT REFERENCES businesses(id) ON DELETE CASCADE,
    tool_id      TEXT,
    tool_name    TEXT NOT NULL,
    version      INTEGER,
    outcome      TEXT NOT NULL,                      -- ok | failed | needs_confirmation | rule | rate_limited | not_published | bad_input
    inputs       TEXT NOT NULL DEFAULT '{}',         -- personal values masked
    result       TEXT,
    message      TEXT,
    duration_ms  INTEGER,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS calls_log_business ON calls_log(business_id, created_at);

CREATE TABLE IF NOT EXISTS demand_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  TEXT NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    keyword      TEXT NOT NULL,                      -- what a customer's assistant asked for and didn't find
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS demand_log_business ON demand_log(business_id, created_at);

CREATE TABLE IF NOT EXISTS ai_providers (
    id             TEXT PRIMARY KEY,                  -- aip_...
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL,                     -- anthropic | openai | openai_compatible
    base_url       TEXT NOT NULL DEFAULT '',
    api_key_enc    TEXT,                              -- Fernet token, never returned by the API
    api_key_hint   TEXT NOT NULL DEFAULT '',          -- last 4 characters, for display
    default_model  TEXT NOT NULL,
    supports_vision INTEGER NOT NULL DEFAULT 1,
    enabled        INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_routes (
    task         TEXT PRIMARY KEY,                    -- "default" or a task name from ai.tasks
    provider_id  TEXT REFERENCES ai_providers(id) ON DELETE SET NULL,
    model        TEXT NOT NULL DEFAULT '',            -- empty: the provider's default model
    effort       TEXT NOT NULL DEFAULT '',            -- Anthropic effort; empty: model default
    max_tokens   INTEGER,
    enabled      INTEGER NOT NULL DEFAULT 1,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL                              -- JSON
);

CREATE TABLE IF NOT EXISTS ai_calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    task           TEXT NOT NULL,
    user_id        TEXT,
    business_id    TEXT,
    provider_id    TEXT,
    provider_kind  TEXT,
    model          TEXT,
    ok             INTEGER NOT NULL,
    error          TEXT,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    latency_ms     INTEGER,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_calls_created ON ai_calls(created_at);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after a table first shipped; CREATE TABLE IF NOT EXISTS won't add them to
# a database that already exists.
COLUMNS = [
    ("businesses", "test_url", "TEXT NOT NULL DEFAULT ''"),  # a test copy of the business's system (bookings, orders...)
    ("tool_versions", "verified", "INTEGER NOT NULL DEFAULT 0"),
    ("tool_versions", "checked_at", "TEXT"),
    ("tool_versions", "rate_limit", "INTEGER"),  # calls per minute
    ("businesses", "public_key", "TEXT NOT NULL DEFAULT ''"),  # Ed25519, signs what the gateway returns
    ("businesses", "signing_key_enc", "TEXT"),
    ("businesses", "published_at", "TEXT"),
    ("businesses", "category_label", "TEXT NOT NULL DEFAULT ''"),  # the owner's own words, e.g. "bike repair shop"
    ("businesses", "online_only", "INTEGER NOT NULL DEFAULT 0"),   # no physical place: no address, map or hours needed
]


def init_db() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
        for table, column, decl in COLUMNS:
            if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        conn.execute("UPDATE tool_checks SET status = 'error', error = 'Interrupted by a server restart' WHERE status = 'running'")
        # A crawl thread does not survive a restart; close out runs it left behind.
        conn.execute(
            "UPDATE crawl_runs SET status = 'failed', error = 'Interrupted by a server restart', finished_at = ? "
            "WHERE status IN ('queued', 'crawling', 'analyzing')",
            (now(),),
        )
        conn.execute(
            "UPDATE recordings SET status = 'failed', error = 'Interrupted by a server restart', finished_at = ? WHERE status = 'recording'",
            (now(),),
        )
        conn.execute(
            "UPDATE proposals SET status = 'failed', error = 'Interrupted by a server restart' WHERE status = 'generating'"
        )


def update(table: str, id_: Any, **fields: Any) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    with session() as conn:
        conn.execute(f"UPDATE {table} SET {cols} WHERE id = ?", (*fields.values(), id_))


def row(r: sqlite3.Row | None, json_fields: tuple[str, ...] = ()) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    for f in json_fields:
        if f in d and isinstance(d[f], str):
            d[f] = json.loads(d[f])
    return d


def rows(rs: list[sqlite3.Row], json_fields: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    return [row(r, json_fields) for r in rs]  # type: ignore[misc]
