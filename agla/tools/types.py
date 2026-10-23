"""Shared result types for the tool layer. Every number a front end shows comes from one of these."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

State = Literal["Delhi", "Haryana", "UP"]
Preference = Literal["fastest", "fewest_changes", "cheapest"]
DayType = Literal["weekday", "sunday_holiday"]
Language = Literal["en", "hinglish", "hi"]
LANGUAGES: dict[str, str] = {"en": "English", "hinglish": "Hinglish", "hi": "हिंदी"}


class ToolError(Exception):
    """A user-facing failure (unknown station, no route, missing fare)."""


@dataclass(frozen=True)
class _Base:
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Station(_Base):
    station_id: str
    name: str
    aliases: list[str]
    lat: float
    lon: float
    state: State
    lines: list[str]
    operator: str


@dataclass(frozen=True)
class StationMatch(_Base):
    station_id: str
    name: str
    score: float
    matched_on: str
    lines: list[str]


@dataclass(frozen=True)
class Stop(_Base):
    station_id: str
    name: str
    line_id: str
    cum_minutes: float  # minutes from departure when the train reaches this stop
    is_interchange: bool


@dataclass(frozen=True)
class Leg(_Base):
    line_id: str  # "WALK" for a walking interchange between two stations
    line_name: str
    operator: str
    from_id: str
    to_id: str
    station_ids: list[str]
    minutes: float
    start_minutes: float  # minutes from departure when this leg starts (after any transfer)
    end_minutes: float


@dataclass(frozen=True)
class Route(_Base):
    from_id: str
    to_id: str
    preference: Preference
    legs: list[Leg]
    stops: list[Stop]
    interchange_ids: list[str]
    minutes: int
    distance_km: float


@dataclass(frozen=True)
class FareComponent(_Base):
    operator: str
    from_id: str
    to_id: str
    amount: int
    rule: str
    source_url: str


@dataclass(frozen=True)
class Fare(_Base):
    total: int
    day_type: DayType
    components: list[FareComponent]
    currency: str = "INR"
    note: str | None = None


def route_from_dict(d: dict) -> Route:
    return Route(
        **{**d, "legs": [Leg(**leg) for leg in d["legs"]], "stops": [Stop(**s) for s in d["stops"]]}
    )


def fare_from_dict(d: dict) -> Fare:
    return Fare(**{**d, "components": [FareComponent(**c) for c in d["components"]]})


@dataclass(frozen=True)
class User(_Base):
    user_id: int
    telegram_id: int
    first_name: str
    safety_on: bool
    demo_fast: bool
    language: Language = "en"


@dataclass(frozen=True)
class Quote(_Base):
    quote_id: str
    user_id: int
    route: Route
    fare: Fare
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class PaymentLink(_Base):
    upi_uri: str
    qr_png: bytes
    amount: int
    payee_name: str
    note: str


@dataclass(frozen=True)
class Trip(_Base):
    """A logged trip, as stored. Post-trip hooks receive this."""

    trip_id: int
    user_id: int
    ticket_id: str
    route: Route
    fare: Fare
    depart_at: str
    eta: str


@dataclass(frozen=True)
class TripResult(_Base):
    trip: Trip
    ticket_png: bytes
    new_visits: list[str]  # station names visited for the first time on this trip
    hook_results: dict  # post-trip hook name -> whatever it returned (miles, badges, safety...)
    already_logged: bool = False  # True when "I've paid" was pressed again for the same quote


@dataclass(frozen=True)
class Visit(_Base):
    station_id: str
    name: str
    state: State
    first_visit: str
    count: int


@dataclass(frozen=True)
class Stats(_Base):
    trips: int
    unique_stations: int
    total_minutes: int
    total_km: float
    total_fare: int
    favourite_line: str | None
    top_stations: list[tuple[str, int]]  # (station name, visits), most visited first
    states_visited: list[str]
    first_trip_at: str | None
    last_trip_at: str | None


@dataclass(frozen=True)
class MilesAward(_Base):
    delta: int
    reason: str
    created_at: str
    trip_id: int | None = None


@dataclass(frozen=True)
class MilesSummary(_Base):
    balance: int
    earned_total: int  # all positive awards ever (redemptions don't reduce it)
    recent: list[MilesAward]


@dataclass(frozen=True)
class Reward(_Base):
    reward_id: str
    name: str
    cost: int


@dataclass(frozen=True)
class Voucher(_Base):
    code: str
    reward_id: str
    name: str
    miles_spent: int
    created_at: str
    label: str = "DEMO — concept only, not redeemable"


@dataclass(frozen=True)
class BadgeStatus(_Base):
    badge_id: str
    name: str
    description: str
    hint: str
    earned_at: str | None  # None while locked
