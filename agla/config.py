"""Process-wide configuration and the only clock. Front ends and tools read time and settings from here."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[1]


def now() -> datetime:
    return datetime.now(IST)


def today() -> date:
    return now().date()


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_bot_username: str
    upi_vpa: str
    upi_payee_name: str
    public_base_url: str
    dashboard_secret: str
    db_path: Path
    model: str = "claude-sonnet-5-5"


@cache
def settings() -> Settings:
    load_dotenv(ROOT / ".env")
    env = os.environ.get
    return Settings(
        anthropic_api_key=env("ANTHROPIC_API_KEY", ""),
        telegram_bot_token=env("TELEGRAM_BOT_TOKEN", ""),
        telegram_bot_username=env("TELEGRAM_BOT_USERNAME", "").lstrip("@"),
        upi_vpa=env("UPI_VPA", ""),
        upi_payee_name=env("UPI_PAYEE_NAME", "") or "Agla Station",
        public_base_url=env("PUBLIC_BASE_URL", "").rstrip("/"),
        dashboard_secret=env("DASHBOARD_SECRET", ""),
        db_path=Path(env("AGLA_DB", str(ROOT / "data" / "agla.db"))),
        model=env("AGLA_MODEL", "claude-sonnet-5-5"),
    )
