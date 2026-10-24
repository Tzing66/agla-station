"""Compare get_fare() with official DMRC journey-planner fares.

Run: uv run python -m scripts.verify_fares [--show-all]

Samples: data/raw/dmrc_api/fare_samples.json (random pairs, weekday + Sunday, with the route DMRC's planner took)
and segments_*.json (every adjacent pair, weekday). Pairs the planner returns 0 for are skipped.

Each sample is priced on DMRC's own route, so this checks the fare engine. Where our planner picks a different
route (say, joining the Airport Express by the Dhaula Kuan footbridge), that route's fare is listed separately:
it's a different trip, not a fare error.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from agla.network.graph import load_network
from agla.tools.fares import get_fare
from agla.tools.routing import plan_route
from agla.tools.types import Leg, Route, ToolError

RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "dmrc_api"
WEEKDAY, SUNDAY = date(2026, 10, 26), date(2026, 10, 25)
# Old names the planner still writes in routes. Not rider aliases: "dwarka" stays ambiguous for riders on purpose.
PLANNER_NAMES = {"DWARKA": "dwarka_kakrola"}


def load(path: Path) -> object:
    data = json.loads(path.read_text())
    return json.loads(data) if isinstance(data, str) else data


def samples() -> list[tuple[str, str, date, int, list | None]]:
    """(from code, to code, day, official fare, DMRC's legs or None)."""
    out = []
    for r in load(RAW / "fare_samples.json")["fares"]:
        out.append((r["from"], r["to"], SUNDAY if r["when"].startswith("2026-10-25") else WEEKDAY, r["fare"],
                    r.get("legs")))
    for f in sorted(RAW.glob("segments_*.json")):
        out += [(r["from"], r["to"], WEEKDAY, r["fare"], None) for r in load(f)]
    return [s for s in out if s[3]]


def official_route(legs: list[dict]) -> Route | None:
    """DMRC's route from a sample (station names as the API writes them), on our network; None if it can't be
    mapped (a station or segment we don't have)."""
    net = load_network()
    name_to_id = _name_to_id()
    out: list[Leg] = []
    for leg in legs:
        ids = [name_to_id.get(n.strip()) for n in leg["path"]]
        if None in ids or len(ids) < 2:
            return None
        lines = {_ride_line(a, b) for a, b in zip(ids, ids[1:], strict=False)}
        if None in lines:
            return None
        for line in sorted(lines):  # a branch can share a leg with its trunk: split by line
            run = [ids[0]] if not out or _ride_line(ids[0], ids[1]) == line else []
            for a, b in zip(ids, ids[1:], strict=False):
                if _ride_line(a, b) == line:
                    run = run or [a]
                    run.append(b)
            if len(run) > 1:
                meta = net.lines[line]
                out.append(Leg(line, meta["name"], meta["operator"], run[0], run[-1], run, 0.0, 0.0, 0.0))
    if not out:
        return None
    return Route(out[0].from_id, out[-1].to_id, "fastest", out, [], [], 0, 0.0)


def _name_to_id() -> dict[str, str]:
    """API station names -> our ids, plus our own names and aliases, plus PLANNER_NAMES."""
    net = load_network()
    by_code = {s["code"]: sid for sid, s in net.stations.items()}
    out = {s["name"].strip(): by_code[s["code"]] for s in load(RAW / "snapshot.json")["stations"]
           if s["code"] in by_code} | PLANNER_NAMES
    for sid, s in net.stations.items():
        for name in [s["name"], *s.get("aliases", [])]:
            out.setdefault(name.strip().upper(), sid)
    return out


def _ride_line(a: str, b: str) -> str | None:
    g = load_network().graph
    for line in load_network().stations[a]["lines"]:
        if g.has_edge((a, line), (b, line)) and g.edges[(a, line), (b, line)]["kind"] == "ride":
            return line
    return None


def main() -> None:
    show_all = "--show-all" in sys.argv
    by_code = {s["code"]: sid for sid, s in load_network().stations.items()}
    ok = bad = skipped = 0
    other_routes: list[str] = []
    for a, b, day, official, legs in samples():
        if a not in by_code or b not in by_code:
            skipped += 1
            continue
        try:
            planned = plan_route(by_code[a], by_code[b], on=day)
            route = (official_route(legs) if legs else None) or planned
            fare = get_fare(route, day)
        except ToolError as exc:
            print(f"ERROR {a}->{b}: {exc}")
            bad += 1
            continue
        match = fare.total == official
        ok += match
        bad += not match
        if show_all or not match:
            parts = " + ".join(f"{c.operator} {c.amount} ({c.rule})" for c in fare.components)
            print(f"{'ok ' if match else 'BAD'} {a}->{b} {day:%a}: ours {fare.total} vs official {official} = {parts}")
        if route is not planned and (ours := get_fare(planned, day).total) != official:
            other_routes.append(f"  {a}->{b} {day:%a}: official {official} on DMRC's route; our fastest route {ours}")
    total = ok + bad
    print(f"\n{ok}/{total} match on DMRC's own routes ({ok / total:.1%}), {skipped} skipped")
    if other_routes:
        print(f"\nOur fastest route differs from DMRC's, so its fare differs too ({len(other_routes)}):")
        print("\n".join(other_routes))


if __name__ == "__main__":
    main()
