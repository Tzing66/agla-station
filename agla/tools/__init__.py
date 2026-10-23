"""The tool layer: the only API front ends (bot, MCP server, web) may call. All numbers come from here."""

from agla.tools.fares import get_fare
from agla.tools.payments import make_payment_link
from agla.tools.quotes import get_quote, quote_trip
from agla.tools.routing import plan_route
from agla.tools.stations import get_station, list_stations, resolve_station, search_station
from agla.tools.stats import get_stats, get_visited_stations
from agla.tools.trips import get_trip, log_trip, register_post_trip_hook
from agla.tools.types import (
    LANGUAGES,
    Fare,
    PaymentLink,
    Quote,
    Route,
    Station,
    StationMatch,
    Stats,
    ToolError,
    Trip,
    TripResult,
    User,
    Visit,
)
from agla.tools.users import find_user_by_telegram_id, get_or_create_user, get_user, set_language, set_safety

__all__ = [
    "LANGUAGES", "Fare", "PaymentLink", "Quote", "Route", "Station", "StationMatch", "Stats", "ToolError", "Trip",
    "TripResult", "User", "Visit",
    "find_user_by_telegram_id", "get_fare", "get_or_create_user", "get_quote", "get_station", "get_stats",
    "get_trip", "get_user", "get_visited_stations", "list_stations", "log_trip", "make_payment_link",
    "plan_route", "quote_trip", "register_post_trip_hook", "resolve_station", "search_station", "set_language",
    "set_safety",
]
