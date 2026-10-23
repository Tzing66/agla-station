"""Metro Wrapped: a rider's month in numbers (computed here), narrated by the LLM, rendered as a card.

Every figure in a recap comes from wrapped_stats(); the narration is checked against it by the number guard.
"""

from __future__ import annotations

import io
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

from PIL import Image, ImageDraw, ImageFont

from agla.network.graph import load_network
from agla.tools.stations import get_station
from agla.tools.trips import visited_station_ids
from agla.tools.types import ToolError, Trip, _Base, route_from_dict


@dataclass(frozen=True)
class WrappedStats(_Base):
    month: str  # "2026-10"
    month_name: str  # "October 2026"
    first_name: str
    trips: int
    unique_stations: int
    new_stations: int  # first ever visit happened this month
    top_stations: list[tuple[str, int]]  # (name, visits this month), up to 3
    favourite_line: str | None
    favourite_line_trips: int
    total_minutes: int
    total_km: float
    total_fare: int
    miles_earned: int
    badges_earned: list[str]
    busiest_day: str | None  # "Thursday 1 October"
    busiest_day_trips: int
    states: list[str]


@dataclass(frozen=True)
class Recap(_Base):
    month: str
    stats: WrappedStats
    text: str
    created_at: str


def _month_bounds(month: str) -> tuple[str, str]:
    try:
        start = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise ToolError(f"Bad month {month!r}: use YYYY-MM, e.g. 2026-10.") from exc
    end = date(start.year + start.month // 12, start.month % 12 + 1, 1)
    return start.isoformat(), end.isoformat()


def wrapped_stats(conn: sqlite3.Connection, user_id: int, month: str) -> WrappedStats:
    start, end = _month_bounds(month)
    rows = conn.execute(
        "SELECT * FROM trips WHERE user_id = ? AND depart_at >= ? AND depart_at < ? ORDER BY depart_at",
        (user_id, start, end),
    ).fetchall()
    first_name = conn.execute("SELECT first_name FROM users WHERE id = ?", (user_id,)).fetchone()[0] or "Rider"

    station_visits: Counter[str] = Counter()
    lines: Counter[str] = Counter()
    days: Counter[str] = Counter()
    for r in rows:
        route = route_from_dict(json.loads(r["route_json"]))
        trip = Trip(r["id"], user_id, r["ticket_id"], route, None, r["depart_at"], r["eta"])  # type: ignore[arg-type]
        station_visits.update(visited_station_ids(trip))
        lines.update({leg.line_id for leg in route.legs if leg.line_id != "WALK"})
        days[r["depart_at"][:10]] += 1

    new = conn.execute(
        "SELECT COUNT(*) FROM visits WHERE user_id = ? AND first_visit >= ? AND first_visit < ?", (user_id, start, end)
    ).fetchone()[0]
    miles = conn.execute(
        "SELECT COALESCE(SUM(delta), 0) FROM miles_ledger WHERE user_id = ? AND delta > 0 AND created_at >= ? "
        "AND created_at < ?", (user_id, start, end),
    ).fetchone()[0]
    badge_ids = [b for (b,) in conn.execute(
        "SELECT badge_id FROM badges WHERE user_id = ? AND earned_at >= ? AND earned_at < ? ORDER BY earned_at",
        (user_id, start, end))]
    from agla.badges import all_badges  # local: badges imports the tool layer

    badge_names = {b.badge_id: b.name for b in all_badges()}
    net = load_network()
    fav = lines.most_common(1)[0] if lines else None
    busiest = min(days.items(), key=lambda kv: (-kv[1], kv[0])) if days else None
    start_d = date.fromisoformat(start)
    return WrappedStats(
        month=month,
        month_name=start_d.strftime("%B %Y"),
        first_name=first_name,
        trips=len(rows),
        unique_stations=len(station_visits),
        new_stations=new,
        top_stations=[(get_station(s).name, n) for s, n in sorted(station_visits.items(),
                                                                  key=lambda kv: (-kv[1], kv[0]))[:3]],
        favourite_line=net.lines[fav[0]]["name"] if fav else None,
        favourite_line_trips=fav[1] if fav else 0,
        total_minutes=sum(r["minutes"] for r in rows),
        total_km=round(sum(r["distance_km"] for r in rows), 1),
        total_fare=int(sum(r["fare"] for r in rows)),
        miles_earned=miles,
        badges_earned=[badge_names.get(b, b) for b in badge_ids],
        busiest_day=date.fromisoformat(busiest[0]).strftime("%A %-d %B") if busiest else None,
        busiest_day_trips=busiest[1] if busiest else 0,
        states=sorted({get_station(s).state for s in station_visits}),
    )


def template_text(s: WrappedStats) -> str:
    """Plain recap with no LLM: the fallback when narration fails or invents a number."""
    if not s.trips:
        return f"No metro trips in {s.month_name} yet, {s.first_name}. Agla station is waiting!"
    parts = [f"{s.month_name}: {s.trips} trips, {s.unique_stations} stations ({s.new_stations} new), "
             f"{s.total_km:g} km and {s.total_minutes // 60}h {s.total_minutes % 60}m on the metro."]
    if s.favourite_line:
        parts.append(f"Favourite line: {s.favourite_line}.")
    if s.top_stations:
        parts.append(f"Top station: {s.top_stations[0][0]}.")
    parts.append(f"+{s.miles_earned} Metro Miles.")
    return " ".join(parts)


def save_recap(conn: sqlite3.Connection, user_id: int, stats: WrappedStats, text: str, now: datetime) -> Recap:
    conn.execute(
        "INSERT INTO wrapped_recaps (user_id, month, stats_json, text, created_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(user_id, month) DO UPDATE SET stats_json = excluded.stats_json, text = excluded.text, "
        "created_at = excluded.created_at",
        (user_id, stats.month, json.dumps(stats.to_dict(), ensure_ascii=False), text, now.isoformat()),
    )
    return Recap(stats.month, stats, text, now.isoformat())


def fresh_recap(conn: sqlite3.Connection, user_id: int, stats: WrappedStats) -> Recap | None:
    """The saved recap for this month if its stats still match (no new trips since), else None."""
    recap = get_recap(conn, user_id, stats.month)
    return recap if recap and recap.stats == stats else None


def get_recap(conn: sqlite3.Connection, user_id: int, month: str) -> Recap | None:
    row = conn.execute("SELECT * FROM wrapped_recaps WHERE user_id = ? AND month = ?", (user_id, month)).fetchone()
    return _recap(row) if row else None


def _recap(row: sqlite3.Row) -> Recap:
    d = json.loads(row["stats_json"])
    stats = WrappedStats(**{**d, "top_stations": [tuple(x) for x in d["top_stations"]]})
    return Recap(row["month"], stats, row["text"], row["created_at"])


# --- card --------------------------------------------------------------------------------------------------------

W, H = 1080, 1920
BG, INK, MUTED = "#fbf7f0", "#2b2d42", "#8d8fa3"
PASTELS = ["#cdeac0", "#ffd6a5", "#d7c8f3", "#bde0fe", "#fdffb6", "#ffc8dd"]  # mint, peach, lilac, sky, butter, pink


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def render_card(stats: WrappedStats, text: str = "") -> bytes:
    """Vertical 9:16 share card: big numbers, one-word labels, no prose (the narration goes in the caption)."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((90, 120), "metro wrapped", font=_font(40), fill=MUTED)
    d.text((90, 175), stats.month_name.split()[0], font=_font(120), fill=INK)
    d.text((90, 320), f"{stats.first_name} · {stats.month_name.split()[1]}", font=_font(40), fill=MUTED)

    h, m = divmod(stats.total_minutes, 60)
    tiles = [
        (str(stats.trips), "trips"),
        (str(stats.unique_stations), "stations"),
        (f"{round(stats.total_km)}", "km"),
        (f"{h}h {m}m", "riding"),
        (str(stats.new_stations), "new"),
        (f"{stats.miles_earned}", "miles"),
    ]
    tw, th, gap, top = 435, 250, 30, 440
    for i, (big, label) in enumerate(tiles):
        x, y = 90 + (i % 2) * (tw + gap), top + (i // 2) * (th + gap)
        d.rounded_rectangle([x, y, x + tw, y + th], radius=40, fill=PASTELS[i])
        d.text((x + 40, y + 45), big, font=_font(92 if len(big) <= 5 else 72), fill=INK)
        d.text((x + 40, y + 170), label, font=_font(38), fill=INK)

    y = top + 3 * (th + gap) + 40
    rows = [("line", stats.favourite_line), ("station", stats.top_stations[0][0] if stats.top_stations else None),
            ("busiest", stats.busiest_day)]
    for label, value in rows:
        if value:
            d.text((90, y), label, font=_font(34), fill=MUTED)
            d.text((300, y - 6), value, font=_font(46), fill=INK)
            y += 90
    d.text((90, H - 120), "agla station", font=_font(34), fill=MUTED)
    d.text((W - 90, H - 120), "concept demo", font=_font(30), fill=MUTED, anchor="ra")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
