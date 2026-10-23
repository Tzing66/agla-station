"""Logging a trip, plus the post-trip hooks later phases plug into (miles, badges, safety check).

A hook is `fn(conn, trip, now) -> Any`; its return value lands in TripResult.hook_results[name].
Front ends never change when a hook is added.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from agla.db import tx
from agla.tools.quotes import get_quote
from agla.tools.stations import get_station
from agla.tools.tickets import render_ticket
from agla.tools.types import ToolError, Trip, TripResult, fare_from_dict, route_from_dict

PostTripHook = Callable[[sqlite3.Connection, Trip, datetime], Any]
_HOOKS: list[tuple[str, PostTripHook]] = []


def register_post_trip_hook(name: str, fn: PostTripHook) -> None:
    """Hooks run in registration order inside the trip's transaction."""
    if name not in {n for n, _ in _HOOKS}:
        _HOOKS.append((name, fn))


def visited_station_ids(trip: Trip) -> list[str]:
    """Visit rule (docs/architecture.md): origin, destination and interchange stops; not stations passed."""
    ids = [s.station_id for s in trip.route.stops if s.is_interchange]
    ids = [trip.route.from_id, *ids, trip.route.to_id]
    return list(dict.fromkeys(ids))


def log_trip(conn: sqlite3.Connection, quote_id: str, telegram_user_id: int, now: datetime) -> TripResult:
    """Turn a paid quote into a trip. Idempotent: pressing "I've paid" twice returns the same trip."""
    quote = get_quote(conn, quote_id)
    owner = conn.execute("SELECT telegram_id FROM users WHERE id = ?", (quote.user_id,)).fetchone()
    if owner is None or owner["telegram_id"] != telegram_user_id:
        raise ToolError("That trip quote belongs to someone else.")

    existing = conn.execute("SELECT * FROM trips WHERE quote_id = ?", (quote_id,)).fetchone()
    if existing is not None:
        trip = _trip_from_row(existing)
        return TripResult(trip, render_ticket(trip), [], {}, already_logged=True)

    if now > datetime.fromisoformat(quote.expires_at):
        raise ToolError("That quote has expired (they last 30 minutes). Ask for the route again for a fresh fare.")

    route, fare = quote.route, quote.fare
    eta = now + timedelta(minutes=route.minutes)
    ticket_id = "AGL-" + secrets.token_hex(4).upper()
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO trips (user_id, quote_id, ticket_id, from_id, to_id, stations_json, lines_json, "
            "route_json, fare_json, interchanges, minutes, distance_km, fare, depart_at, eta, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (quote.user_id, quote_id, ticket_id, route.from_id, route.to_id,
             json.dumps([s.station_id for s in route.stops]),
             json.dumps([leg.line_id for leg in route.legs]),
             json.dumps(route.to_dict()), json.dumps(fare.to_dict()),
             len(route.interchange_ids), route.minutes, route.distance_km, fare.total,
             now.isoformat(), eta.isoformat(), now.isoformat()),
        )
        trip = Trip(cur.lastrowid, quote.user_id, ticket_id, route, fare, now.isoformat(), eta.isoformat())
        new_visits = record_visits(conn, trip, now)
        results = {name: fn(conn, trip, now) for name, fn in _HOOKS}
    return TripResult(trip, render_ticket(trip), new_visits, results)


def record_visits(conn: sqlite3.Connection, trip: Trip, now: datetime) -> list[str]:
    """Upsert visits; return names of stations visited for the first time."""
    new: list[str] = []
    for sid in visited_station_ids(trip):
        key = (trip.user_id, sid)
        if conn.execute("SELECT 1 FROM visits WHERE user_id = ? AND station_id = ?", key).fetchone():
            conn.execute("UPDATE visits SET count = count + 1 WHERE user_id = ? AND station_id = ?", key)
        else:
            conn.execute(
                "INSERT INTO visits (user_id, station_id, first_visit, count) VALUES (?, ?, ?, 1)",
                (trip.user_id, sid, now.isoformat()),
            )
            new.append(get_station(sid).name)
    return new


def _trip_from_row(row: sqlite3.Row) -> Trip:
    return Trip(
        trip_id=row["id"],
        user_id=row["user_id"],
        ticket_id=row["ticket_id"],
        route=route_from_dict(json.loads(row["route_json"])),
        fare=fare_from_dict(json.loads(row["fare_json"])),
        depart_at=row["depart_at"],
        eta=row["eta"],
    )


def get_trip(conn: sqlite3.Connection, trip_id: int) -> Trip:
    row = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if row is None:
        raise ToolError(f"Unknown trip {trip_id}.")
    return _trip_from_row(row)
