"""Metro Miles: deterministic earning rules (data/miles.yaml), the ledger, and demo redemption.

Concept demo only. Balance = SUM(delta) over miles_ledger; redemptions are negative rows.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import date, datetime, time, timedelta
from functools import cache
from pathlib import Path

import yaml

from agla.db import tx
from agla.tools.stations import get_station
from agla.tools.trips import visited_station_ids
from agla.tools.types import MilesAward, MilesSummary, Reward, ToolError, Trip, Voucher

ROOT = Path(__file__).resolve().parents[1]


@cache
def rules() -> dict:
    return yaml.safe_load((ROOT / "data" / "miles.yaml").read_text())


@cache
def _rewards() -> dict[str, Reward]:
    raw = yaml.safe_load((ROOT / "data" / "rewards.yaml").read_text())["rewards"]
    return {r["id"]: Reward(r["id"], r["name"], int(r["cost"])) for r in raw}


def is_off_peak(when: datetime) -> bool:
    if when.weekday() >= 5:
        return True
    t = when.time()
    for start, end in rules()["off_peak"]["weekday_peaks"]:
        if time.fromisoformat(start) <= t < time.fromisoformat(end):
            return False
    return True


def trip_awards(conn: sqlite3.Connection, trip: Trip, now: datetime) -> list[tuple[int, str]]:
    """The (delta, reason) rows a freshly logged trip earns. Pure over the DB state; doesn't write."""
    r = rules()
    depart = datetime.fromisoformat(trip.depart_at)
    awards: list[tuple[int, str]] = []

    base = round(trip.route.distance_km * r["base_per_km"])
    awards.append((base, f"{trip.route.distance_km} km x {r['base_per_km']}"))
    if is_off_peak(depart):
        mult = r["off_peak"]["multiplier"]
        awards.append((base * (mult - 1), f"{mult}x off-peak"))

    # visits were recorded just before the hooks ran, stamped with this trip's time
    for sid in visited_station_ids(trip):
        row = conn.execute(
            "SELECT first_visit, count FROM visits WHERE user_id = ? AND station_id = ?", (trip.user_id, sid)
        ).fetchone()
        if row and row["count"] == 1 and row["first_visit"] == now.isoformat():
            awards.append((r["first_visit_bonus"], f"new station: {get_station(sid).name}"))

    streak = streak_days(conn, trip.user_id, depart.date())
    first_today = conn.execute(
        "SELECT COUNT(*) FROM trips WHERE user_id = ? AND substr(depart_at, 1, 10) = ?",
        (trip.user_id, depart.date().isoformat()),
    ).fetchone()[0] == 1
    if first_today and streak >= r["streak"]["from_day"]:
        awards.append((r["streak"]["bonus"], f"{streak}-day streak"))
    return awards


def streak_days(conn: sqlite3.Connection, user_id: int, day: date) -> int:
    """Consecutive days with at least one trip, ending on `day`."""
    days = {
        date.fromisoformat(d)
        for (d,) in conn.execute("SELECT DISTINCT substr(depart_at, 1, 10) FROM trips WHERE user_id = ?", (user_id,))
    }
    n = 0
    while day - timedelta(days=n) in days:
        n += 1
    return n


def award_trip_miles(conn: sqlite3.Connection, trip: Trip, now: datetime) -> dict:
    """Post-trip hook. Returns {"total": int, "awards": [{"delta", "reason"}]} for the bot to show."""
    awards = trip_awards(conn, trip, now)
    conn.executemany(
        "INSERT INTO miles_ledger (user_id, trip_id, delta, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        [(trip.user_id, trip.trip_id, d, reason, now.isoformat()) for d, reason in awards if d],
    )
    return {"total": sum(d for d, _ in awards), "awards": [{"delta": d, "reason": r} for d, r in awards if d]}


def award_arrival(conn: sqlite3.Connection, user_id: int, trip_id: int, now: datetime) -> int:
    bonus = rules()["arrival_bonus"]
    conn.execute(
        "INSERT INTO miles_ledger (user_id, trip_id, delta, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, trip_id, bonus, "confirmed arrival", now.isoformat()),
    )
    return bonus


def get_miles(conn: sqlite3.Connection, user_id: int, recent: int = 8) -> MilesSummary:
    agg = conn.execute(
        "SELECT COALESCE(SUM(delta), 0) AS bal, COALESCE(SUM(CASE WHEN delta > 0 THEN delta END), 0) AS earned "
        "FROM miles_ledger WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    rows = conn.execute(
        "SELECT delta, reason, created_at, trip_id FROM miles_ledger WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, recent),
    )
    return MilesSummary(
        balance=agg["bal"],
        earned_total=agg["earned"],
        recent=[MilesAward(r["delta"], r["reason"], r["created_at"], r["trip_id"]) for r in rows],
    )


def list_rewards() -> list[Reward]:
    return sorted(_rewards().values(), key=lambda r: r.cost)


def redeem_reward(conn: sqlite3.Connection, user_id: int, reward_id: str, now: datetime) -> Voucher:
    reward = _rewards().get(reward_id)
    if reward is None:
        raise ToolError(f"Unknown reward {reward_id!r}.")
    with tx(conn):
        balance = get_miles(conn, user_id, recent=0).balance
        if balance < reward.cost:
            raise ToolError(f"Not enough Metro Miles: {reward.name} needs {reward.cost}, you have {balance}.")
        code = "DEMO-" + secrets.token_hex(3).upper()
        conn.execute(
            "INSERT INTO miles_ledger (user_id, trip_id, delta, reason, created_at) VALUES (?, NULL, ?, ?, ?)",
            (user_id, -reward.cost, f"redeemed: {reward.name}", now.isoformat()),
        )
        conn.execute(
            "INSERT INTO vouchers (user_id, reward_id, miles_spent, code, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, reward.reward_id, reward.cost, code, now.isoformat()),
        )
    return Voucher(code, reward.reward_id, reward.name, reward.cost, now.isoformat())


def list_vouchers(conn: sqlite3.Connection, user_id: int) -> list[Voucher]:
    rows = conn.execute(
        "SELECT reward_id, miles_spent, code, created_at FROM vouchers WHERE user_id = ? ORDER BY id DESC", (user_id,)
    )
    names = {rid: r.name for rid, r in _rewards().items()}
    return [Voucher(r["code"], r["reward_id"], names.get(r["reward_id"], r["reward_id"]), r["miles_spent"],
                    r["created_at"]) for r in rows]
