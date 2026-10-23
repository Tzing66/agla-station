"""Process-wide configuration and the only clock. Front ends and tools read time from here."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now() -> datetime:
    return datetime.now(IST)


def today() -> date:
    return now().date()
