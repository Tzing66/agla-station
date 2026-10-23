"""Dashboard data: map, per-line completion, insights and the Wrapped archive. Every number computed here."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta

from agla.network.graph import load_network
from agla.tools.stations import get_station


def _visits(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    return {r["station_id"]: r["count"] for r in conn.execute(
        "SELECT station_id, count FROM visits WHERE user_id = ?", (user_id,))}


def map_data(conn: sqlite3.Connection, user_id: int) -> dict:
    """All stations with coordinates, line colours and whether this rider has visited them."""
    net = load_network()
    visits = _visits(conn, user_id)
    lines = {lid: {"name": m["name"], "colour": m["colour"]} for lid, m in net.lines.items()}
    stations = [
        {"id": sid, "name": s["name"], "lat": s["lat"], "lon": s["lon"], "lines": s["lines"],
         "visits": visits.get(sid, 0)}
        for sid, s in net.stations.items()
    ]
    seen: set[tuple[str, frozenset[str]]] = set()
    segments = []
    for (a, la), (b, lb), d in net.graph.edges(data=True):
        if d["kind"] == "ride" and la == lb and (key := (la, frozenset((a, b)))) not in seen:
            seen.add(key)
            sa, sb = net.stations[a], net.stations[b]
            segments.append({"line": la, "path": [[sa["lat"], sa["lon"]], [sb["lat"], sb["lon"]]]})
    return {"lines": lines, "stations": stations, "segments": segments,
            "completion": line_completion(conn, user_id)}


def line_completion(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """Per line: stations visited / total, in the network's line order (branches and extensions included)."""
    net = load_network()
    visited = set(_visits(conn, user_id))
    out = []
    for lid, meta in net.lines.items():
        on_line = [sid for sid, s in net.stations.items() if lid in s["lines"]]
        done = sum(1 for sid in on_line if sid in visited)
        out.append({"line": lid, "name": meta["name"], "colour": meta["colour"], "visited": done,
                    "total": len(on_line), "pct": round(done / len(on_line) * 100) if on_line else 0})
    return out


def insights(conn: sqlite3.Connection, user_id: int, today: date, weeks: int = 8) -> dict:
    """Trips per week (Monday-start, last `weeks` weeks), line split, top stations and totals."""
    rows = conn.execute("SELECT depart_at, lines_json, minutes, distance_km, fare FROM trips WHERE user_id = ?",
                        (user_id,)).fetchall()
    this_monday = today - timedelta(days=today.weekday())
    starts = [this_monday - timedelta(weeks=w) for w in range(weeks - 1, -1, -1)]
    per_week: Counter[date] = Counter()
    lines: Counter[str] = Counter()
    for r in rows:
        d = datetime.fromisoformat(r["depart_at"]).date()
        per_week[d - timedelta(days=d.weekday())] += 1
        lines.update({ln for ln in json.loads(r["lines_json"]) if ln != "WALK"})
    net = load_network()
    visits = _visits(conn, user_id)
    top = sorted(visits.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return {
        "trips_per_week": [{"week": s.isoformat(), "label": s.strftime("%-d %b"), "trips": per_week.get(s, 0)}
                           for s in starts],
        "line_split": [{"line": lid, "name": net.lines[lid]["name"], "colour": net.lines[lid]["colour"], "trips": n}
                       for lid, n in lines.most_common()],
        "top_stations": [{"name": get_station(sid).name, "visits": n} for sid, n in top],
        "totals": {
            "trips": len(rows),
            "minutes": int(sum(r["minutes"] for r in rows)),
            "km": round(sum(r["distance_km"] for r in rows), 1),
            "fare": int(sum(r["fare"] for r in rows)),
            "stations": len(visits),
        },
    }


def trip_months(conn: sqlite3.Connection, user_id: int) -> list[str]:
    """Months (YYYY-MM) with at least one trip, newest first."""
    return [m for (m,) in conn.execute(
        "SELECT DISTINCT substr(depart_at, 1, 7) AS m FROM trips WHERE user_id = ? ORDER BY m DESC", (user_id,))]
