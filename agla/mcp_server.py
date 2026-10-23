"""agla-mcp: the Agla Station tool layer over MCP (stdio).

Run:  uv run --directory /path/to/agla-station python -m agla.mcp_server

A thin front end: every tool resolves inputs and calls agla.tools; no metro logic lives here.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from agla import tools
from agla.config import today

INSTRUCTIONS = """\
Delhi NCR metro (DMRC lines, Airport Express, Rapid Metro Gurugram, Noida Aqua Line).
Plan routes and quote fares with these tools. Never state a time, distance or fare that a tool did not return.
If a station name is ambiguous the tool says so and lists candidates: ask the user which one they mean.
Fares are official token fares; Sundays and national holidays are cheaper on most lines."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

mcp = MCPServer("agla_mcp", instructions=INSTRUCTIONS)

StationArg = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        description="Station id (e.g. 'rajiv_chowk') or a name as a person would type it "
        "(e.g. 'RC', 'hauz khas', 'cyber hub', 'noida sec 18').",
    ),
]
PreferenceArg = Annotated[
    Literal["fastest", "fewest_changes", "cheapest"],
    Field(description="'fastest' (default), 'fewest_changes', or 'cheapest' (avoids pricey Airport Express)."),
]
DateArg = Annotated[
    str | None,
    Field(description="Travel date YYYY-MM-DD (fares differ on Sundays/holidays). Defaults to today in IST."),
]


def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Turn tool-layer errors into MCP tool errors the agent can read and act on."""
    try:
        return fn(*args, **kwargs)
    except tools.ToolError as exc:
        raise MCPToolError(str(exc)) from exc


def _date(value: str | None) -> date:
    if not value:
        return today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MCPToolError(f"Bad date {value!r}: use YYYY-MM-DD, e.g. {today().isoformat()}.") from exc


def _journey(origin: str, destination: str, preference: str, on: date) -> tuple[tools.Route, tools.Fare]:
    a = _call(tools.resolve_station, origin)
    b = _call(tools.resolve_station, destination)
    route = _call(tools.plan_route, a.station_id, b.station_id, preference, on)
    return route, _call(tools.get_fare, route, on)


def _route_summary(route: tools.Route) -> dict:
    """Route without the per-stop list, which agents rarely need and which costs context."""
    names = {sid: tools.get_station(sid).name for leg in route.legs for sid in (leg.from_id, leg.to_id)}
    return {
        "from": names[route.legs[0].from_id],
        "to": names[route.legs[-1].to_id],
        "preference": route.preference,
        "minutes": route.minutes,
        "distance_km": route.distance_km,
        "interchanges": [tools.get_station(s).name for s in route.interchange_ids],
        "legs": [
            {
                "line": leg.line_name,
                "from": names[leg.from_id],
                "to": names[leg.to_id],
                "stops": len(leg.station_ids) - 1,
                "minutes": leg.minutes,
            }
            for leg in route.legs
        ],
    }


@mcp.tool(name="agla_search_station", annotations=READ_ONLY, structured_output=True)
def search_station(
    query: Annotated[str, Field(min_length=1, max_length=100, description="Messy station name, e.g. 'rajiv chok'")],
    limit: Annotated[int, Field(ge=1, le=10, description="Max matches to return")] = 3,
) -> list[dict[str, Any]]:
    """Find metro stations matching a name, abbreviation, landmark or Hinglish phrasing.

    Returns up to `limit` matches, best first: station_id, name, score (0-100), matched_on, lines.
    Close top scores mean the query is ambiguous; ask the user to choose.
    """
    return [m.to_dict() for m in _call(tools.search_station, query, limit)]


@mcp.tool(name="agla_plan_route", annotations=READ_ONLY, structured_output=True)
def plan_route(
    origin: StationArg,
    destination: StationArg,
    preference: PreferenceArg = "fastest",
    travel_date: DateArg = None,
    include_stops: Annotated[bool, Field(description="Include every stop with cumulative minutes")] = False,
) -> dict[str, Any]:
    """Plan a metro route between two stations and quote its fare.

    Returns: route (from, to, minutes, distance_km, interchanges, legs[line, from, to, stops, minutes]),
    fare (total INR, day_type, components per operator with rule and source_url), and stops if requested.
    """
    on = _date(travel_date)
    route, fare = _journey(origin, destination, preference, on)
    out = {"route": _route_summary(route), "fare": fare.to_dict()}
    if include_stops:
        out["stops"] = [{"name": s.name, "cum_minutes": s.cum_minutes, "interchange": s.is_interchange}
                        for s in route.stops]
    return out


@mcp.tool(name="agla_get_fare", annotations=READ_ONLY, structured_output=True)
def get_fare(
    origin: StationArg,
    destination: StationArg,
    preference: PreferenceArg = "fastest",
    travel_date: DateArg = None,
) -> dict[str, Any]:
    """Official token fare for a trip (the fare depends on the route chosen by `preference`).

    Returns: total (INR), day_type (weekday | sunday_holiday), components[operator, amount, rule, source_url],
    and route_lines so the agent can say which route the fare is for.
    """
    on = _date(travel_date)
    route, fare = _journey(origin, destination, preference, on)
    return {**fare.to_dict(), "route_lines": [leg.line_name for leg in route.legs]}


NOT_YET = "Not available yet: {what} arrives in Phase {phase} of the Agla Station build (trips are logged by the bot)."


@mcp.tool(name="agla_get_stats", annotations=READ_ONLY)
def get_stats(telegram_id: Annotated[int | None, Field(description="Rider; defaults to the demo user")] = None) -> str:
    """A rider's trip statistics (trips, minutes, distance, spend). Not available until the bot logs trips."""
    raise MCPToolError(NOT_YET.format(what="trip stats", phase=4))


@mcp.tool(name="agla_get_visited_stations", annotations=READ_ONLY)
def get_visited_stations(
    telegram_id: Annotated[int | None, Field(description="Rider; defaults to the demo user")] = None,
) -> str:
    """Stations a rider has visited (origin, destination or interchange of a logged trip)."""
    raise MCPToolError(NOT_YET.format(what="visited stations", phase=4))


@mcp.tool(name="agla_get_badges", annotations=READ_ONLY)
def get_badges(telegram_id: Annotated[int | None, Field(description="Rider; defaults to the demo user")] = None) -> str:
    """A rider's earned and locked badges."""
    raise MCPToolError(NOT_YET.format(what="badges", phase=6))


@mcp.tool(name="agla_get_miles", annotations=READ_ONLY)
def get_miles(telegram_id: Annotated[int | None, Field(description="Rider; defaults to the demo user")] = None) -> str:
    """A rider's Metro Miles balance and recent awards."""
    raise MCPToolError(NOT_YET.format(what="Metro Miles", phase=6))


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
