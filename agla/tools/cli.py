"""Dev CLI over the tool layer.

    python -m agla.tools.cli "rajiv chowk" "hauz khas" [--fewest-changes | --cheapest] [--date 2026-10-25]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from agla.config import today
from agla.tools.fares import DAY_LABELS, get_fare
from agla.tools.routing import plan_route
from agla.tools.stations import get_station, resolve_station
from agla.tools.types import ToolError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("origin")
    p.add_argument("destination")
    pref = p.add_mutually_exclusive_group()
    pref.add_argument("--fewest-changes", action="store_true")
    pref.add_argument("--cheapest", action="store_true")
    p.add_argument("--date", type=date.fromisoformat, default=today())
    args = p.parse_args(argv)
    try:
        a, b = resolve_station(args.origin), resolve_station(args.destination)
        preference = "cheapest" if args.cheapest else "fewest_changes" if args.fewest_changes else "fastest"
        route = plan_route(a.station_id, b.station_id, preference, on=args.date)
        fare = get_fare(route, args.date)
    except ToolError as exc:
        print(exc, file=sys.stderr)
        return 1

    changes = len(route.interchange_ids)
    print(f"{a.name} -> {b.name}: ~{route.minutes} min, {route.distance_km} km, "
          f"{changes} change{'s' if changes != 1 else ''}")
    for leg in route.legs:
        stops = len(leg.station_ids) - 1
        if leg.line_id == "WALK":
            print(f"  walk  {leg.line_name} (~{leg.minutes:.0f} min)")
        else:
            print(f"  {leg.line_name}: {get_station(leg.from_id).name} -> {get_station(leg.to_id).name}, "
                  f"{stops} stop{'s' if stops != 1 else ''}, ~{leg.minutes:.0f} min")
    parts = " + ".join(f"{c.operator} Rs {c.amount}" for c in fare.components)
    print(f"Fare: Rs {fare.total} ({DAY_LABELS[fare.day_type]}) = {parts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
