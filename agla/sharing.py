"""Journey sharing and "I've reached".

- estimate_position(trip, now): where the rider should be, from the timetable. Pure; no GPS (none underground).
- Shares: random-token links showing first name only; they expire (ETA + 2h, or 30 min after the rider arrives).
- Arrival: the traveller taps "I've reached"; the trip is marked arrived, any shared page flips to Arrived, and the
  bot hands back a ready-made message the traveller sends to whoever they choose. Nobody is messaged automatically.
"""

from __future__ import annotations

import math
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from agla.tools.stations import get_station
from agla.tools.trips import get_trip
from agla.tools.types import ToolError, Trip, _Base
from agla.tools.users import find_user_by_telegram_id, get_user

SHARE_TTL_AFTER_ETA = timedelta(hours=2)
SHARE_TTL_AFTER_ARRIVAL = timedelta(minutes=30)
OVERDUE_AFTER = timedelta(minutes=15)

PositionState = Literal["not_started", "riding", "changing", "walking", "arrived"]


@dataclass(frozen=True)
class Position(_Base):
    state: PositionState
    text: str
    line_name: str | None
    progress_pct: int
    eta: str
    minutes_left: int
    reached_ids: list[str]  # stations the timetable says the rider has reached (for the progress bar)


@dataclass(frozen=True)
class ShareView(_Base):
    token: str
    first_name: str
    from_name: str
    to_name: str
    stations: list[tuple[str, bool, bool]]  # (name, reached, key) in route order; key = worth showing when collapsed
    position: Position
    status: Literal["on_the_way", "arrived", "overdue"]
    eta_hm: str
    arrived_hm: str | None
    expires_at: str


