"""LLM loop with a scripted fake client: tool dispatch, quote capture, ambiguity, and the number guard."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace as NS

from agla import tools
from agla.config import IST
from agla.db import connect
from agla.llm import GUARD_FALLBACK, GUARD_FALLBACK_WITH_CARD, Agent, guard_numbers

MON = datetime(2026, 10, 26, 9, 30, tzinfo=IST)
USAGE = NS(input_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0, output_tokens=1)


def text(t):
    return NS(type="text", text=t)


def tool_use(name, **args):
    return NS(type="tool_use", id=f"tu_{name}", name=name, input=args)


class FakeClient:
    """Returns scripted responses in order and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self.create))

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        content, stop = self.responses.pop(0)
        return NS(content=content, stop_reason=stop, usage=USAGE)


def run(client, text_in, history=None):
    conn = connect(":memory:")
    user = tools.get_or_create_user(conn, 1, "Tanmay", MON)
    agent = Agent(client, conn, "claude-sonnet-5-5")
    return asyncio.run(agent.respond(user, history or [], text_in, MON)), conn


def test_guard_numbers():
    assert guard_numbers("About 19 min, Rs 32.", "rc to hkv", ['{"minutes": 19, "fare_inr": 32}'])
    assert not guard_numbers("That's Rs 40.", "rc to hkv", ['{"fare_inr": 32}'])
    assert guard_numbers("Sector 18 it is!", "noida sector 18", [])  # numbers the rider typed are fine
    assert guard_numbers("No numbers here.", "", [])


def test_quote_flow_returns_quote_id_and_reply():
    client = FakeClient(
        ([tool_use("quote_trip", origin="RC", destination="hkv", preference="fastest")], "tool_use"),
        ([text("Seedha Yellow Line, koi change nahi!")], "end_turn"),
    )
    reply, conn = run(client, "RC se hkv")
    assert reply.text.startswith("Seedha") and not reply.guarded
    assert len(reply.quote_ids) == 1
    assert tools.get_quote(conn, reply.quote_ids[0]).fare.total == 32
    # the tool result went back to the model, and the request carried caching + fallbacks + low effort
    second = client.requests[1]
    result = second["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and not result["is_error"]
    assert '"lines": ["Yellow Line"]' in result["content"]
    # review finding: the model sees no numbers (or quote ids) for a trip, so it has nothing to restate or swap
    assert not any(ch.isdigit() for ch in result["content"])
    assert second["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert second["fallbacks"] == "default" and second["output_config"] == {"effort": "low"}


def test_invented_number_trips_the_guard():
    client = FakeClient(
        ([tool_use("quote_trip", origin="RC", destination="hkv", preference="fastest")], "tool_use"),
        ([text("That'll be Rs 25, cheap!")], "end_turn"),
    )
    reply, _ = run(client, "RC se hkv")
    assert reply.guarded and reply.text == GUARD_FALLBACK_WITH_CARD and len(reply.quote_ids) == 1


def test_guard_without_card_uses_generic_fallback():
    client = FakeClient(([text("You've taken 42 trips this year.")], "end_turn"))
    reply, _ = run(client, "how many trips?")
    assert reply.guarded and reply.text == GUARD_FALLBACK and reply.quote_ids == []


def test_ambiguous_station_is_returned_as_tool_error():
    client = FakeClient(
        ([tool_use("quote_trip", origin="dwarka", destination="rc", preference="fastest")], "tool_use"),
        ([text("Which Dwarka station: Dwarka Mor, Dwarka Sector 10 or Dwarka Sector 11?")], "end_turn"),
    )
    reply, _ = run(client, "dwarka to rc")
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "ambiguous" in result["content"]
    assert reply.quote_ids == [] and not reply.guarded  # "10"/"11" came from the tool's options


def test_history_is_capped_and_text_only():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(10)]
    client = FakeClient(([text("hi")], "end_turn"))
    run(client, "hello", history)
    sent = client.requests[0]["messages"]
    assert [m["content"] for m in sent[:6]] == [f"m{i}" for i in range(4, 10)]
    assert sent[6] == {"role": "user", "content": "hello"} and sent[7]["role"] == "system"


def test_refusal_gets_a_polite_redirect():
    client = FakeClient(([], "refusal"))
    reply, _ = run(client, "something off-topic")
    assert "metro" in reply.text


def test_devanagari_digits_count_as_numbers():
    assert guard_numbers("किराया ₹३२ है", "rc to hkv", ['{"fare_inr": 32}'])
    assert not guard_numbers("किराया ₹४० है", "rc to hkv", ['{"fare_inr": 32}'])


def test_language_goes_in_the_per_turn_system_note():
    client = FakeClient(([text("हो गया")], "end_turn"))
    conn = connect(":memory:")
    user = tools.set_language(conn, tools.get_or_create_user(conn, 1, "Tanmay", MON).user_id, "hi")
    asyncio.run(Agent(client, conn, "m").respond(user, [], "hi", MON))
    req = client.requests[0]
    assert "Reply language: Hindi (Devanagari)" in req["messages"][-1]["content"]
    assert "Reply language" not in req["system"][0]["text"]  # cached prefix stays identical across riders


def test_history_text_notes_what_the_app_showed():
    client = FakeClient(
        ([tool_use("quote_trip", origin="RC", destination="hkv", preference="fastest")], "tool_use"),
        ([text("Seedha Yellow Line!")], "end_turn"),
    )
    reply, _ = run(client, "RC se hkv")
    assert reply.history_text == (
        "Seedha Yellow Line!\n[Shown to rider: route card and UPI payment QR for Rajiv Chowk to Hauz Khas, Rs 32]"
    )



def test_any_number_in_a_trip_reply_is_rejected():
    # even a true one: the card shows the numbers, and the model never sees them
    client = FakeClient(
        ([tool_use("quote_trip", origin="RC", destination="hkv", preference="fastest")], "tool_use"),
        ([text("Seedha Yellow Line, 19 min!")], "end_turn"),
    )
    reply, _ = run(client, "RC se hkv")
    assert reply.guarded and reply.text == GUARD_FALLBACK_WITH_CARD
