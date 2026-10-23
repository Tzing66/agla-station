"""Opening the app database from front ends that don't own a connection (MCP server, scripts)."""

from __future__ import annotations

import sqlite3

from agla.config import settings
from agla.db import connect

DEMO_TELEGRAM_ID = 1_000_001  # the rider scripts/seed_demo.py creates; MCP user tools default to it


def open_database() -> sqlite3.Connection:
    return connect(settings().db_path)
