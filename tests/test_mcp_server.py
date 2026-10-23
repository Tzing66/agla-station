"""agla-mcp over a real stdio connection, as Claude Code / Claude Desktop would use it."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def _session_calls(calls: list[tuple[str, dict]]) -> tuple[list[str], list]:
    params = StdioServerParameters(command=sys.executable, args=["-m", "agla.mcp_server"], cwd=str(ROOT))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        names = [t.name for t in (await s.list_tools()).tools]
        results = [await s.call_tool(name, args) for name, args in calls]
    return names, results


def test_mcp_server_end_to_end():
    names, (route, fare, ambiguous, later) = asyncio.run(_session_calls([
        ("agla_plan_route", {"origin": "Botanical Garden", "destination": "Cyber City", "travel_date": "2026-10-26"}),
        ("agla_get_fare", {"origin": "rc", "destination": "hkv", "travel_date": "2026-10-25"}),
        ("agla_plan_route", {"origin": "dwarka", "destination": "rajiv chowk"}),
        ("agla_get_badges", {}),
    ]))

    assert set(names) == {
        "agla_search_station", "agla_plan_route", "agla_get_fare", "agla_get_stats",
        "agla_get_visited_stations", "agla_get_badges", "agla_get_miles",
    }

    assert not route.is_error
    body = route.structured_content
    assert body["route"]["interchanges"] == ["Hauz Khas", "Sikanderpur"]
    assert body["fare"]["total"] == sum(c["amount"] for c in body["fare"]["components"])

    assert not fare.is_error
    assert fare.structured_content["total"] == 21  # official Sunday fare, Rajiv Chowk -> Hauz Khas

    assert ambiguous.is_error
    assert "ambiguous" in ambiguous.content[0].text and "dwarka_mor" in ambiguous.content[0].text

    assert later.is_error and "Not available yet" in later.content[0].text
