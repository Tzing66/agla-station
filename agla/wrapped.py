"""Metro Wrapped: a rider's month in numbers (computed here), narrated by the LLM, rendered as a card.

Every figure in a recap comes from wrapped_stats(); the narration is checked against it by the number guard.
"""

from __future__ import annotations

import io
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

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


# --- story --------------------------------------------------------------------------------------------------------
# The tap-through Wrapped: one idea per slide, a big figure and one short line saying what it means. Every figure and
# comparison is computed here from the stats and the network (code decides); the page only displays them.


@dataclass(frozen=True)
class Slide(_Base):
    key: str  # stable id: trips, distance, time, busiest, line, station, explorer, miles
    big: str  # the hero figure or name
    label: str  # what the figure is, in a few words
    line: str  # what it means
    colour: str | None = None  # a metro line's own colour, for the line slide


def _line_lengths_km() -> dict[str, float]:
    """End-to-end length of each line: every ride segment counted once, whichever direction it runs."""
    net = load_network()
    seen: set[tuple[str, frozenset[str]]] = set()
    km: Counter[str] = Counter()
    for (a, la), (b, lb), d in net.graph.edges(data=True):
        if d["kind"] == "ride" and la == lb and (key := (la, frozenset((a, b)))) not in seen:
            seen.add(key)
            km[la] += d["km"]
    return dict(km)


def _days_covered(month: str, today: date) -> int:
    start_s, end_s = _month_bounds(month)
    start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
    return max(1, ((min(today, end - timedelta(days=1)) - start).days + 1) if today >= start else (end - start).days)


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def wrapped_story(s: WrappedStats, today: date) -> list[Slide]:
    """The slides for one month, skipping any that would be empty. `today` trims the current month to the days so
    far, so "a week" averages stay honest mid-month."""
    if not s.trips:
        return []
    net = load_network()
    plural = "s" if s.trips != 1 else ""
    slides = []

    weeks = _days_covered(s.month, today) / 7
    per_week = s.trips / weeks
    slides.append(Slide("trips", str(s.trips), f"trip{plural}",
                        f"About {round(per_week)} a week." if weeks >= 1 and per_week >= 1.5
                        else "Every one of them counted on your map."))

    km = round(s.total_km)
    fav_id = next((lid for lid, m in net.lines.items() if m["name"] == s.favourite_line), None)
    length = _line_lengths_km().get(fav_id or "", 0)
    if length and s.total_km >= 0.9 * length:
        n = round(s.total_km / length)
        meaning = f"Like riding the {s.favourite_line} end to end {_times(n)}."
    else:
        meaning = f"{s.total_km / s.trips:.1f} km a trip on average."
    slides.append(Slide("distance", f"{km:,} km", "travelled", meaning))

    h, m = divmod(s.total_minutes, 60)
    avg = round(s.total_minutes / s.trips)
    days = round(s.total_minutes / 1440)
    time_line = f"{avg} minutes a trip on average."
    if days >= 1:
        time_line = f"About {days} full day{'s' if days > 1 else ''} in all, {avg} minutes a trip."
    slides.append(Slide("time", f"{h}h {m}m" if h else f"{m} min", "on the metro", time_line))

    if s.busiest_day and s.busiest_day_trips >= 2:
        slides.append(Slide("busiest", s.busiest_day, "your busiest day", f"{s.busiest_day_trips} trips in one day."))

    if s.favourite_line:
        slides.append(Slide("line", s.favourite_line, "your line",
                            f"{s.favourite_line_trips} of your {s.trips} trips rode it.",
                            colour=net.lines[fav_id]["colour"] if fav_id else None))
    if s.top_stations:
        name, visits = s.top_stations[0]
        slides.append(Slide("station", name, "your station",
                            f"You started, changed or finished here {_times(visits)}."))

    total = len(net.stations)
    explorer = (f"{s.new_stations} of them new to you. The network has {total}."
                if s.new_stations else f"All familiar ones. The network has {total} to explore.")
    slides.append(Slide("explorer", str(s.unique_stations), "stations", explorer))

    if s.miles_earned:
        badges = s.badges_earned
        miles_line = ("Spend them in the Miles tab." if not badges else
                      f"And a new badge: {badges[0]}." if len(badges) == 1 else
                      f"And {len(badges)} new badges, including {badges[0]}.")
        slides.append(Slide("miles", f"+{s.miles_earned:,}", "Metro Miles", miles_line))
    return slides


