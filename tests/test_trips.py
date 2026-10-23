"""Phase 4 tool layer: users, quotes, UPI links, trip logging, visits, stats, post-trip hooks."""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from agla import tools
from agla.config import IST
from agla.db import connect
from agla.tools import trips as trips_mod

MON = datetime(2026, 10, 26, 9, 30, tzinfo=IST)


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture
def rider(conn):
    return tools.get_or_create_user(conn, 111, "Ravi Kumar", MON)


def test_user_first_name_only_and_upsert(conn):
    u = tools.get_or_create_user(conn, 5, "Asha Kumari Rao", MON)
    assert u.first_name == "Asha"
    again = tools.get_or_create_user(conn, 5, None, MON)
    assert again.user_id == u.user_id and again.first_name == "Asha"


def test_quote_stores_route_and_official_fare(conn, rider):
    q = tools.quote_trip(conn, rider.user_id, "RC", "hkv", "fastest", MON)
    assert q.fare.total == 32
    stored = tools.get_quote(conn, q.quote_id)
    assert stored.route == q.route and stored.fare == q.fare
    assert len(f"paid:{q.quote_id}".encode()) <= 64  # Telegram callback_data limit


def test_quote_ambiguous_station_raises(conn, rider):
    with pytest.raises(tools.ToolError, match="ambiguous"):
        tools.quote_trip(conn, rider.user_id, "dwarka", "rajiv chowk", "fastest", MON)


def test_payment_link_amount_comes_from_quote(conn, rider):
    q = tools.quote_trip(conn, rider.user_id, "rajiv chowk", "cyber city", "fastest", MON)
    pay = tools.make_payment_link(q, "demo@upi", "Demo Payee")
    url = urlparse(pay.upi_uri)
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.scheme == "upi" and url.netloc == "pay"
    assert params == {"pa": "demo@upi", "pn": "Demo Payee", "am": "74.00", "cu": "INR",
                      "tn": "Agla Station Rajiv Chowk-Cyber City"}
    assert pay.qr_png.startswith(b"\x89PNG")


def test_log_trip_records_trip_visits_and_ticket(conn, rider):
    q = tools.quote_trip(conn, rider.user_id, "kashmere gate", "pari chowk", "fastest", MON)
    paid_at = MON + timedelta(minutes=3)
    r = tools.log_trip(conn, q.quote_id, 111, paid_at)
    assert r.trip.ticket_id.startswith("AGL-")
    assert datetime.fromisoformat(r.trip.eta) == paid_at + timedelta(minutes=q.route.minutes)
    # visit rule: origin, interchanges (both ends of the Sector 52 <-> 51 walk), destination
    assert r.new_visits == ["Kashmere Gate", "Mandi House", "Noida Sector 52", "Noida Sector 51", "Pari Chowk"]
    assert r.ticket_png.startswith(b"\x89PNG")
    assert tools.get_trip(conn, r.trip.trip_id) == r.trip


def test_log_trip_is_idempotent(conn, rider):
    q = tools.quote_trip(conn, rider.user_id, "rajiv chowk", "hauz khas", "fastest", MON)
    first = tools.log_trip(conn, q.quote_id, 111, MON)
    second = tools.log_trip(conn, q.quote_id, 111, MON + timedelta(minutes=1))
    assert second.already_logged and second.trip.trip_id == first.trip.trip_id
    assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 1


def test_log_trip_rejects_other_users_and_expired_quotes(conn, rider):
    q = tools.quote_trip(conn, rider.user_id, "rajiv chowk", "hauz khas", "fastest", MON)
    with pytest.raises(tools.ToolError, match="someone else"):
        tools.log_trip(conn, q.quote_id, 999, MON)
    with pytest.raises(tools.ToolError, match="expired"):
        tools.log_trip(conn, q.quote_id, 111, MON + timedelta(minutes=31))


def test_repeat_visits_count_and_stats(conn, rider):
    for when in (MON, MON + timedelta(hours=1)):
        q = tools.quote_trip(conn, rider.user_id, "rajiv chowk", "hauz khas", "fastest", when)
        r = tools.log_trip(conn, q.quote_id, 111, when)
    assert r.new_visits == []  # second time round, nothing is new
    s = tools.get_stats(conn, rider.user_id)
    assert (s.trips, s.unique_stations, s.total_fare) == (2, 2, 64)
    assert s.favourite_line == "Yellow Line"
    assert s.top_stations[0][1] == 2
    assert [v.count for v in tools.get_visited_stations(conn, rider.user_id)] == [2, 2]


def test_post_trip_hooks_plug_in_without_bot_changes(conn, rider, monkeypatch):
    monkeypatch.setattr(trips_mod, "_HOOKS", [])
    tools.register_post_trip_hook("echo", lambda c, trip, now: {"km": trip.route.distance_km})
    q = tools.quote_trip(conn, rider.user_id, "rajiv chowk", "hauz khas", "fastest", MON)
    r = tools.log_trip(conn, q.quote_id, 111, MON)
    assert r.hook_results == {"echo": {"km": q.route.distance_km}}


def test_language_setting_and_validation(conn, rider):
    assert rider.language == "en"
    assert tools.set_language(conn, rider.user_id, "hinglish").language == "hinglish"
    with pytest.raises(tools.ToolError):
        tools.set_language(conn, rider.user_id, "tamil")


def test_migration_adds_language_to_v1_database(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE NOT NULL, first_name TEXT, "
                "safety_on INTEGER NOT NULL DEFAULT 0, demo_fast INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
    old.execute("INSERT INTO users (telegram_id, first_name, created_at) VALUES (7, 'Old', 'x')")
    old.commit()
    old.close()
    conn = connect(path)
    assert tools.find_user_by_telegram_id(conn, 7).language == "en"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
