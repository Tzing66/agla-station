"""Station lookup: fuzzy, Hinglish-tolerant search over names and aliases."""

from __future__ import annotations

import re
from functools import cache

from rapidfuzz import fuzz, process

from agla.network.graph import load_network
from agla.tools.types import Station, StationMatch, ToolError

# Filler words people wrap station names in ("RC se", "hauz khas metro station tak").
FILLER = {"se", "to", "tak", "ko", "from", "metro", "station", "stn", "jana", "hai", "the", "go"}
EXPANSIONS = {"sec": "sector", "sect": "sector", "sctr": "sector", "nd": "new delhi", "ggn": "gurugram"}


def normalise(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"(\D)(\d)", r"\1 \2", text)  # "sec18" / "sector-18" -> "sec 18"
    words = re.findall(r"[a-z0-9]+", text)
    words = [EXPANSIONS.get(w, w) for w in words if w not in FILLER]
    return " ".join(words)


@cache
def _choices() -> tuple[list[str], list[tuple[str, str]]]:
    """Searchable strings and, for each, (station_id, the original name/alias it came from)."""
    texts: list[str] = []
    owners: list[tuple[str, str]] = []
    for sid, s in load_network().stations.items():
        for label in [s["name"], *s["aliases"]]:
            texts.append(normalise(label))
            owners.append((sid, label))
    return texts, owners


def _station(sid: str) -> Station:
    net = load_network()
    s = net.stations[sid]
    return Station(
        station_id=sid,
        name=s["name"],
        aliases=list(s["aliases"]),
        lat=s["lat"],
        lon=s["lon"],
        state=s["state"],
        lines=list(s["lines"]),
        operator=net.lines[s["lines"][0]]["operator"],
    )


def get_station(station_id: str) -> Station:
    if station_id not in load_network().stations:
        raise ToolError(f"Unknown station id: {station_id}")
    return _station(station_id)


def list_stations() -> list[Station]:
    return [_station(sid) for sid in load_network().stations]


def search_station(query: str, limit: int = 3) -> list[StationMatch]:
    """Top `limit` distinct stations for a messy query, best first. Scores are 0-100."""
    q = normalise(query)
    if not q:
        return []
    texts, owners = _choices()
    net = load_network()
    best: dict[str, StationMatch] = {}
    for _text, score, idx in process.extract(q, texts, scorer=_score, limit=limit * 8):
        sid, label = owners[idx]
        if sid not in best or score > best[sid].score:
            best[sid] = StationMatch(
                station_id=sid,
                name=net.stations[sid]["name"],
                score=round(score, 1),
                matched_on=label,
                lines=[net.lines[ln]["name"] for ln in net.stations[sid]["lines"]],
            )
    return sorted(best.values(), key=lambda m: (-m.score, m.name))[:limit]


AMBIGUITY_MARGIN = 5.0  # top two scores closer than this -> ask the user


def resolve_station(query: str) -> StationMatch:
    """One station for an id or a messy name; ToolError (listing candidates) if unknown or ambiguous."""
    if query in load_network().stations:
        s = _station(query)
        return StationMatch(query, s.name, 100.0, query, [load_network().lines[ln]["name"] for ln in s.lines])
    matches = search_station(query)
    if not matches:
        raise ToolError(f"No station matches {query!r}. Try the station's name as shown on the metro map.")
    if len(matches) > 1 and matches[0].score - matches[1].score < AMBIGUITY_MARGIN:
        options = "; ".join(f"{m.name} [{m.station_id}]" for m in matches)
        raise ToolError(f"{query!r} is ambiguous. Ask the user which one they mean: {options}")
    return matches[0]


def _score(query: str, choice: str, **_: object) -> float:
    if query == choice:
        return 100.0
    # Numbers must agree: "sector 52" should never fuzzily match "sector 62".
    if re.findall(r"\d+", query) and set(re.findall(r"\d+", query)) - set(re.findall(r"\d+", choice)):
        return fuzz.WRatio(query, choice) * 0.6
    return fuzz.WRatio(query, choice)
