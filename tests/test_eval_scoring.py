"""The eval's scorer must grade the system the rider gets, so test it on hand-made responses (no API calls)."""

from __future__ import annotations

from types import SimpleNamespace as NS

from evals.run_eval import load_cases, score


def quote(origin, destination, preference="fastest"):
    return [NS(type="tool_use", name="quote_trip",
               input={"origin": origin, "destination": destination, "preference": preference})]


def reply(text):
    return [NS(type="text", text=text)]


NORMAL = {"id": "c", "category": "plain", "input": "x",
          "expected": {"origin": "rajiv_chowk", "destination": "hauz_khas"}}
PREF = {"id": "p", "category": "hinglish", "input": "x",
        "expected": {"origin": "hauz_khas", "destination": "cyber_city", "preference": "cheapest"}}
AMBIG = {"id": "a", "category": "ambiguous", "input": "dwarka to rc",
         "expected": {"ask": True, "ambiguous_side": "origin"}}


def test_dataset_shape():
    cases = load_cases()
    assert len(cases) == 50
    assert sum(c["category"] == "ambiguous" for c in cases) == 5
    assert len({c["id"] for c in cases}) == 50


def test_normal_case_passes_through_the_resolver():
    assert score(NORMAL, quote("RC", "hkv")).passed
    assert not score(NORMAL, quote("hkv", "RC")).passed  # swapped
    assert not score(NORMAL, reply("Which Rajiv Chowk?")).passed  # asking when it shouldn't


def test_preference_scored_separately():
    r = score(PREF, quote("hauz khas", "cyber city", "fastest"))
    assert r.passed and r.preference_ok is False
    assert score(PREF, quote("hauz khas", "cyber city", "cheapest")).preference_ok is True


def test_ambiguous_case_passes_when_the_system_asks():
    assert score(AMBIG, reply("Which Dwarka station do you mean?")).passed  # model asks
    assert score(AMBIG, quote("dwarka", "rajiv chowk")).passed  # resolver flags the ambiguous side
    assert not score(AMBIG, quote("dwarka mor", "rajiv chowk")).passed  # model guessed
