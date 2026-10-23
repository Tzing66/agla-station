"""Rider statistics: computed in SQL/Python so the bot never states a number it made up."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

from agla.network.graph import load_network
from agla.tools.stations import get_station
from agla.tools.types import Stats, Visit


def get_stats(conn: sqlite3.Connection, user_id: int) -> Stats:
    agg = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(minutes), 0) AS mins, COALESCE(SUM(distance_km), 0) AS km, "
        "COALESCE(SUM(fare), 0) AS fare, MIN(depart_at) AS first, MAX(depart_at) AS last "
        "FROM trips WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    lines: Counter[str] = Counter()
    for (lines_json,) in conn.execute("SELECT lines_json FROM trips WHERE user_id = ?", (user_id,)):
        lines.update(ln for ln in json.loads(lines_json) if ln != "WALK")
    visits = get_visited_stations(conn, user_id)
    net = load_network()
    return Stats(
        trips=agg["n"],
        unique_stations=len(visits),
        total_minutes=int(agg["mins"]),
        total_km=round(agg["km"], 1),
        total_fare=int(agg["fare"]),
        favourite_line=net.lines[lines.most_common(1)[0][0]]["name"] if lines else None,
        top_stations=[(v.name, v.count) for v in sorted(visits, key=lambda v: (-v.count, v.name))[:3]],
        states_visited=sorted({v.state for v in visits}),
        first_trip_at=agg["first"],
        last_trip_at=agg["last"],
    )


def get_visited_stations(conn: sqlite3.Connection, user_id: int) -> list[Visit]:
    rows = conn.execute(
        "SELECT station_id, first_visit, count FROM visits WHERE user_id = ? ORDER BY first_visit", (user_id,)
    )
    out = []
    for r in rows:
        s = get_station(r["station_id"])
        out.append(Visit(r["station_id"], s.name, s.state, r["first_visit"], r["count"]))
    return out
