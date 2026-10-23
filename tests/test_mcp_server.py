"""agla-mcp over a real stdio connection, as Claude Code / Claude Desktop would use it."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agla import tools
from agla.config import IST
from agla.db import connect

ROOT = Path(__file__).resolve().parents[1]


async def _session_calls(calls: list[tuple[str, dict]], db: Path) -> tuple[list[str], list]:
    env = {**os.environ, "AGLA_DB": str(db)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "agla.mcp_server"], cwd=str(ROOT), env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        names = [t.name for t in (await s.list_tools()).tools]
        results = [await s.call_tool(name, args) for name, args in calls]
    return names, results


def test_mcp_server_end_to_end(tmp_path):
    db = tmp_path / "agla.db"
    conn = connect(db)
    when = datetime(2026, 10, 24, 18, 0, tzinfo=IST)
    demo = tools.get_or_create_user(conn, tools.DEMO_TELEGRAM_ID, "Demo", when)
    q = tools.quote_trip(conn, demo.user_id, "rajiv chowk", "hauz khas", "fastest", when)
    tools.log_trip(conn, q.quote_id, tools.DEMO_TELEGRAM_ID, when)
    conn.close()

    names, (route, fare, ambiguous, badges, miles, unknown) = asyncio.run(_session_calls([
        ("agla_plan_route", {"origin": "Botanical Garden", "destination": "Cyber City", "travel_date": "2026-10-26"}),
        ("agla_get_fare", {"origin": "rc", "destination": "hkv", "travel_date": "2026-10-25"}),
        ("agla_plan_route", {"origin": "dwarka", "destination": "rajiv chowk"}),
        ("agla_get_badges", {}),
        ("agla_get_miles", {}),
        ("agla_get_stats", {"telegram_id": 999}),
    ], db))

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

    earned = [b["badge_id"] for b in badges.structured_content["result"] if b["earned_at"]]
    assert not badges.is_error and earned == ["first_ride"]
    assert miles.structured_content["balance"] > 0 and miles.structured_content["rewards"]
    assert unknown.is_error and "No rider" in unknown.content[0].text
