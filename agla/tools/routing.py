"""Route planning over the NCR metro graph."""

from __future__ import annotations

from datetime import date

import networkx as nx

from agla.network.graph import load_network
from agla.tools.types import Leg, Preference, Route, Stop, ToolError

CHANGE_COST = 1000.0  # fewest_changes: one interchange outweighs any realistic ride time
WALK = "WALK"
PRICEY_LINES = frozenset({"DMRC_AIRPORT"})  # premium fares; tried with and without for "cheapest"


def plan_route(from_id: str, to_id: str, preference: Preference = "fastest", on: date | None = None) -> Route:
    """Best route for `preference`. `on` only matters for "cheapest" (fares differ on Sundays)."""
    net = load_network()
    for sid in (from_id, to_id):
        if sid not in net.stations:
            raise ToolError(f"Unknown station id: {sid}")
    if from_id == to_id:
        raise ToolError("Origin and destination are the same station.")
    if preference not in ("fastest", "fewest_changes", "cheapest"):
        raise ToolError(f"Unknown preference: {preference}")

    if preference != "cheapest":
        path = _search(from_id, to_id, preference, avoid=frozenset())
        if path is None:
            raise ToolError(f"No route between {from_id} and {to_id}.")
        return _to_route(path, from_id, to_id, preference)

    # cheapest: price a few sensible candidates; Airport Express is the usual way "fastest" gets expensive
    from agla.tools.fares import get_fare  # fares depends on routing's output types, not the other way round

    day = on or date.today()
    candidates: dict[tuple, Route] = {}
    for pref in ("fastest", "fewest_changes"):
        for avoid in (frozenset(), PRICEY_LINES):
            path = _search(from_id, to_id, pref, avoid)
            if path is not None:
                candidates.setdefault(tuple(path), _to_route(path, from_id, to_id, "cheapest"))
    if not candidates:
        raise ToolError(f"No route between {from_id} and {to_id}.")
    return min(candidates.values(), key=lambda r: (get_fare(r, day).total, r.minutes))


def _search(from_id: str, to_id: str, preference: str, avoid: frozenset[str]) -> list[tuple[str, str]] | None:
    """Node path between the two stations (without the src/dst endpoints), or None."""

    def weight(u: tuple[str, str], v: tuple[str, str], d: dict) -> float | None:
        if u[1] in avoid or v[1] in avoid:
            return None  # networkx treats None as "edge hidden"
        changes = d["kind"] in ("transfer", "walk")
        return d["minutes"] + (CHANGE_COST if preference == "fewest_changes" and changes else 0.0)

    try:
        path = nx.shortest_path(load_network().graph, ("src", from_id), ("dst", to_id), weight=weight)
    except nx.NetworkXNoPath:
        return None
    return path[1:-1]


def _to_route(nodes: list[tuple[str, str]], from_id: str, to_id: str, preference: Preference) -> Route:
    net = load_network()
    g = net.graph
    name = {sid: s["name"] for sid, s in net.stations.items()}

    legs: list[Leg] = []
    stops: list[Stop] = []
    interchanges: list[str] = []
    t = 0.0
    km = 0.0
    leg_start = 0
    leg_t0 = 0.0

    def close_leg(end: int, line: str) -> None:
        ids = [nodes[i][0] for i in range(leg_start, end + 1)]
        meta = net.lines[line]
        legs.append(Leg(
            line_id=line,
            line_name=meta["name"],
            operator=meta["operator"],
            from_id=ids[0],
            to_id=ids[-1],
            station_ids=ids,
            minutes=round(t - leg_t0, 1),
            start_minutes=round(leg_t0, 1),
            end_minutes=round(t, 1),
        ))

    stops.append(Stop(from_id, name[from_id], nodes[0][1], 0.0, False))
    for i in range(1, len(nodes)):
        (a, la), (b, lb) = nodes[i - 1], nodes[i]
        edge = g.edges[nodes[i - 1], nodes[i]]
        if edge["kind"] == "ride":
            t += edge["minutes"]
            km += edge["km"]
            stops.append(Stop(b, name[b], lb, round(t, 1), False))
            continue
        # transfer, family change or walk: the current leg ends at `a`
        close_leg(i - 1, la)
        if edge["kind"] != "family":
            interchanges.append(a)
            stops[-1] = Stop(a, name[a], la, stops[-1].cum_minutes, True)
        if edge["kind"] == "walk":
            legs.append(Leg(WALK, f"Walk to {name[b]}", "walk", a, b, [a, b], edge["minutes"], round(t, 1),
                            round(t + edge["minutes"], 1)))
            t += edge["minutes"]
            stops.append(Stop(b, name[b], lb, round(t, 1), True))
        else:
            t += edge["minutes"]
        leg_start, leg_t0 = i, t
    close_leg(len(nodes) - 1, nodes[-1][1])

    # A route that starts or ends with a walk leaves a one-station "ride" leg at that end (you never board that
    # line). Drop it, so fares don't charge for a train that isn't taken, and don't call the endpoints interchanges.
    legs = [leg for leg in legs if leg.line_id == WALK or len(leg.station_ids) > 1]
    if not any(leg.line_id != WALK for leg in legs):
        raise ToolError(f"{name[from_id]} and {name[to_id]} are connected by a short walk, no metro needed.")
    interchanges = [s for s in interchanges if s not in (from_id, to_id)]
    stops[0] = Stop(stops[0].station_id, stops[0].name, legs[0].line_id, 0.0, False)
    stops[-1] = Stop(stops[-1].station_id, stops[-1].name, stops[-1].line_id, stops[-1].cum_minutes, False)

    return Route(
        from_id=from_id,
        to_id=to_id,
        preference=preference,
        legs=legs,
        stops=stops,
        interchange_ids=interchanges,
        minutes=round(t),
        distance_km=round(km, 1),
    )
