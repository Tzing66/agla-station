"""Fares from data/fares.yaml. Cross-operator trips pay the sum of each operator's segment."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

import yaml

from agla.network.graph import load_network
from agla.tools.types import DayType, Fare, FareComponent, Route, ToolError

ROOT = Path(__file__).resolve().parents[2]
FARES_FILE = ROOT / "data" / "fares.yaml"


@dataclass(frozen=True)
class Segment:
    """A contiguous stretch of a route charged by one fare operator."""

    operator: str
    station_ids: list[str]  # every station passed, in order
    fare_km: float  # distance used for slab fares (see "fare_km" in network.json)


@cache
def _rules() -> dict:
    return yaml.safe_load(FARES_FILE.read_text())


@cache
def _od_table(rel_path: str) -> dict[tuple[str, str], dict[str, int]]:
    rows = [ln for ln in (ROOT / rel_path).read_text().splitlines() if not ln.startswith("#")]
    return {
        (r["from_id"], r["to_id"]): {"weekday": int(r["weekday"]), "sunday_holiday": int(r["sunday_holiday"])}
        for r in csv.DictReader(rows)
    }


def day_type(on: date) -> DayType:
    if on.weekday() == 6 or on.strftime("%m-%d") in _rules()["national_holidays"]:
        return "sunday_holiday"
    return "weekday"


def _slab(slabs: list[list], value: float) -> int:
    for upper, fare in slabs:
        if upper is None or value <= upper:
            return int(fare)
    raise ToolError("Fare slab table is malformed.")


def segments(route: Route) -> list[Segment]:
    """Split a route into per-operator segments; a walk always ends a segment."""
    net = load_network()
    out: list[Segment] = []
    for leg in route.legs:
        if leg.line_id == "WALK":
            out.append(Segment("WALK", [], 0.0))
            continue
        op = net.lines[leg.line_id]["fare_operator"]
        km = sum(
            net.graph.edges[(a, leg.line_id), (b, leg.line_id)]["fare_km"]
            for a, b in zip(leg.station_ids, leg.station_ids[1:], strict=False)
        )
        if out and out[-1].operator == op:
            prev = out[-1]
            out[-1] = Segment(op, prev.station_ids + leg.station_ids[1:], prev.fare_km + km)
        else:
            out.append(Segment(op, list(leg.station_ids), km))
    return [s for s in out if s.operator != "WALK"]


def get_fare(route: Route, on: date) -> Fare:
    rules = _rules()["operators"]
    dt = day_type(on)
    components: list[FareComponent] = []
    segs = segments(route)
    for seg in segs:
        rule = rules[seg.operator]
        a, b = seg.station_ids[0], seg.station_ids[-1]
        if "through_fare" in rule and len(segs) > 1:
            amount = int(rule["through_fare"])
            how = "flat fare when changing to/from DMRC"
        elif rule["kind"] == "distance_slabs":
            amount = _slab(rule[dt], seg.fare_km)
            how = f"{seg.fare_km:.1f} km, {dt.replace('_', '/')} slab"
        elif rule["kind"] == "station_count_slabs":
            count = len(seg.station_ids) - 1
            amount = _slab(rule[dt], count)
            how = f"{count} stations, {dt.replace('_', '/')} slab"
        elif rule["kind"] == "od_table":
            fares = _od_table(rule["table"]).get((a, b))
            if fares is None:
                raise ToolError(f"No published {seg.operator} fare for this trip.")
            amount = fares[dt]
            how = "official station-pair fare"
        else:
            raise ToolError(f"Unknown fare rule kind: {rule['kind']}")
        components.append(FareComponent(seg.operator, a, b, amount, how, rule["source_url"]))
    return Fare(total=sum(c.amount for c in components), day_type=dt, components=components)
