"""Cheap, local check: does a message look like it's about metro travel? No API calls.

Used to stop spending LLM calls on repeated off-topic chatter: after a couple of off-topic turns the bot answers
from canned redirects until a message looks metro-related again.
"""

from __future__ import annotations

from functools import cache

from agla.network.graph import load_network
from agla.tools.stations import normalise, search_station

KEYWORDS = {
    "metro", "station", "stn", "route", "rasta", "raasta", "fare", "kiraya", "ticket", "train", "line", "interchange",
    "miles", "badge", "badges", "reward", "rewards", "wrapped", "stats", "trip", "trips", "safety", "reach", "reached",
    "jana", "jaana", "jaun", "jaaun", "pahunch", "pahuchna", "sasta", "cheapest", "fastest", "platform", "airport",
    "मेट्रो", "स्टेशन", "टिकट", "किराया", "जाना",
}
STATION_SCORE = 90.0
MIN_PHRASE_CHARS = 4


MAX_WORDS = 30  # only look at the start of long messages


@cache
def _exact_names() -> frozenset[str]:
    return frozenset(normalise(label) for s in load_network().stations.values() for label in [s["name"], *s["aliases"]])


def is_metro_related(text: str) -> bool:
    words = [w.strip(".,!?;:'\"()") for w in text.lower().split()][:MAX_WORDS]  # \w splits Devanagari
    if any(w in KEYWORDS for w in words):
        return True
    norm = normalise(" ".join(words)).split()
    names = _exact_names()
    phrases = [" ".join(norm[i:i + n]) for n in (3, 2, 1) for i in range(len(norm) - n + 1)]
    if any(p in names for p in phrases):  # cheap set lookups first ("rc", "hauz khas")
        return True
    for phrase in phrases:  # then fuzzy matching, only for phrases long enough to mean something
        if len(phrase) < MIN_PHRASE_CHARS:
            continue
        match = search_station(phrase, limit=1)
        if match and match[0].score >= STATION_SCORE:
            return True
    return False
