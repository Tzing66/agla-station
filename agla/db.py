"""SQLite schema and connection. SQL only: business rules live in the tool layer.

The full schema (all phases) is created up front so later phases add code, not migrations.
See docs/architecture.md section 4.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    telegram_id INTEGER UNIQUE NOT NULL,
    first_name TEXT,
    language TEXT NOT NULL DEFAULT 'en',  -- en | hinglish | hi
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quotes (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    preference TEXT NOT NULL,
    route_json TEXT NOT NULL,
    fare_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trips (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    quote_id TEXT UNIQUE REFERENCES quotes(id),
    ticket_id TEXT UNIQUE NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    stations_json TEXT NOT NULL,  -- station ids passed, in order
    lines_json TEXT NOT NULL,     -- line ids ridden, in order
    route_json TEXT NOT NULL,     -- full Route (stops with cumulative minutes) for ETA/sharing
    fare_json TEXT NOT NULL,      -- full Fare with per-operator components
    interchanges INTEGER NOT NULL,
    minutes INTEGER NOT NULL,
    distance_km REAL NOT NULL,
    fare REAL NOT NULL,
    depart_at TEXT NOT NULL,
    eta TEXT NOT NULL,
    arrived_at TEXT,              -- set when the traveller taps "I've reached"
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS trips_user_depart ON trips(user_id, depart_at);
CREATE TABLE IF NOT EXISTS visits (
    user_id INTEGER NOT NULL REFERENCES users(id),
    station_id TEXT NOT NULL,
    first_visit TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (user_id, station_id)
);
CREATE TABLE IF NOT EXISTS badges (
    user_id INTEGER NOT NULL REFERENCES users(id),
    badge_id TEXT NOT NULL,
    earned_at TEXT NOT NULL,
    PRIMARY KEY (user_id, badge_id)
);
CREATE TABLE IF NOT EXISTS miles_ledger (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    trip_id INTEGER REFERENCES trips(id),
    delta INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS miles_user_created ON miles_ledger(user_id, created_at);
CREATE TABLE IF NOT EXISTS vouchers (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    reward_id TEXT NOT NULL,
    miles_spent INTEGER NOT NULL,
    code TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wrapped_recaps (
    user_id INTEGER NOT NULL REFERENCES users(id),
    month TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, month)
);
CREATE TABLE IF NOT EXISTS shares (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    trip_id INTEGER NOT NULL REFERENCES trips(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    arrived_at TEXT
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (and initialise) the database. Use ":memory:" in tests."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)  # autocommit; use tx()
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    init(conn)
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    migrate(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def migrate(conn: sqlite3.Connection) -> None:
    """Bring databases created by older versions up to date (CREATE IF NOT EXISTS won't add columns)."""
    user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "language" not in user_cols:  # v2
        conn.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'en'")
    trip_cols = {r["name"] for r in conn.execute("PRAGMA table_info(trips)")}
    if "arrived_at" not in trip_cols:  # v3: arrival moved onto the trip
        conn.execute("ALTER TABLE trips ADD COLUMN arrived_at TEXT")
    # v4: the automatic safety check was removed (see ledger/decisions.md); drop what it left behind
    for table in ("safety_checks", "trusted_contacts", "trust_invites"):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    for col in ("safety_on", "demo_fast"):
        if col in user_cols:
            conn.execute(f"ALTER TABLE users DROP COLUMN {col}")


class tx:
    """`with tx(conn): ...` runs the block in one transaction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN")
        return self.conn

    def __exit__(self, exc_type: object, *_: object) -> None:
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
