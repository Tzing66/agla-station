"""Cheap, local check: does a message look like it's about metro travel? No API calls.

Used to stop spending LLM calls on repeated off-topic chatter: after a couple of off-topic turns the bot answers
from canned redirects until a message looks metro-related again.
"""

from __future__ import annotations

from agla.tools.stations import normalise, search_station

KEYWORDS = {
    "metro", "station", "stn", "route", "rasta", "raasta", "fare", "kiraya", "ticket", "train", "line", "interchange",
    "miles", "badge", "badges", "reward", "rewards", "wrapped", "stats", "trip", "trips", "safety", "reach", "reached",
    "jana", "jaana", "jaun", "jaaun", "pahunch", "pahuchna", "sasta", "cheapest", "fastest", "platform", "airport",
    "मेट्रो", "स्टेशन", "टिकट", "किराया", "जाना",
}
STATION_SCORE = 90.0
MIN_PHRASE_CHARS = 4


def is_metro_related(text: str) -> bool:
    words = [w.strip(".,!?;:'\"()") for w in text.lower().split()]  # \w splits Devanagari at vowel signs
    if any(w in KEYWORDS for w in words):
        return True
    norm = normalise(text).split()
    for n in (3, 2, 1):  # station names are 1-3 words; try the longest phrases first
        for i in range(len(norm) - n + 1):
            phrase = " ".join(norm[i:i + n])
            match = search_station(phrase, limit=1)
            if not match:
                continue
            if match[0].score == 100.0 or (len(phrase) >= MIN_PHRASE_CHARS and match[0].score >= STATION_SCORE):
                return True  # exact name/alias ("rc", "hkv") at any length; fuzzy only for longer phrases
    return False
