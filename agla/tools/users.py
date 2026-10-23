"""Riders. Internal user_id everywhere; telegram_id only at the edge."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from agla.tools.types import LANGUAGES, ToolError, User


def _user(row: sqlite3.Row) -> User:
    return User(
        user_id=row["id"],
        telegram_id=row["telegram_id"],
        first_name=row["first_name"] or "Rider",
        safety_on=bool(row["safety_on"]),
        demo_fast=bool(row["demo_fast"]),
        language=row["language"],
    )


def get_or_create_user(conn: sqlite3.Connection, telegram_id: int, first_name: str | None, now: datetime) -> User:
    """Create the rider on first contact; keep their first name current (share pages show first name only)."""
    first = (first_name or "").split()[0] if first_name else None
    conn.execute(
        "INSERT INTO users (telegram_id, first_name, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(telegram_id) DO UPDATE SET first_name = COALESCE(excluded.first_name, users.first_name)",
        (telegram_id, first, now.isoformat()),
    )
    return _user(conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone())


def get_user(conn: sqlite3.Connection, user_id: int) -> User:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise ToolError(f"Unknown user {user_id}.")
    return _user(row)


def find_user_by_telegram_id(conn: sqlite3.Connection, telegram_id: int) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    return _user(row) if row else None


def set_safety(conn: sqlite3.Connection, user_id: int, on: bool) -> User:
    conn.execute("UPDATE users SET safety_on = ? WHERE id = ?", (int(on), user_id))
    return get_user(conn, user_id)


def set_language(conn: sqlite3.Connection, user_id: int, language: str) -> User:
    if language not in LANGUAGES:
        raise ToolError(f"Unknown language {language!r}; choose one of {', '.join(LANGUAGES)}.")
    conn.execute("UPDATE users SET language = ? WHERE id = ?", (language, user_id))
    return get_user(conn, user_id)
