"""Seed a realistic month of trips for a demo rider (or your own Telegram account), through the real pipeline:
quote_trip -> log_trip -> post-trip hooks, so every mile and badge is computed exactly as it would be live.

    uv run python -m scripts.seed_demo                      # demo rider (agla-mcp's default user)
    uv run python -m scripts.seed_demo --telegram-id 123    # your account, to demo on your phone
    uv run python -m scripts.seed_demo --reset              # wipe that rider's trips/miles/badges first

The month: Mon-Thu commute Noida Sector 18 <-> Cyber City (UP <-> Haryana, mostly peak hours), Fridays working
from home, weekend outings across Delhi, Haryana and UP, one late night and one early airport run.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import date, datetime, time, timedelta

from agla import tools
from agla.config import IST

MONTH_START, MONTH_END = date(2026, 10, 1), date(2026, 10, 22)
HOME, OFFICE = "noida sector 18", "cyber city"

# (date, time, origin, destination) for weekends and one-offs
OUTINGS = [
    ("2026-10-03", "11:10", HOME, "chandni chowk"),
    ("2026-10-03", "17:40", "chandni chowk", "rajiv chowk"),
    ("2026-10-03", "21:15", "rajiv chowk", HOME),
    ("2026-10-04", "10:30", HOME, "qutab minar"),
    ("2026-10-04", "16:00", "qutab minar", "hauz khas"),
    ("2026-10-04", "22:40", "hauz khas", HOME),  # night owl
    ("2026-10-10", "12:00", HOME, "pari chowk"),  # Aqua Line via the Sector 52 <-> 51 walk
    ("2026-10-10", "18:30", "pari chowk", HOME),
    ("2026-10-11", "06:20", HOME, "airport t3"),  # early bird, Airport Express
    ("2026-10-11", "14:00", "delhi aerocity", "dwarka sector 21"),
    ("2026-10-11", "19:10", "dwarka sector 21", HOME),
    ("2026-10-17", "11:30", HOME, "kashmere gate"),
    ("2026-10-17", "15:45", "kashmere gate", "lal quila"),
    ("2026-10-17", "20:30", "lal quila", HOME),
    ("2026-10-18", "13:00", HOME, "botanical garden"),
    ("2026-10-18", "13:40", "botanical garden", "kalkaji mandir"),
    ("2026-10-18", "18:20", "kalkaji mandir", "nehru place"),
    ("2026-10-18", "19:00", "nehru place", HOME),
]


def plan() -> list[tuple[datetime, str, str]]:
    trips = []
    day = MONTH_START
    while day <= MONTH_END:
        if day.weekday() <= 3:  # Mon-Thu commute; Fridays WFH
            leave_home = time(8, 40) if day.day % 4 else time(11, 20)  # some late (off-peak) starts
            leave_work = time(18, 45) if day.day % 3 else time(20, 15)  # some late evenings
            trips.append((datetime.combine(day, leave_home, IST), HOME, OFFICE))
            trips.append((datetime.combine(day, leave_work, IST), OFFICE, HOME))
        day += timedelta(days=1)
    trips += [(datetime.fromisoformat(f"{d}T{t}").replace(tzinfo=IST), a, b) for d, t, a, b in OUTINGS]
    return sorted(trips)


def reset(conn: sqlite3.Connection, user_id: int) -> None:
    for table in ("miles_ledger", "vouchers", "badges", "visits", "safety_checks", "shares", "wrapped_recaps"):
        conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM trips WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM quotes WHERE user_id = ?", (user_id,))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--telegram-id", type=int, default=tools.DEMO_TELEGRAM_ID)
    p.add_argument("--name", default="Aarav")
    p.add_argument("--reset", action="store_true", help="delete this rider's existing trips, miles and badges first")
    args = p.parse_args()

    conn = tools.open_database()
    user = tools.get_or_create_user(conn, args.telegram_id, args.name, datetime.combine(MONTH_START, time(8), IST))
    existing = conn.execute("SELECT COUNT(*) FROM trips WHERE user_id = ?", (user.user_id,)).fetchone()[0]
    if existing and not args.reset:
        raise SystemExit(f"Rider already has {existing} trips; rerun with --reset to replace them.")
    if args.reset:
        reset(conn, user.user_id)

    for when, a, b in plan():
        quote = tools.quote_trip(conn, user.user_id, a, b, "fastest", when)
        tools.log_trip(conn, quote.quote_id, args.telegram_id, when)

    stats = tools.get_stats(conn, user.user_id)
    miles = tools.get_miles(conn, user.user_id, recent=0)
    badges = [b for b in tools.get_badges(conn, user.user_id) if b.earned_at]
    print(f"Seeded {stats.trips} trips for {user.first_name} (telegram_id {args.telegram_id}): "
          f"{stats.unique_stations} stations, {stats.total_km} km, Rs {stats.total_fare}, "
          f"states {stats.states_visited}")
    print(f"Metro Miles: {miles.balance}")
    print(f"Badges ({len(badges)}): {', '.join(b.name for b in badges)}")


if __name__ == "__main__":
    main()