def _hm(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%-I:%M %p")


def _name(sid: str) -> str:
    return get_station(sid).name


# --- position (pure) ---------------------------------------------------------------------------------------------


def estimate_position(trip: Trip, now: datetime) -> Position:
    """Where the rider should be at `now`, from departure time and the route's cumulative minutes."""
    route = trip.route
    depart = datetime.fromisoformat(trip.depart_at)
    elapsed = (now - depart).total_seconds() / 60
    total = route.stops[-1].cum_minutes or route.minutes or 1
    eta = datetime.fromisoformat(trip.eta)
    minutes_left = max(0, math.ceil((eta - now).total_seconds() / 60))
    pct = int(max(0, min(100, elapsed / total * 100)))
    arrival = {s.station_id: s.cum_minutes for s in route.stops}

    def times(leg) -> list[float]:  # departure for the first station, arrival times after that
        return [leg.start_minutes, *(arrival[s] for s in leg.station_ids[1:])]

    reached = [s.station_id for s in route.stops if s.cum_minutes <= elapsed] if elapsed >= 0 else []
    base = {"eta": trip.eta, "minutes_left": minutes_left, "progress_pct": pct, "reached_ids": reached}

    if elapsed < 0:
        return Position("not_started", f"Starting soon from {_name(route.from_id)}", None,
                        **{**base, "progress_pct": 0})
    if elapsed >= total:
        return Position("arrived", f"Should have arrived at {_name(route.to_id)}", None,
                        **{**base, "progress_pct": 100, "reached_ids": [s.station_id for s in route.stops]})
    for i, leg in enumerate(route.legs):
        if leg.start_minutes <= elapsed < leg.end_minutes:
            if leg.line_id == "WALK":
                return Position("walking", f"Walking from {_name(leg.from_id)} to {_name(leg.to_id)}", None, **base)
            t = times(leg)
            for a, b, ta, tb in zip(leg.station_ids, leg.station_ids[1:], t, t[1:], strict=False):
                if ta <= elapsed < tb:
                    return Position("riding", f"Between {_name(a)} and {_name(b)}", leg.line_name, **base)
        nxt = route.legs[i + 1] if i + 1 < len(route.legs) else None
        if nxt and leg.end_minutes <= elapsed < nxt.start_minutes:
            return Position("changing", f"Changing at {_name(leg.to_id)} to the {nxt.line_name}", None, **base)
    return Position("arrived", f"Should have arrived at {_name(route.to_id)}", None, **base)


# --- shares ------------------------------------------------------------------------------------------------------


def create_share(conn: sqlite3.Connection, trip_id: int, telegram_user_id: int, now: datetime) -> str:
    """Return the trip's share token, creating it on first use. Only the trip's owner may share it."""
    trip = _own_trip(conn, trip_id, telegram_user_id)
    row = conn.execute("SELECT token FROM shares WHERE trip_id = ?", (trip_id,)).fetchone()
    if row:
        return row["token"]
    token = secrets.token_urlsafe(16)
    arrived = _arrived_at(conn, trip_id)
    expires = (datetime.fromisoformat(arrived) + SHARE_TTL_AFTER_ARRIVAL if arrived
               else datetime.fromisoformat(trip.eta) + SHARE_TTL_AFTER_ETA)
    conn.execute(
        "INSERT INTO shares (token, user_id, trip_id, created_at, expires_at, arrived_at) VALUES (?, ?, ?, ?, ?, ?)",
        (token, trip.user_id, trip_id, now.isoformat(), expires.isoformat(), arrived),
    )
    return token


def get_share_view(conn: sqlite3.Connection, token: str, now: datetime) -> ShareView | None:
    """The public share page's data, or None if the token is unknown or the link has expired."""
    row = conn.execute("SELECT * FROM shares WHERE token = ?", (token,)).fetchone()
    if row is None or now >= datetime.fromisoformat(row["expires_at"]):
        return None
    trip = get_trip(conn, row["trip_id"])
    user = get_user(conn, row["user_id"])
    pos = estimate_position(trip, now)
    arrived = _arrived_at(conn, trip.trip_id)
    if arrived:
        status = "arrived"
    elif now > datetime.fromisoformat(trip.eta) + OVERDUE_AFTER:
        status = "overdue"
    else:
        status = "on_the_way"
    stops = trip.route.stops
    reached = set(pos.reached_ids) | ({s.station_id for s in stops} if arrived else set())
    last = max((i for i, s in enumerate(stops) if s.station_id in reached), default=-1)
    key = {0, len(stops) - 1, last, last + 1} | {i for i, s in enumerate(stops) if s.is_interchange}
    return ShareView(
        token=token,
        first_name=user.first_name,
        from_name=_name(trip.route.from_id),
        to_name=_name(trip.route.to_id),
        stations=[(s.name, s.station_id in reached, i in key) for i, s in enumerate(stops)],
        position=pos,
        status=status,
        eta_hm=_hm(trip.eta),
        arrived_hm=_hm(arrived) if arrived else None,
        expires_at=row["expires_at"],
    )


def share_message(first_name: str, trip: Trip, url: str) -> str:
    return (f"I'm on my way: {_name(trip.route.from_id)} → {_name(trip.route.to_id)}, ETA {_hm(trip.eta)}. "
            f"Track me: {url}")


# --- arrival -------------------------------------------------------------------------------------------------------


def confirm_arrival(conn: sqlite3.Connection, trip_id: int, telegram_user_id: int, now: datetime) -> dict:
    """The traveller taps "I've reached". Marks the trip arrived (once), flips any shared page to Arrived and lets
    its link expire 30 min later, and awards the arrival miles once.
    Returns {"already": bool, "miles": int, "message": str} where message is ready to send to someone."""
    from agla.miles import award_safe_arrival  # local: miles imports the tool layer

    trip = _own_trip(conn, trip_id, telegram_user_id)
    user = get_user(conn, trip.user_id)
    already = _arrived_at(conn, trip_id)
    message = f"✅ {user.first_name} has reached {_name(trip.route.to_id)} ({_hm(already or now.isoformat())})."
    if already:
        return {"already": True, "miles": 0, "message": message}
    conn.execute("UPDATE trips SET arrived_at = ? WHERE id = ?", (now.isoformat(), trip_id))
    share = conn.execute("SELECT expires_at FROM shares WHERE trip_id = ?", (trip_id,)).fetchone()
    if share:
        expires = min(datetime.fromisoformat(share["expires_at"]), now + SHARE_TTL_AFTER_ARRIVAL)
        conn.execute("UPDATE shares SET arrived_at = ?, expires_at = ? WHERE trip_id = ?",
                     (now.isoformat(), expires.isoformat(), trip_id))
    miles = award_safe_arrival(conn, trip.user_id, trip_id, now)
    return {"already": False, "miles": miles, "message": message}


def _arrived_at(conn: sqlite3.Connection, trip_id: int) -> str | None:
    row = conn.execute("SELECT arrived_at FROM trips WHERE id = ?", (trip_id,)).fetchone()
    return row["arrived_at"] if row else None


def _own_trip(conn: sqlite3.Connection, trip_id: int, telegram_user_id: int) -> Trip:
    trip = get_trip(conn, trip_id)
    owner = find_user_by_telegram_id(conn, telegram_user_id)
    if owner is None or owner.user_id != trip.user_id:
        raise ToolError("That trip belongs to someone else.")
    return trip
