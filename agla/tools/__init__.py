"""The tool layer: the only API front ends (bot, MCP server, web) may call. All numbers come from here."""

from agla.tools.fares import get_fare
from agla.tools.intent import is_metro_related
from agla.tools.payments import make_payment_link
from agla.tools.quotes import get_quote, quote_trip
from agla.tools.routing import plan_route
from agla.tools.stations import get_station, list_stations, resolve_station, search_station
from agla.tools.stats import get_stats, get_visited_stations
from agla.tools.storage import DEMO_TELEGRAM_ID, open_database
from agla.tools.trips import get_trip, log_trip, register_post_trip_hook
from agla.tools.types import (
    LANGUAGES,
    BadgeStatus,
    Fare,
    MilesAward,
    MilesSummary,
    PaymentLink,
    Quote,
    Reward,
    Route,
    Station,
    StationMatch,
    Stats,
    ToolError,
    Trip,
    TripResult,
    User,
    Visit,
    Voucher,
)
from agla.tools.users import find_user_by_telegram_id, get_or_create_user, get_user, set_language, set_safety

__all__ = [
    "LANGUAGES", "Fare", "PaymentLink", "Quote", "Route", "Station", "StationMatch", "Stats", "ToolError", "Trip",
    "TripResult", "User", "Visit",
    "find_user_by_telegram_id", "get_fare", "get_or_create_user", "get_quote", "get_station", "get_stats",
    "get_trip", "get_user", "get_visited_stations", "list_stations", "log_trip", "make_payment_link",
    "plan_route", "quote_trip", "register_post_trip_hook", "resolve_station", "search_station", "set_language",
    "set_safety",
    "BadgeStatus", "MilesAward", "MilesSummary", "Reward", "Voucher",
    "DEMO_TELEGRAM_ID", "open_database", "is_metro_related",
    "award_safe_arrival", "get_badges", "get_miles", "list_rewards", "list_vouchers", "redeem_reward",
]

# Domain modules (docs/architecture.md) are re-exported lazily: they import tool submodules themselves, so a
# from-import here would be circular whenever agla.miles / agla.badges is imported before agla.tools.
import agla.badges as _badges  # noqa: E402
import agla.miles as _miles  # noqa: E402
import agla.wrapped as _wrapped  # noqa: E402

_DOMAIN = {
    "get_badges": _badges,
    "award_safe_arrival": _miles, "get_miles": _miles, "list_rewards": _miles, "list_vouchers": _miles,
    "redeem_reward": _miles,
    "wrapped_stats": _wrapped, "template_text": _wrapped, "save_recap": _wrapped, "get_recap": _wrapped,
    "fresh_recap": _wrapped, "list_recaps": _wrapped, "render_card": _wrapped,
    "WrappedStats": _wrapped, "Recap": _wrapped,
}


def __getattr__(name: str):  # PEP 562: tools.get_miles(...) / from agla.tools import get_miles
    if name in _DOMAIN:
        return getattr(_DOMAIN[name], name)
    raise AttributeError(f"module 'agla.tools' has no attribute {name!r}")


# Post-trip hooks, in order: miles first so the "Thousand Miler" badge sees this trip's miles.
register_post_trip_hook("miles", lambda conn, trip, now: _miles.award_trip_miles(conn, trip, now))
register_post_trip_hook("badges", lambda conn, trip, now: _badges.badges_hook(conn, trip, now))
