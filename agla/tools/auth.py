"""Dashboard authentication.

1. Telegram Mini App: validate `initData` as Telegram documents it:
   secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
   hash == HMAC_SHA256(key=secret_key, msg=data_check_string), rejected if auth_date is older than 24 h.
2. Normal browsers: a signed, expiring magic link (itsdangerous, DASHBOARD_SECRET).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from urllib.parse import parse_qsl

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from agla.tools.types import ToolError

INIT_DATA_MAX_AGE = timedelta(hours=24)
MAGIC_LINK_MAX_AGE = timedelta(days=7)
_SALT = "agla-dashboard"
MIN_SECRET_LEN = 32


def _require_secret(secret: str) -> None:
    """The salt and payload shape are public (open-source repo), so the secret is the only thing preventing forgery."""
    if len(secret or "") < MIN_SECRET_LEN:
        raise ToolError(f"DASHBOARD_SECRET must be set to at least {MIN_SECRET_LEN} random characters.")


def verify_init_data(init_data: str, bot_token: str, now: datetime) -> dict:
    """Return the Telegram user dict ({"id", "first_name", ...}) if initData is genuine and fresh."""
    if not init_data or not bot_token:
        raise ToolError("Missing Telegram login data.")
    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received = fields.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise ToolError("Telegram login data didn't verify. Reopen the dashboard from the bot.")
    try:
        auth_date = datetime.fromtimestamp(int(fields["auth_date"]), tz=now.tzinfo)
        user = json.loads(fields["user"])
    except (KeyError, ValueError) as exc:
        raise ToolError("Telegram login data is incomplete.") from exc
    if now - auth_date > INIT_DATA_MAX_AGE:
        raise ToolError("This dashboard session is more than a day old. Reopen it from the bot.")
    return user


def sign_dashboard_token(telegram_id: int, secret: str) -> str:
    _require_secret(secret)
    return URLSafeTimedSerializer(secret, salt=_SALT).dumps({"tid": telegram_id})


def verify_dashboard_token(token: str, secret: str) -> int:
    """Telegram id from a magic link, if the signature is valid and the link is less than 7 days old."""
    _require_secret(secret)
    try:
        data = URLSafeTimedSerializer(secret, salt=_SALT).loads(token, max_age=int(MAGIC_LINK_MAX_AGE.total_seconds()))
    except SignatureExpired as exc:
        raise ToolError("This dashboard link has expired. Send /dashboard to the bot for a new one.") from exc
    except BadSignature as exc:
        raise ToolError("This dashboard link isn't valid.") from exc
    return int(data["tid"])
