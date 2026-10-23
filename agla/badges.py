"""Badges: deterministic rules over the DB, evaluated after every trip. Non-consequential, just for fun.

Each badge has an id, name, description, a hint shown while locked, and check(conn, user_id, now) -> bool.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache

from agla.network.graph import load_network
from agla.tools.stations import get_station
from agla.tools.trips import visited_station_ids
from agla.tools.types import BadgeStatus, Trip, route_from_dict

Check = Callable[[sqlite3.Connection, int, datetime], bool]


@dataclass(frozen=True)
class Badge:
    badge_id: str
    name: str
    description: str
    hint: str
    check: Check


def _count(conn: sqlite3.Connection, sql: str, *args: object) -> int:
    return conn.execute(sql, args).fetchone()[0]


def _trips(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM trips WHERE user_id = ? ORDER BY depart_at", (user_id,)).fetchall()


def _unique_stations(conn: sqlite3.Connection, user_id: int) -> int:
    return _count(conn, "SELECT COUNT(*) FROM visits WHERE user_id = ?", user_id)


@cache
def line_terminals() -> dict[str, frozenset[str]]:
    """Both ends of each line (stations with one neighbour on that line). Loops like Rapid Metro have one end."""
    degree: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for e in load_network_edges():
        degree[e["line"]][e["from"]].add(e["to"])
        degree[e["line"]][e["to"]].add(e["from"])
    return {line: frozenset(s for s, nbrs in stations.items() if len(nbrs) == 1) for line, stations in degree.items()}


@cache
def load_network_edges() -> tuple[dict, ...]:
    net = load_network()
    return tuple({"line": line, "from": a, "to": b}
                 for (a, line), (b, line_b) in net.graph.edges if line == line_b and a != b)  # ride edges only


@cache
def line_stations() -> dict[str, frozenset[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for sid, s in load_network().stations.items():
        for line in s["lines"]:
            out[line].add(sid)
    return {line: frozenset(v) for line, v in out.items()}


def _hour_trip(conn: sqlite3.Connection, user_id: int, ok: Callable[[int], bool]) -> bool:
    return any(ok(datetime.fromisoformat(t["depart_at"]).hour) for t in _trips(conn, user_id))


def _terminal_to_terminal(conn: sqlite3.Connection, user_id: int, now: datetime) -> bool:
    ends = [t for t in line_terminals().values() if len(t) == 2]
    return any({t["from_id"], t["to_id"]} == set(pair) for t in _trips(conn, user_id) for pair in ends)


def _state_hopper(conn: sqlite3.Connection, user_id: int, now: datetime) -> bool:
    """Delhi, Haryana and UP all visited within one 7-day window (by trip visit rule)."""
    week = [(datetime.fromisoformat(t["depart_at"]), _trip_states(t)) for t in _trips(conn, user_id)]
    for start, _ in week:
        states = set().union(*(s for when, s in week if start <= when < start + timedelta(days=7)))
        if {"Delhi", "Haryana", "UP"} <= states:
            return True
    return False


def _trip_states(row: sqlite3.Row) -> set[str]:
    route = route_from_dict(json.loads(row["route_json"]))
    trip = Trip(row["id"], row["user_id"], row["ticket_id"], route, None, row["depart_at"], row["eta"])  # type: ignore[arg-type]
    return {get_station(s).state for s in visited_station_ids(trip)}


def _loyal(conn: sqlite3.Connection, user_id: int, now: datetime) -> bool:
    return _count(conn, "SELECT COALESCE(MAX(n), 0) FROM (SELECT COUNT(*) AS n FROM trips WHERE user_id = ? "
                        "GROUP BY from_id, to_id)", user_id) >= 10


def _line_collector(line_id: str) -> Check:
    def check(conn: sqlite3.Connection, user_id: int, now: datetime) -> bool:
        visited = {r[0] for r in conn.execute("SELECT station_id FROM visits WHERE user_id = ?", (user_id,))}
        return line_stations()[line_id] <= visited
    return check


BADGES: list[Badge] = [
    Badge("first_ride", "Agla Station", "Logged your first trip.", "Take your first trip.",
          lambda c, u, n: _count(c, "SELECT COUNT(*) FROM trips WHERE user_id = ?", u) >= 1),
    Badge("explorer_10", "Explorer", "Visited 10 different stations.", "Visit 10 different stations.",
          lambda c, u, n: _unique_stations(c, u) >= 10),
    Badge("explorer_25", "Cartographer", "Visited 25 different stations.", "Visit 25 different stations.",
          lambda c, u, n: _unique_stations(c, u) >= 25),
    Badge("interchange_goblin", "Interchange Goblin", "10 trips with 2 or more changes.",
          "Take 10 trips that change lines at least twice.",
          lambda c, u, n: _count(c, "SELECT COUNT(*) FROM trips WHERE user_id = ? AND interchanges >= 2", u) >= 10),
    Badge("terminal_to_terminal", "End of the Line", "Rode a line from one end to the other.",
          "Travel between both ends of any line.", _terminal_to_terminal),
    Badge("night_owl", "Night Owl", "Took a trip after 10pm.", "Ride after 10pm.",
          lambda c, u, n: _hour_trip(c, u, lambda h: h >= 22)),
    Badge("early_bird", "Early Bird", "Took a trip before 7am.", "Ride before 7am.",
          lambda c, u, n: _hour_trip(c, u, lambda h: h < 7)),
    Badge("state_hopper", "State Hopper", "Delhi, Haryana and UP in one week.",
          "Visit stations in Delhi, Haryana and UP within a week.", _state_hopper),
    Badge("loyal", "Regular", "Took the same route 10 times.", "Take the same route 10 times.", _loyal),
    Badge("miles_1000", "Thousand Miler", "Earned 1,000 Metro Miles.", "Earn 1,000 Metro Miles.",
          lambda c, u, n: _count(c, "SELECT COALESCE(SUM(delta), 0) FROM miles_ledger WHERE user_id = ? AND delta > 0",
                                 u) >= 1000),
    Badge("safe_and_sound", "Safe and Sound", "Confirmed 5 arrivals with the safety check on.",
          "Turn on /safety and confirm 5 arrivals.",
          lambda c, u, n: _count(c, "SELECT COUNT(*) FROM safety_checks WHERE user_id = ? AND arrived_at IS NOT NULL",
                                 u) >= 5),
]


@cache
def all_badges() -> tuple[Badge, ...]:
    net = load_network()
    collectors = [
        Badge(f"line_collector_{line.lower()}", f"Line Collector: {meta['name']}",
              f"Visited every station on the {meta['name']}.", f"Visit every station on the {meta['name']}.",
              _line_collector(line))
        for line, meta in net.lines.items()
    ]
    return (*BADGES, *collectors)


def evaluate_badges(conn: sqlite3.Connection, user_id: int, now: datetime) -> list[BadgeStatus]:
    """Award any newly earned badges; return them."""
    earned = {r[0] for r in conn.execute("SELECT badge_id FROM badges WHERE user_id = ?", (user_id,))}
    new = []
    for b in all_badges():
        if b.badge_id not in earned and b.check(conn, user_id, now):
            conn.execute("INSERT INTO badges (user_id, badge_id, earned_at) VALUES (?, ?, ?)",
                         (user_id, b.badge_id, now.isoformat()))
            new.append(BadgeStatus(b.badge_id, b.name, b.description, b.hint, now.isoformat()))
    return new


def badges_hook(conn: sqlite3.Connection, trip: Trip, now: datetime) -> list[dict]:
    """Post-trip hook: newly earned badges as dicts for the bot."""
    return [b.to_dict() for b in evaluate_badges(conn, trip.user_id, now)]


def get_badges(conn: sqlite3.Connection, user_id: int) -> list[BadgeStatus]:
    earned = {r["badge_id"]: r["earned_at"] for r in conn.execute(
        "SELECT badge_id, earned_at FROM badges WHERE user_id = ?", (user_id,))}
    return [BadgeStatus(b.badge_id, b.name, b.description, b.hint, earned.get(b.badge_id)) for b in all_badges()]
