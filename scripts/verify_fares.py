"""Compare get_fare() with official DMRC journey-planner fares.

Run: uv run python scripts/verify_fares.py [--show-all]

Samples: data/raw/dmrc_api/fare_samples.json (random pairs, weekday + Sunday) and
segments_*.json (every adjacent pair, weekday). Pairs the planner returns 0 for are skipped.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from agla.network.graph import load_network
from agla.tools.fares import get_fare
from agla.tools.routing import plan_route
from agla.tools.types import ToolError

RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "dmrc_api"
WEEKDAY, SUNDAY = date(2026, 10, 26), date(2026, 10, 25)


def load(path: Path) -> object:
    data = json.loads(path.read_text())
    return json.loads(data) if isinstance(data, str) else data


def samples() -> list[tuple[str, str, date, int]]:
    out = []
    for r in load(RAW / "fare_samples.json")["fares"]:
        out.append((r["from"], r["to"], SUNDAY if r["when"].startswith("2026-10-25") else WEEKDAY, r["fare"]))
    for f in sorted(RAW.glob("segments_*.json")):
        out += [(r["from"], r["to"], WEEKDAY, r["fare"]) for r in load(f)]
    return [s for s in out if s[3]]


def main() -> None:
    show_all = "--show-all" in sys.argv
    by_code = {s["code"]: sid for sid, s in load_network().stations.items()}
    ok = bad = skipped = 0
    for a, b, day, official in samples():
        if a not in by_code or b not in by_code:
            skipped += 1
            continue
        try:
            route = plan_route(by_code[a], by_code[b])
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
    total = ok + bad
    print(f"\n{ok}/{total} match ({ok / total:.1%}), {skipped} skipped")


if __name__ == "__main__":
    main()
