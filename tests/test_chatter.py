"""Off-topic handling: the free metro-intent check and the canned-redirect policy (no API calls)."""

from __future__ import annotations

import random

import pytest

from agla.bot.chatter import REDIRECTS, ChatterState
from agla.tools import is_metro_related


@pytest.mark.parametrize("text", [
    "RC se hkv", "hauz khas to cyber hub", "how many miles do i have", "kashmere gate kaise jaun",
    "noida sec 18", "botanical", "मेट्रो से जाना है", "cp jana hai", "gk to cs", "my badges?",
])
def test_metro_related(text):
    assert is_metro_related(text)


@pytest.mark.parametrize("text", [
    "how are you", "tell me a joke", "who won the match yesterday", "what's the weather", "i am bored",
    "write me a poem about love", "are you chatgpt", "kya haal hai", "hi", "ok", "thanks", "lol",
])
def test_not_metro_related(text):
    assert not is_metro_related(text)


def test_first_off_topic_message_uses_the_llm_then_canned():
    s = ChatterState()
    assert not s.should_skip_llm(metro_related=False)  # 1st: natural LLM redirect
    s.record(metro_related=False, used_tools=False)
    assert s.should_skip_llm(metro_related=False)  # 2nd in a row: canned, no API call
    assert not s.should_skip_llm(metro_related=True)  # a metro message always goes to the LLM


def test_metro_message_or_tool_use_resets_the_streak():
    s = ChatterState(off_topic_streak=3)
    s.record(metro_related=True, used_tools=False)
    assert s.off_topic_streak == 0
    s = ChatterState(off_topic_streak=3)
    s.record(metro_related=False, used_tools=True)  # e.g. "what are my stats" phrased oddly, but a tool ran
    assert s.off_topic_streak == 0


def test_canned_lines_rotate_without_recent_repeats():
    s, rng = ChatterState(off_topic_streak=1), random.Random(7)
    lines = [s.canned("en", rng) for _ in range(30)]
    assert all(line in REDIRECTS["en"] for line in lines)
    for i in range(len(lines) - 4):
        assert len(set(lines[i:i + 5])) == 5  # any 5 consecutive replies are all different


def test_every_language_has_a_full_pool():
    assert {len(v) for v in REDIRECTS.values()} == {12}
    assert ChatterState(off_topic_streak=1).canned("hi") in REDIRECTS["hi"]
