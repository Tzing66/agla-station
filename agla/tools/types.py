"""Shared result types for the tool layer. Every number a front end shows comes from one of these."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

State = Literal["Delhi", "Haryana", "UP"]
Preference = Literal["fastest", "fewest_changes", "cheapest"]
DayType = Literal["weekday", "sunday_holiday"]


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
