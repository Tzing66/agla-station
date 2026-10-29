"""Phase 2: station search, routing and fares over the built network.

Expected fares are official DMRC journey-planner / NMRC fare-table values fetched 2026-10-23.
"""

from __future__ import annotations

from datetime import date

import pytest

from agla.tools.fares import day_type, get_fare
from agla.tools.routing import plan_route
from agla.tools.stations import resolve_station, search_station
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
    assert get_fare(cheapest, MONDAY).total == 64  # human spot-check: matches DMRC's minimum-interchange fare
    assert get_fare(fastest, MONDAY).total == 118  # human spot-check: matches DMRC's quickest-route fare


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
        # human spot-check against the DMRC / NMRC apps, 2026-10-23
        ("millennium_city_centre_gurugram", "botanical_garden", SUNDAY, 54),
        ("noida_sector_51", "pari_chowk", MONDAY, 40),
        ("janakpuri_west", "kalkaji_mandir", SUNDAY, 43),
        ("new_delhi", "airport_t3", MONDAY, 64),
    ],
)
def test_fares_match_official(a, b, on, official):
    assert get_fare(plan_route(a, b), on).total == official


def test_fare_near_21km_boundary_kashmere_gate_noida_city_centre():
    # Human spot-check 2026-10-23: DMRC app shows Rs 54. Straight lines gave 20.7 km (Rs 43) until the Blue Line's
    # track factor; it was the known xfail until then.
    assert get_fare(plan_route("kashmere_gate", "noida_city_centre"), MONDAY).total == 54


def test_curvy_magenta_line_is_stretched_to_its_track_length():
    # Official Rs 84 = 64 DMRC (over 32 km) + 20 Rapid Metro; straight lines measure 30.8 km
    fare = get_fare(plan_route("botanical_garden", "cyber_city"), MONDAY)
    assert fare.total == 84 and fare.components[0].amount == 64


def test_dmrc_charges_shortest_distance_whichever_way_you_ride():
    # Our route goes via Mandi House (32.4 km ridden); DMRC charges the 30 km shortest track: Rs 54, not 64.
    route = plan_route("mewala_maharajpur", "rajendra_place")
    assert get_fare(route, MONDAY).total == 54
    assert get_fare(route, MONDAY).components[0].rule.startswith("30.0 km")


def test_cheapest_finds_the_short_airport_express_hop():
    # Fastest joins the Airport Express by the Dhaula Kuan footbridge (Rs 107). DMRC's own route stays on the Blue
    # Line to Dwarka Sector 21 and takes a short Airport Express hop: Rs 75, which "cheapest" must find.
    a, b = "maharaja_surajmal_stadium", "yashobhoomi_dwarka_sector_25"
    assert get_fare(plan_route(a, b, "fastest"), MONDAY).total == 107
    cheapest = plan_route(a, b, "cheapest", on=MONDAY)
    assert get_fare(cheapest, MONDAY).total == 75
    assert not any(leg.line_id == "WALK" for leg in cheapest.legs)


def test_every_official_fare_matches_on_dmrcs_own_route(capsys):
    import re

    from scripts import fit_track_factors, verify_fares

    verify_fares.main()
    ok, total = map(int, re.search(r"(\d+)/(\d+) match", capsys.readouterr().out).groups())
    assert ok == total >= 404  # fare samples, cross-operator samples and adjacent pairs
    assert fit_track_factors.main() == 0  # every fare inside its official slab with the factors in fares.yaml


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


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("milennium city centre", "millennium_city_centre_gurugram"),  # typo used to look ambiguous
        ("punjabi bagh", "punjabi_bagh"),  # exact name beats "Punjabi Bagh West"
        ("sector 52 noida", "noida_sector_52"),  # word order
        ("knowledge park", "knowledge_park_ii"),
        ("electronic city", "noida_electronic_city"),
    ],
)
def test_resolve_station(query, expected):
    from agla.tools.stations import resolve_station

    assert resolve_station(query).station_id == expected


@pytest.mark.parametrize("query", ["mayur vihar", "shivaji", "dwarka", "janakpuri", "badli"])
def test_resolve_station_asks_when_several_stations_share_the_words(query):
    from agla.tools.stations import resolve_station

    with pytest.raises(ToolError, match="ambiguous"):
        resolve_station(query)



# review finding: routes that start or end with a walk used to charge for a train never boarded
def test_walk_at_the_start_isnt_charged():
    r = plan_route("noida_sector_52", "noida_sector_50")
    assert lines_of(r) == ["WALK", "NMRC_AQUA"]
    assert r.interchange_ids == [] and not r.stops[0].is_interchange
    fare = get_fare(r, MONDAY)
    assert [c.operator for c in fare.components] == ["NMRC"] and fare.total == 10  # one Aqua stop


def test_walk_at_the_end_over_the_footbridge_can_be_priced():
    r = plan_route("delhi_cantt", "dhaula_kuan")
    assert lines_of(r)[-1] == "WALK"
    fare = get_fare(r, MONDAY)
    assert [c.operator for c in fare.components] == ["DMRC"]


def test_walk_only_trip_is_not_a_metro_trip():
    with pytest.raises(ToolError, match="short walk"):
        plan_route("noida_sector_52", "noida_sector_51")


@pytest.mark.parametrize("query", ["india gate", "parliament", "delhi university", "iit delhi"])
def test_places_that_only_share_a_word_with_a_station_are_not_guessed(query):
    """Found while writing example prompts: these used to route to Delhi Gate, Palam and Delhi Aerocity."""
    with pytest.raises(ToolError, match="isn't a station name I know. The closest is"):
        resolve_station(query)


@pytest.mark.parametrize(("query", "name"), [
    ("conaught place", "Rajiv Chowk"), ("rajeev chowk", "Rajiv Chowk"), ("kashmeri gate", "Kashmere Gate"),
    ("milennium city centre", "Millennium City Centre Gurugram"), ("red fort", "Lal Quila"), ("hkv", "Hauz Khas"),
])
def test_typos_aliases_and_landmarks_still_resolve(query, name):
    assert resolve_station(query).name == name


@pytest.mark.parametrize(("query", "name"), [
    ("knowledge park 2", "Knowledge Park II"), ("knowledge park ii", "Knowledge Park II"),
    ("mayur vihar 2", "East Vinod Nagar - Mayur Vihar II"),
    ("mayur vihar phase 2", "East Vinod Nagar - Mayur Vihar II"),
    ("mayur vihar 1", "Mayur Vihar I"), ("mayur vihar i", "Mayur Vihar I"), ("ip extension", "I.P. Extension"),
])
def test_digits_and_roman_numerals_are_the_same_station(query, name):
    """2026-10-28: "knowledge park 2" matched nothing, so Claude searched and retried: three calls for one trip."""
    assert resolve_station(query).name == name
