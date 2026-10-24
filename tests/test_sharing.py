"""Phase 8: timetable position estimates, share links and "I've reached"."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from agla import tools
from agla.config import IST
from agla.db import connect

T0 = datetime(2026, 10, 26, 13, 0, tzinfo=IST)  # Kashmere Gate -> Pari Chowk departs here (89 min)
RIDER, FRIEND = 42, 77


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture
def trip(conn):
    uid = tools.get_or_create_user(conn, RIDER, "Meera Sharma", T0).user_id
    q = tools.quote_trip(conn, uid, "kashmere gate", "pari chowk", "fastest", T0)
    return tools.log_trip(conn, q.quote_id, RIDER, T0).trip


# --- estimate_position: one fixed timestamp per state ---


@pytest.mark.parametrize(("minutes", "state", "text"), [
    (-5, "not_started", "Starting soon from Kashmere Gate"),
    (3.5, "riding", "Between Lal Quila and Jama Masjid"),  # Violet: Lal Quila 2.8, Jama Masjid 4.4
    (13, "changing", "Changing at Mandi House to the Blue Line"),  # Violet ends 10.4, Blue starts 16.4
    (53, "walking", "Walking from Noida Sector 52 to Noida Sector 51"),  # walk 50.8 - 56.8
    (95, "arrived", "Should have arrived at Pari Chowk"),
])
def test_estimate_position_states(trip, minutes, state, text):
    pos = tools.estimate_position(trip, at(minutes))
    assert (pos.state, pos.text) == (state, text)


def test_position_progress_and_eta(trip):
    mid = tools.estimate_position(trip, at(44.4))
    assert 45 <= mid.progress_pct <= 55
    assert mid.minutes_left == 45 and mid.line_name == "Blue Line"
    assert "kashmere_gate" in mid.reached_ids and "pari_chowk" not in mid.reached_ids
    assert tools.estimate_position(trip, at(-5)).progress_pct == 0
    assert tools.estimate_position(trip, at(200)).progress_pct == 100


# --- share links ---


def test_share_page_shows_first_name_only_and_expires(conn, trip):
    token = tools.create_share(conn, trip.trip_id, RIDER, T0)
    assert tools.create_share(conn, trip.trip_id, RIDER, at(1)) == token  # one link per trip
    view = tools.get_share_view(conn, token, at(20))
    assert view.first_name == "Meera" and "Sharma" not in str(view.to_dict())
    assert view.status == "on_the_way" and view.from_name == "Kashmere Gate"
    assert tools.get_share_view(conn, token, at(89 + 16)).status == "overdue"
    assert tools.get_share_view(conn, token, at(89 + 119)) is not None
    assert tools.get_share_view(conn, token, at(89 + 121)) is None  # ETA + 2h
    assert tools.get_share_view(conn, "not-a-token", at(1)) is None


def test_only_the_owner_can_share(conn, trip):
    tools.get_or_create_user(conn, FRIEND, "Ravi", T0)
    with pytest.raises(tools.ToolError):
        tools.create_share(conn, trip.trip_id, FRIEND, T0)


def test_arrival_marks_share_and_shortens_expiry(conn, trip):
    token = tools.create_share(conn, trip.trip_id, RIDER, T0)
    result = tools.confirm_arrival(conn, trip.trip_id, RIDER, at(85))
    assert result["miles"] == 10 and not result["already"] and result["share_token"] == token
    view = tools.get_share_view(conn, token, at(90))
    assert view.status == "arrived" and all(reached for _, reached, _ in view.stations)
    assert tools.get_share_view(conn, token, at(85 + 31)) is None  # 30 min after arrival
    assert tools.confirm_arrival(conn, trip.trip_id, RIDER, at(86))["already"]


# --- I've reached ---


def test_reached_marks_trip_awards_miles_once_and_returns_a_message(conn, trip):
    res = tools.confirm_arrival(conn, trip.trip_id, RIDER, at(85))
    assert res["miles"] == 10 and not res["already"]
    assert res["message"] == "✅ Meera has reached Pari Chowk (2:25 PM)."
    again = tools.confirm_arrival(conn, trip.trip_id, RIDER, at(90))
    assert again == {**res, "already": True, "miles": 0}  # same time and message, no double miles


def test_reached_works_without_a_share_and_a_later_share_shows_arrived(conn, trip):
    tools.confirm_arrival(conn, trip.trip_id, RIDER, at(85))
    token = tools.create_share(conn, trip.trip_id, RIDER, at(86))
    view = tools.get_share_view(conn, token, at(87))
    assert view.status == "arrived" and view.arrived_hm == "2:25 PM"
    assert tools.get_share_view(conn, token, at(85 + 31)) is None  # 30 min after arrival


def test_only_the_traveller_can_mark_arrival(conn, trip):
    tools.get_or_create_user(conn, FRIEND, "Ravi", T0)
    with pytest.raises(tools.ToolError, match="someone else"):
        tools.confirm_arrival(conn, trip.trip_id, FRIEND, at(85))


def test_safe_and_sound_badge_after_five_arrivals(conn, trip):
    uid = tools.find_user_by_telegram_id(conn, RIDER).user_id
    tools.confirm_arrival(conn, trip.trip_id, RIDER, at(85))
    for day in range(1, 5):
        when = T0 + timedelta(days=day)
        q = tools.quote_trip(conn, uid, "rajiv chowk", "hauz khas", "fastest", when)
        r = tools.log_trip(conn, q.quote_id, RIDER, when)
        tools.confirm_arrival(conn, r.trip.trip_id, RIDER, when + timedelta(minutes=20))
    q = tools.quote_trip(conn, uid, "hauz khas", "rajiv chowk", "fastest", T0 + timedelta(days=6))
    tools.log_trip(conn, q.quote_id, RIDER, T0 + timedelta(days=6))  # badges are evaluated after each trip
    assert {b.badge_id for b in tools.get_badges(conn, uid) if b.earned_at} >= {"safe_and_sound"}



# review finding: sharing a finished journey handed out a dead link
def test_cannot_share_a_journey_that_is_over(conn, trip):
    with pytest.raises(tools.ToolError, match="journey is over"):
        tools.create_share(conn, trip.trip_id, RIDER, at(89 + 121))
    token = tools.create_share(conn, trip.trip_id, RIDER, at(10))
    assert tools.create_share(conn, trip.trip_id, RIDER, at(20)) == token
    with pytest.raises(tools.ToolError, match="journey is over"):
        tools.create_share(conn, trip.trip_id, RIDER, at(89 + 121))



# review finding: "I've reached" could be tapped straight away to farm miles
def test_reached_after_half_the_trip_earns_miles(conn, trip):
    assert tools.confirm_arrival(conn, trip.trip_id, RIDER, at(45))["miles"] == 10  # 89-min trip: half is ~44.5


def test_early_reached_asks_are_you_sure_with_the_eta(conn, trip):
    question = r"Are you sure you've reached Pari Chowk\? Your ETA is \d+:\d\d [AP]M\."
    with pytest.raises(tools.ArrivalTooEarly, match=question) as e:
        tools.confirm_arrival(conn, trip.trip_id, RIDER, at(30))
    assert e.value.destination == "Pari Chowk"
    assert isinstance(e.value, tools.ToolError)  # front ends that only know ToolError still show the question


def test_confirmed_early_arrival_counts_but_earns_no_miles(conn, trip):
    token = tools.create_share(conn, trip.trip_id, RIDER, at(5))
    res = tools.confirm_arrival(conn, trip.trip_id, RIDER, at(10), confirmed_early=True)
    assert not res["already"] and res["miles"] == 0 and "has reached" in res["message"]
    assert tools.get_share_view(conn, token, at(11)).status == "arrived"
    assert tools.confirm_arrival(conn, trip.trip_id, RIDER, at(60))["already"]  # no second chance at the bonus
