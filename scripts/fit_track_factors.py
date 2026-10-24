"""Check (and re-fit) the per-line DMRC track factors in data/fares.yaml against every official fare we hold.

Run: uv run python -m scripts.fit_track_factors [--fit]

DMRC charges by track distance in slabs, but our network only knows straight-line km between stations, which
runs short on curvy lines. Each official fare says which slab the true distance falls in, so it bounds the
distance of DMRC's own route. A line's factor stretches its straight-line km; this script checks that the factors
put every official fare in its slab, prints how far each factor could move without breaking one, and with --fit
searches for the smallest set of factors (closest to 1.0) that fits.

Evidence: fare samples priced on DMRC's own route (scripts/verify_fares.py), adjacent-station fares, and the human
spot-check Kashmere Gate -> Noida City Centre = Rs 54 weekday (2026-10-23).
"""

from __future__ import annotations

import sys

from agla.network.graph import load_network
from agla.tools.fares import _rules, get_fare
from scripts.verify_fares import KNOWN_QUIRKS, WEEKDAY, official_route, samples

GRID = [round(0.95 + 0.01 * i, 2) for i in range(46)]  # 0.95 .. 1.40
SPOT_CHECKS = [("kashmere_gate", "noida_city_centre", 54)]  # weekday, from the DMRC app


def shortest_dmrc_legs(a: str, b: str) -> list[tuple[str, list[str]]]:
    """The shortest straight-line DMRC path between two stations, split into (line, stations) legs."""
    import networkx as nx

    net = load_network()
    h = nx.Graph()
    for (x, lx), (y, ly), d in net.graph.edges(data=True):
        if d["kind"] == "ride" and lx == ly and net.lines[lx]["fare_operator"] == "DMRC":
            h.add_edge(x, y, km=d["fare_km"], line=lx)
    path = nx.shortest_path(h, a, b, weight="km")
    legs: list[tuple[str, list[str]]] = []
    for x, y in zip(path, path[1:], strict=False):
        line = h[x][y]["line"]
        if legs and legs[-1][0] == line:
            legs[-1][1].append(y)
        else:
            legs.append((line, [x, y]))
    return legs


def constraints() -> list[tuple[dict[str, float], float, float, str]]:
    """(straight-line km per DMRC line, low, high, label): the DMRC part must fall in (low, high]."""
    net, g = load_network(), load_network().graph
    rules = _rules()["operators"]["DMRC"]
    out = []

    def add(legs: list[tuple[str, list[str]]], day_type: str, dmrc_fare: int, label: str) -> None:
        kms: dict[str, float] = {}
        for line, ids in legs:
            for a, b in zip(ids, ids[1:], strict=False):
                kms[line] = kms.get(line, 0.0) + g.edges[(a, line), (b, line)]["fare_km"]
        low, matches = 0.0, []  # a fare can span neighbouring slabs (Sunday Rs 11 covers 0-5 km)
        for upper, fare in rules[day_type]:
            if fare == dmrc_fare:
                matches.append((low, upper if upper is not None else 1e9))
            low = upper if upper is not None else low
        if matches:
            out.append((kms, min(lo for lo, _ in matches), max(hi for _, hi in matches), label))

    by_code = {s["code"]: sid for sid, s in net.stations.items()}
    for a, b, day, official, legs in samples():
        if (a, b, day) in KNOWN_QUIRKS:  # official answers we deliberately don't follow (see verify_fares)
            continue
        route = official_route(legs) if legs else None
        if route is None and a in by_code and b in by_code:  # adjacent-station fares: one DMRC hop
            hop = [ln for ln in net.stations[by_code[a]]["lines"]
                   if g.has_edge((by_code[a], ln), (by_code[b], ln)) and net.lines[ln]["fare_operator"] == "DMRC"]
            if hop:
                add([(hop[0], [by_code[a], by_code[b]])], "weekday", official, f"{a}->{b} adjacent")
            continue
        if route is None:
            continue
        dmrc_legs = [(leg.line_id, leg.station_ids) for leg in route.legs
                     if net.lines[leg.line_id]["fare_operator"] == "DMRC"]
        if not dmrc_legs:
            continue
        other = sum(c.amount for c in get_fare(route, day).components if c.operator != "DMRC")
        dt = "weekday" if day == WEEKDAY else "sunday_holiday"
        add(dmrc_legs, dt, official - other, f"{a}->{b} {day:%a}")
    for a, b, fare in SPOT_CHECKS:
        add(shortest_dmrc_legs(a, b), "weekday", fare, f"spot-check {a}->{b}")
    return out


def violations(cons: list, factors: dict[str, float]) -> list[str]:
    bad = []
    for kms, low, high, label in cons:
        km = sum(factors.get(line, 1.0) * k for line, k in kms.items())
        if not low < km <= high and not (low == 0 and km <= high):
            bad.append(f"{label}: {km:.1f} km, official slab ({low:g}, {high:g}]")
    return bad


def main() -> int:
    cons = constraints()
    factors = dict(_rules()["operators"]["DMRC"].get("track_factors", {}))
    lines = sorted({line for kms, *_ in cons for line in kms})
    if "--fit" in sys.argv:
        factors = {}
        for _ in range(6):  # coordinate descent: fewest violations, then closest to 1.0
            for line in lines:
                def score(f: float, ln: str = line) -> tuple[int, float]:
                    return len(violations(cons, {**factors, ln: f})), abs(f - 1)

                factors[line] = min(GRID, key=score)
        factors = {k: v for k, v in factors.items() if v != 1.0}
    bad = violations(cons, factors)
    print(f"{len(cons)} official fares; factors {factors or 'all 1.0'}: {len(bad)} outside their slab")
    for b in bad:
        print("  " + b)
    print("\nRange each factor can take with the others fixed:")
    for line in lines:
        ok = [f for f in GRID if not violations(cons, {**factors, line: f})]
        print(f"  {line:18} {f'{min(ok)} .. {max(ok)}' if ok else 'none'}   (now {factors.get(line, 1.0)})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
