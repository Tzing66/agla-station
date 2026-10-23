"""Phase 6: Metro Miles rules (data/miles.yaml), badges, redemption."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from agla import tools
from agla.config import IST
from agla.db import connect
from agla.miles import is_off_peak

MON_PEAK = datetime(2026, 10, 26, 9, 30, tzinfo=IST)  # Monday 09:30, inside 08:00-11:00
MON_OFF = datetime(2026, 10, 26, 13, 0, tzinfo=IST)  # Monday 13:00
SAT = datetime(2026, 10, 24, 18, 0, tzinfo=IST)  # weekend: all off-peak


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture
def uid(conn):
    return tools.get_or_create_user(conn, 42, "Ravi", MON_PEAK).user_id


def ride(conn, uid, a, b, when):
    q = tools.quote_trip(conn, uid, a, b, "fastest", when)
    return tools.log_trip(conn, q.quote_id, 42, when)


def reasons(result):
    return [a["reason"] for a in result.hook_results["miles"]["awards"]]


def test_off_peak_windows():
    assert not is_off_peak(MON_PEAK)
    assert is_off_peak(MON_OFF)
    assert not is_off_peak(datetime(2026, 10, 26, 17, 0, tzinfo=IST))  # 17:00 starts the evening peak
    assert is_off_peak(datetime(2026, 10, 26, 20, 0, tzinfo=IST))  # 20:00 is the first off-peak minute
    assert is_off_peak(SAT)


def test_peak_trip_base_plus_first_visits(conn, uid):
    r = ride(conn, uid, "rajiv chowk", "hauz khas", MON_PEAK)  # 10.1 km
    miles = r.hook_results["miles"]
    assert miles["awards"][0] == {"delta": 10, "reason": "10.1 km x 1"}  # round(10.1 * 1)
    assert "2x off-peak" not in reasons(r)
    assert {"delta": 25, "reason": "new station: Rajiv Chowk"} in miles["awards"]
    assert {"delta": 25, "reason": "new station: Hauz Khas"} in miles["awards"]
    assert miles["total"] == 60
    assert tools.get_miles(conn, uid).balance == 60


def test_off_peak_doubles_base_and_repeat_visit_earns_no_bonus(conn, uid):
    ride(conn, uid, "rajiv chowk", "hauz khas", MON_PEAK)
    r = ride(conn, uid, "hauz khas", "rajiv chowk", MON_OFF)
    assert reasons(r) == ["10.1 km x 1", "2x off-peak"]
    assert r.hook_results["miles"]["total"] == 20


def test_streak_bonus_from_third_day_once_per_day(conn, uid):
    day = MON_OFF
    totals = []
    for i in range(4):
        r = ride(conn, uid, "rajiv chowk", "hauz khas", day + timedelta(days=i))
        totals.append([x for x in reasons(r) if "streak" in x])
    assert totals == [[], [], ["3-day streak"], ["4-day streak"]]
    r = ride(conn, uid, "hauz khas", "rajiv chowk", day + timedelta(days=3, hours=2))  # 2nd trip same day
    assert not [x for x in reasons(r) if "streak" in x]


def test_every_ledger_row_has_a_reason(conn, uid):
    ride(conn, uid, "kashmere gate", "pari chowk", SAT)
    rows = conn.execute("SELECT delta, reason FROM miles_ledger").fetchall()
    assert rows and all(r["reason"] and r["delta"] > 0 for r in rows)


def test_badges_first_ride_and_hints(conn, uid):
    r = ride(conn, uid, "rajiv chowk", "hauz khas", MON_PEAK)
    assert [b["badge_id"] for b in r.hook_results["badges"]] == ["first_ride"]
    statuses = {b.badge_id: b for b in tools.get_badges(conn, uid)}
    assert statuses["first_ride"].earned_at and statuses["explorer_10"].earned_at is None
    assert statuses["explorer_10"].hint == "Visit 10 different stations."
    assert "line_collector_rapid" in statuses


def test_night_owl_and_early_bird(conn, uid):
    ride(conn, uid, "rajiv chowk", "hauz khas", datetime(2026, 10, 26, 22, 30, tzinfo=IST))
    ride(conn, uid, "hauz khas", "rajiv chowk", datetime(2026, 10, 27, 6, 15, tzinfo=IST))
    earned = {b.badge_id for b in tools.get_badges(conn, uid) if b.earned_at}
    assert {"night_owl", "early_bird"} <= earned


def test_terminal_to_terminal_and_state_hopper(conn, uid):
    ride(conn, uid, "samaypur badli", "millennium city centre", SAT)  # Yellow end to end; Delhi + Haryana
    ride(conn, uid, "rajiv chowk", "noida city centre", SAT + timedelta(days=2))  # UP within the week
    earned = {b.badge_id for b in tools.get_badges(conn, uid) if b.earned_at}
    assert {"terminal_to_terminal", "state_hopper"} <= earned


def test_redeem_deducts_miles_and_issues_demo_voucher(conn, uid):
    for i in range(3):  # enough miles for a chai (300) under the calibrated rules
        ride(conn, uid, "kashmere gate", "pari chowk", SAT + timedelta(days=7 * i))
        ride(conn, uid, "pari chowk", "samaypur badli", SAT + timedelta(days=7 * i, hours=3))
    balance = tools.get_miles(conn, uid).balance
    chai = next(r for r in tools.list_rewards() if r.reward_id == "chai_kiosk")
    v = tools.redeem_reward(conn, uid, "chai_kiosk", SAT)
    assert v.code.startswith("DEMO-") and "not redeemable" in v.label
    after = tools.get_miles(conn, uid)
    assert after.balance == balance - chai.cost
    assert after.earned_total == balance  # spending doesn't reduce lifetime earnings
    assert after.recent[0].reason == "redeemed: Free chai at a station kiosk"
    assert [x.code for x in tools.list_vouchers(conn, uid)] == [v.code]


def test_redeem_needs_enough_miles(conn, uid):
    with pytest.raises(tools.ToolError, match="Not enough Metro Miles"):
        tools.redeem_reward(conn, uid, "day_pass", SAT)
    assert tools.get_miles(conn, uid).balance == 0  # nothing deducted
