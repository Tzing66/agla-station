"""Quotes: a priced route stored server-side. Payment links and "I've paid" refer to a quote id,
so the amount a rider pays always comes from code, never from the LLM."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta

from agla.tools.fares import get_fare
from agla.tools.routing import plan_route
from agla.tools.stations import resolve_station
from agla.tools.types import Preference, Quote, ToolError, fare_from_dict, route_from_dict

QUOTE_TTL = timedelta(minutes=30)


def quote_trip(
    conn: sqlite3.Connection,
    user_id: int,
    origin: str,
    destination: str,
    preference: Preference,
    now: datetime,
) -> Quote:
    """Resolve both stations (names or ids), plan, price for today, and store the quote."""
    a, b = resolve_station(origin), resolve_station(destination)
    route = plan_route(a.station_id, b.station_id, preference, on=now.date())
    fare = get_fare(route, now.date())
    quote = Quote(
        quote_id=secrets.token_urlsafe(9),  # 12 chars: fits Telegram's 64-byte callback data with room to spare
        user_id=user_id,
        route=route,
        fare=fare,
        created_at=now.isoformat(),
        expires_at=(now + QUOTE_TTL).isoformat(),
    )
    conn.execute(
        "INSERT INTO quotes (id, user_id, from_id, to_id, preference, route_json, fare_json, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (quote.quote_id, user_id, route.from_id, route.to_id, preference,
         json.dumps(route.to_dict()), json.dumps(fare.to_dict()), quote.created_at, quote.expires_at),
    )
    return quote


def purge_expired_quotes(conn: sqlite3.Connection, now: datetime, keep: timedelta = timedelta(days=1)) -> int:
    """Delete quotes that expired over `keep` ago and were never paid (paid ones are referenced by a trip)."""
    cur = conn.execute(
        "DELETE FROM quotes WHERE expires_at < ? AND id NOT IN (SELECT quote_id FROM trips WHERE quote_id IS NOT NULL)",
        ((now - keep).isoformat(),),
    )
    return cur.rowcount


def get_quote(conn: sqlite3.Connection, quote_id: str) -> Quote:
    row = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
    if row is None:
        raise ToolError("That trip quote doesn't exist any more. Ask for the route again.")
    return Quote(
        quote_id=row["id"],
        user_id=row["user_id"],
        route=route_from_dict(json.loads(row["route_json"])),
        fare=fare_from_dict(json.loads(row["fare_json"])),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )
