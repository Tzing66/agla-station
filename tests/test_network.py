"""Phase 2: station search, routing and fares over the built network.

Expected fares are official DMRC journey-planner / NMRC fare-table values fetched 2026-10-23.
"""

from __future__ import annotations

from datetime import date

import pytest

from agla.tools.fares import day_type, get_fare
from agla.tools.routing import plan_route
from agla.tools.stations import search_station
from agla.tools.types import ToolError

MONDAY = date(2026, 10, 26)
SUNDAY = date(2026, 10, 25)


def lines_of(route) -> list[str]:
    return [leg.line_id for leg in route.legs]


# --- routes (plan.md asks for 6, incl. 2 interchanges, Noida Aqua, Rapid Metro) ---


def test_direct_route_rajiv_chowk_hauz_khas():
    r = plan_route("rajiv_chowk", "hauz_khas")
    assert lines_of(r) == ["DMRC_YELLOW"]
    assert r.interchange_ids == []
    assert 17 <= r.minutes <= 22  # DMRC planner: 0:19:24
    assert r.stops[0].station_id == "rajiv_chowk" and r.stops[-1].station_id == "hauz_khas"
    assert len(r.stops) == 10
    assert [s.cum_minutes for s in r.stops] == sorted(s.cum_minutes for s in r.stops)


def test_two_interchanges_botanical_garden_to_cyber_city():
    r = plan_route("botanical_garden", "cyber_city")
    assert r.interchange_ids == ["hauz_khas", "sikanderpur"]
    assert lines_of(r) == ["DMRC_MAGENTA", "DMRC_YELLOW", "RAPID"]


def test_into_noida_aqua_line_via_sector_52_walk():
    r = plan_route("kashmere_gate", "pari_chowk")
    assert "WALK" in lines_of(r)
    assert lines_of(r)[-1] == "NMRC_AQUA"
    walk = next(leg for leg in r.legs if leg.line_id == "WALK")
    assert (walk.from_id, walk.to_id) == ("noida_sector_52", "noida_sector_51")
    # the walk is one interchange, but both stations count as interchange stops (visit rule)
    assert r.interchange_ids.count("noida_sector_52") == 1 and "noida_sector_51" not in r.interchange_ids
    assert {s.station_id for s in r.stops if s.is_interchange} >= {"noida_sector_52", "noida_sector_51"}


def test_into_rapid_metro_rajiv_chowk_to_cyber_city():
    r = plan_route("rajiv_chowk", "cyber_city")
    assert lines_of(r) == ["DMRC_YELLOW", "RAPID"]
    assert r.interchange_ids == ["sikanderpur"]


def test_rapid_metro_loop_is_one_way():
    # Cyber City -> Belvedere Towers has to go round the loop (DMRC planner: 5 stations, 0:06:51)
    r = plan_route("cyber_city", "belvedere_towers")
    assert r.legs[0].station_ids == ["cyber_city", "moulsari_avenue", "phase_3", "phase_2", "belvedere_towers"]


def test_fewest_changes_prefers_single_line():
    fewest = plan_route("dwarka_sector_21", "noida_electronic_city", "fewest_changes")
    assert fewest.interchange_ids == []
    assert lines_of(fewest) == ["DMRC_BLUE"]


def test_cheapest_avoids_airport_express_when_it_costs_more():
    fastest = plan_route("dwarka_sector_21", "noida_electronic_city", "fastest")
    cheapest = plan_route("dwarka_sector_21", "noida_electronic_city", "cheapest", on=MONDAY)
    assert "DMRC_AIRPORT" in lines_of(fastest)
    assert lines_of(cheapest) == ["DMRC_BLUE"]
    assert get_fare(cheapest, MONDAY).total < get_fare(fastest, MONDAY).total


def test_cheapest_keeps_airport_express_when_it_is_the_only_sensible_option():
    assert lines_of(plan_route("new_delhi", "airport_t3", "cheapest", on=MONDAY)) == ["DMRC_AIRPORT"]


def test_green_line_branch_joins_at_ashok_park_main():
    r = plan_route("satguru_ram_singh_marg", "inderlok")
    assert r.legs[0].station_ids == ["satguru_ram_singh_marg", "ashok_park_main", "inderlok"]


def test_bad_inputs_raise_tool_error():
    with pytest.raises(ToolError):
        plan_route("rajiv_chowk", "rajiv_chowk")
    with pytest.raises(ToolError):
        plan_route("rajiv_chowk", "not_a_station")


# --- fares ---


@pytest.mark.parametrize(
    ("a", "b", "on", "official"),
    [
        ("rajiv_chowk", "hauz_khas", MONDAY, 32),
        ("rajiv_chowk", "hauz_khas", SUNDAY, 21),
        ("rajiv_chowk", "sikanderpur", MONDAY, 54),
        ("rajiv_chowk", "cyber_city", MONDAY, 74),  # 54 DMRC + 20 Rapid Metro
        ("rajiv_chowk", "cyber_city", SUNDAY, 63),  # 43 + 20 (no Sunday discount on Rapid Metro)
        ("sikanderpur", "cyber_city", MONDAY, 31),  # standalone Rapid Metro from Sikanderpur
        ("rajiv_chowk", "airport_t3", MONDAY, 75),  # 11 DMRC + 64 Airport Express
        ("new_delhi", "dhaula_kuan", SUNDAY, 43),  # Airport Express: no Sunday discount
        ("noida_sector_51", "gnida_office", MONDAY, 50),  # NMRC: 19 stations
        ("noida_sector_51", "gnida_office", SUNDAY, 40),
    ],
)
def test_fares_match_official(a, b, on, official):
    assert get_fare(plan_route(a, b), on).total == official


def test_cross_operator_fare_lists_components():
    fare = get_fare(plan_route("kashmere_gate", "pari_chowk"), MONDAY)
    assert [c.operator for c in fare.components] == ["DMRC", "NMRC"]
    assert fare.total == sum(c.amount for c in fare.components)
    assert all(c.source_url.startswith("https://") for c in fare.components)


def test_day_type():
    assert day_type(MONDAY) == "weekday"
    assert day_type(SUNDAY) == "sunday_holiday"
    assert day_type(date(2026, 10, 2)) == "sunday_holiday"  # Gandhi Jayanti
    assert day_type(date(2026, 10, 3)) == "weekday"  # Saturday


# --- station search ---


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("rajiv chowk", "rajiv_chowk"),
        ("RC se", "rajiv_chowk"),
        ("rajiv chok", "rajiv_chowk"),
        ("hkv", "hauz_khas"),
        ("botanical", "botanical_garden"),
        ("cyber hub", "cyber_city"),
        ("noida sec 18", "noida_sector_18"),
        ("huda city centre", "millennium_city_centre_gurugram"),
        ("sector 52", "noida_sector_52"),
    ],
)
def test_search_station_top_hit(query, expected):
    assert search_station(query)[0].station_id == expected


def test_search_station_ambiguous_returns_close_scores():
    top = search_station("dwarka")
    assert len(top) == 3
    assert top[0].score - top[1].score < 5


def test_search_numbers_must_agree():
    assert search_station("sector 52")[0].station_id != "noida_sector_62"