# --- card --------------------------------------------------------------------------------------------------------

W, H = 1080, 1920
INK, SOFT, PANEL = "#3b1f1a", "#7a4a3c", (255, 250, 244)
SKY = ("#ffd08a", "#f6a6a0")  # marigold to gulabi, top to bottom
FONTS = Path(__file__).resolve().parents[1] / "data" / "fonts"


@cache
def _font(size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    """Baloo 2 (variable weight) for figures and headings; both fonts are OFL and cover Devanagari."""
    f = ImageFont.truetype(str(FONTS / "Baloo2.ttf"), size)
    f.set_variation_by_name(weight)
    return f


@cache
def _body(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / "Mukta-Medium.ttf"), size)


def _fit(d: ImageDraw.ImageDraw, text: str, size: int, width: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    while size > 30 and d.textlength(text, font=_font(size, weight)) > width:
        size -= 4
    return _font(size, weight)


def render_card(stats: WrappedStats, text: str = "", today: date | None = None) -> bytes:
    """Vertical 9:16 share card in warm tones: the month, its biggest figure with what it means, then three panels.
    No narration on the card (that goes in the chat caption); every line comes from wrapped_story()."""
    story = {sl.key: sl for sl in wrapped_story(stats, today or date.max)}  # no date: the whole month
    img = Image.new("RGB", (1, 2))
    img.putpixel((0, 0), ImageColor.getrgb(SKY[0]))
    img.putpixel((0, 1), ImageColor.getrgb(SKY[1]))
    img = img.resize((W, H), Image.Resampling.BILINEAR)
    d = ImageDraw.Draw(img, "RGBA")
    x, inner = 96, W - 2 * 96

    d.text((x, 110), "metro wrapped", font=_body(40), fill=SOFT)
    month, year = stats.month_name.split()
    d.text((x, 150), month, font=_fit(d, month, 170, inner, "ExtraBold"), fill=INK)
    d.text((x, 345), f"{stats.first_name}, {year}", font=_body(44), fill=SOFT)

    if not story:
        d.text((x, 520), "No trips this month yet.", font=_font(64, "SemiBold"), fill=INK)
    else:
        hero = story["distance"]
        d.text((x, 470), hero.big, font=_fit(d, hero.big, 210, inner, "ExtraBold"), fill=INK)
        _wrap(d, (x, 710), hero.line, _body(46), inner, SOFT)

        y = 880
        for key in ("trips", "time", "line" if "line" in story else "explorer"):
            sl = story[key]
            d.rounded_rectangle([x - 24, y, W - x + 24, y + 250], radius=44, fill=(*PANEL, 205))
            big_font = _fit(d, sl.big, 96, inner - 40, "Bold")
            d.text((x + 16, y + 26), sl.big, font=big_font, fill=sl.colour or INK)
            label_x = x + 16 + d.textlength(sl.big, font=big_font) + 18
            if label_x < W - x - 200:
                d.text((label_x, y + 70), sl.label, font=_body(40), fill=SOFT)
            _wrap(d, (x + 16, y + 150), sl.line, _body(38), inner - 40, SOFT, max_lines=2)
            y += 280

    d.text((x, H - 120), "agla station", font=_font(40, "Bold"), fill=INK)
    d.text((W - x, H - 112), "concept demo", font=_body(32), fill=SOFT, anchor="ra")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _wrap(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.FreeTypeFont, width: int,
          fill: str, max_lines: int = 3) -> None:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if d.textlength(trial, font=font) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    x, y = xy
    for ln in lines[:max_lines]:
        d.text((x, y), ln, font=font, fill=fill)
        y += int(font.size * 1.25)
