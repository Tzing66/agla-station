"""Phase 7: Metro Wrapped stats, recap storage, skill-driven narration with the number guard, and the card."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace as NS

import pytest

from agla import tools
from agla.config import IST
from agla.db import connect
from agla.llm import narrate_wrapped, wrapped_facts, wrapped_system_prompt

OCT_A = datetime(2026, 10, 3, 13, 0, tzinfo=IST)  # Saturday
OCT_B = datetime(2026, 10, 5, 9, 0, tzinfo=IST)  # Monday
SEP = datetime(2026, 9, 30, 23, 30, tzinfo=IST)  # previous month, must not count


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture
def uid(conn):
    uid = tools.get_or_create_user(conn, 9, "Meera", SEP).user_id
    for a, b, when in [("rajiv chowk", "hauz khas", SEP), ("rajiv chowk", "hauz khas", OCT_A),
                       ("hauz khas", "botanical garden", OCT_B)]:
        q = tools.quote_trip(conn, uid, a, b, "fastest", when)
        tools.log_trip(conn, q.quote_id, 9, when)
    return uid


def test_month_stats(conn, uid):
    s = tools.wrapped_stats(conn, uid, "2026-10")
    assert (s.month_name, s.first_name, s.trips) == ("October 2026", "Meera", 2)
    assert s.unique_stations == 3  # Rajiv Chowk, Hauz Khas, Botanical Garden
    assert s.new_stations == 1  # Rajiv Chowk and Hauz Khas were first visited in September
    assert s.top_stations[0] == ("Hauz Khas", 2)
    assert s.total_fare == 32 + 43
    assert s.busiest_day == "Saturday 3 October" and s.busiest_day_trips == 1  # ties -> earliest
    assert "Delhi" in s.states and "UP" in s.states
    assert s.miles_earned == sum(a.delta for a in tools.get_miles(conn, uid, recent=50).recent
                                 if a.created_at.startswith("2026-10"))


def test_empty_and_bad_months(conn, uid):
    assert tools.wrapped_stats(conn, uid, "2026-08").trips == 0
    assert "No metro trips" in tools.template_text(tools.wrapped_stats(conn, uid, "2026-08"))
    with pytest.raises(tools.ToolError):
        tools.wrapped_stats(conn, uid, "October")


def test_recap_is_reused_until_stats_change(conn, uid):
    s = tools.wrapped_stats(conn, uid, "2026-10")
    assert tools.fresh_recap(conn, uid, s) is None
    tools.save_recap(conn, uid, s, "great month", OCT_B)
    assert tools.fresh_recap(conn, uid, s).text == "great month"
    q = tools.quote_trip(conn, uid, "botanical garden", "rajiv chowk", "fastest", OCT_B.replace(hour=19))
    tools.log_trip(conn, q.quote_id, 9, OCT_B.replace(hour=19))
    assert tools.fresh_recap(conn, uid, tools.wrapped_stats(conn, uid, "2026-10")) is None
    assert tools.get_recap(conn, uid, "2026-10").text == "great month"


def test_runtime_prompt_is_the_voice_skill():
    prompt = wrapped_system_prompt()
    assert prompt.startswith("# Metro Wrapped voice") and "name: metro-wrapped-voice" not in prompt
    assert "Never invent a number" in prompt


class FakeClient:
    def __init__(self, text):
        self.text, self.requests = text, []
        self.beta = NS(messages=NS(create=self.create))

    async def create(self, **kw):
        self.requests.append(kw)
        return NS(content=[NS(type="text", text=self.text)], stop_reason="end_turn")


def narrate(conn, uid, text):
    s = tools.wrapped_stats(conn, uid, "2026-10")
    client = FakeClient(text)
    return asyncio.run(narrate_wrapped(client, "claude-sonnet-5-5", s, "en", "TEMPLATE")), client, s


def test_narration_passes_when_numbers_come_from_the_facts(conn, uid):
    (text, guarded), client, s = narrate(conn, uid, "Meera, 2 trips and 1 new station. Hauz Khas twice!")
    assert not guarded and text.startswith("Meera")
    assert client.requests[0]["system"][0]["text"] == wrapped_system_prompt()
    assert '"time_on_metro"' in client.requests[0]["messages"][0]["content"]


def test_invented_number_or_long_text_falls_back_to_template(conn, uid):
    (text, guarded), _, _ = narrate(conn, uid, "Meera, 7 trips this month!")
    assert guarded and text == "TEMPLATE"
    (text, guarded), _, _ = narrate(conn, uid, "word " * 80)
    assert guarded and text == "TEMPLATE"


def test_facts_include_derived_phrasings(conn, uid):
    f = wrapped_facts(tools.wrapped_stats(conn, uid, "2026-10"))
    assert f["time_on_metro"].endswith("m") and isinstance(f["km_rounded"], int)


def test_card_is_a_png(conn, uid):
    s = tools.wrapped_stats(conn, uid, "2026-10")
    assert tools.render_card(s, tools.template_text(s)).startswith(b"\x89PNG")


# --- story ---------------------------------------------------------------------------------------------------------


def test_story_figures_all_come_from_the_stats(conn, uid):
    from datetime import date

    s = tools.wrapped_stats(conn, uid, "2026-10")
    slides = {sl.key: sl for sl in tools.wrapped_story(s, date(2026, 10, 31))}
    assert list(slides)[0] == "trips" and slides["trips"].big == str(s.trips)
    assert slides["distance"].big == f"{round(s.total_km):,} km"
    assert slides["line"].big == s.favourite_line and slides["line"].colour.startswith("#")
    assert slides["line"].line == f"{s.favourite_line_trips} of your {s.trips} trips rode it."
    assert slides["explorer"].big == str(s.unique_stations)
    assert "busiest" not in slides  # one trip a day: not worth a slide
    assert all(sl.line.endswith(".") and len(sl.line) <= 90 for sl in slides.values())  # one short sentence each


def test_story_compares_distance_with_a_real_line(conn, uid):
    from agla.wrapped import _line_lengths_km

    lengths = _line_lengths_km()
    assert 50 < lengths["DMRC_BLUE"] < 62  # Dwarka Sector 21 to Noida Electronic City is about 56 km
    long = tools.WrappedStats(**{**tools.wrapped_stats(conn, uid, "2026-10").to_dict(), "favourite_line": "Blue Line",
                                 "total_km": round(lengths["DMRC_BLUE"] * 3, 1)})
    distance = next(sl for sl in tools.wrapped_story(long, long_ago()) if sl.key == "distance")
    assert distance.line == "Like riding the Blue Line end to end 3 times."


def long_ago():
    from datetime import date

    return date.max


def test_story_per_week_average_counts_only_days_so_far(conn, uid):
    from datetime import date

    s = tools.wrapped_stats(conn, uid, "2026-10")
    busy = tools.WrappedStats(**{**s.to_dict(), "trips": 14})
    mid_month = {sl.key: sl for sl in tools.wrapped_story(busy, date(2026, 10, 7))}
    assert mid_month["trips"].line == "About 14 a week."  # 14 trips in the first 7 days
    whole = {sl.key: sl for sl in tools.wrapped_story(busy, date.max)}
    assert whole["trips"].line == "About 3 a week."  # 14 over 31 days


def test_no_trips_no_story(conn, uid):
    assert tools.wrapped_story(tools.wrapped_stats(conn, uid, "2026-08"), long_ago()) == []
    assert tools.render_card(tools.wrapped_stats(conn, uid, "2026-08")).startswith(b"\x89PNG")
