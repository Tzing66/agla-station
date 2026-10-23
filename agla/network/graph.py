"""Load data/network.json into a routing graph.

Nodes:
- (station_id, line_id)  riding or waiting on a line at a station
- ("src", station_id)    journey start, free edge onto any line at the station
- ("dst", station_id)    journey end, free edge off any line at the station
Edge attribute `kind`: ride | transfer | family | walk | endpoint.
`family` transfers (e.g. Pink <-> Pink extension) are cheap and don't count as interchanges.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from itertools import permutations
from pathlib import Path

import networkx as nx

NETWORK_FILE = Path(__file__).resolve().parents[2] / "data" / "network.json"

TRANSFER_MINUTES = 6.0
FAMILY_TRANSFER_MINUTES = 2.0


@dataclass(frozen=True)
class Network:
    stations: dict[str, dict]
    lines: dict[str, dict]
    graph: nx.DiGraph
    meta: dict


def build_graph(data: dict) -> nx.DiGraph:
    g = nx.DiGraph()
    lines = data["lines"]
    for e in data["edges"]:
        a, b = (e["from"], e["line"]), (e["to"], e["line"])
        attrs = {"kind": "ride", "minutes": e["minutes"], "km": e["km"], "fare_km": e.get("fare_km", e["km"])}
        g.add_edge(a, b, **attrs)
        if not e["directed"]:
            g.add_edge(b, a, **attrs)

    for sid, s in data["stations"].items():
        for la, lb in permutations(s["lines"], 2):
            same_family = lines[la]["family"] == lines[lb]["family"]
            g.add_edge(
                (sid, la),
                (sid, lb),
                kind="family" if same_family else "transfer",
                minutes=FAMILY_TRANSFER_MINUTES if same_family else TRANSFER_MINUTES,
                km=0.0,
            )
        for line in s["lines"]:
            g.add_edge(("src", sid), (sid, line), kind="endpoint", minutes=0.0, km=0.0)
            g.add_edge((sid, line), ("dst", sid), kind="endpoint", minutes=0.0, km=0.0)

    stations = data["stations"]
    for w in data["walks"]:
        for a, b in ((w["from"], w["to"]), (w["to"], w["from"])):
            for la in stations[a]["lines"]:
                for lb in stations[b]["lines"]:
                    g.add_edge((a, la), (b, lb), kind="walk", minutes=w["minutes"], km=0.0)
    return g


@cache
def load_network(path: Path = NETWORK_FILE) -> Network:
    data = json.loads(path.read_text())
    return Network(stations=data["stations"], lines=data["lines"], graph=build_graph(data), meta=data["meta"])
