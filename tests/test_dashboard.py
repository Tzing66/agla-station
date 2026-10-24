"""Phase 9: dashboard auth (Telegram initData HMAC, signed magic links) and the JSON API."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from agla import tools
from agla.config import IST, Settings
from agla.db import connect
from agla.web.app import create_app

BOT_TOKEN = "123456:TEST-token-for-hmac-checks-only"
SECRET = "test-dashboard-secret-0123456789abcdef"
NOW = datetime(2026, 10, 23, 20, 0, tzinfo=IST)


def init_data(user: dict, auth_date: datetime, bot_token: str = BOT_TOKEN, **extra: str) -> str:
    """Build initData exactly as Telegram signs it."""
    fields = {"auth_date": str(int(auth_date.timestamp())), "query_id": "AAE", "user": json.dumps(user), **extra}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_valid_init_data():
    user = tools.verify_init_data(init_data({"id": 42, "first_name": "Meera"}, NOW), BOT_TOKEN, NOW)
    assert user == {"id": 42, "first_name": "Meera"}


def test_tampered_or_stale_init_data_rejected():
    good = init_data({"id": 42, "first_name": "Meera"}, NOW)
    with pytest.raises(tools.ToolError, match="didn't verify"):
        tools.verify_init_data(good.replace("42", "43"), BOT_TOKEN, NOW)  # someone else's id
    with pytest.raises(tools.ToolError, match="didn't verify"):
        tools.verify_init_data(init_data({"id": 42}, NOW, bot_token="999:other"), BOT_TOKEN, NOW)
    with pytest.raises(tools.ToolError, match="more than a day old"):
        tools.verify_init_data(init_data({"id": 42}, NOW - timedelta(hours=25)), BOT_TOKEN, NOW)


def test_magic_link_roundtrip_and_tamper():
    token = tools.sign_dashboard_token(42, SECRET)
    assert tools.verify_dashboard_token(token, SECRET) == 42
    with pytest.raises(tools.ToolError, match="isn't valid"):
        tools.verify_dashboard_token(token, "another-secret-that-is-long-enough-123")


def test_empty_or_short_secret_cannot_be_used_to_forge_links():
    # review finding: the salt and payload are public, so with an empty secret anyone could mint a token
    from itsdangerous import URLSafeTimedSerializer

    forged = URLSafeTimedSerializer("", salt="agla-dashboard").dumps({"tid": 12345})
    for weak in ("", "short-secret"):
        with pytest.raises(tools.ToolError, match="DASHBOARD_SECRET"):
            tools.verify_dashboard_token(forged, weak)
        with pytest.raises(tools.ToolError, match="DASHBOARD_SECRET"):
            tools.sign_dashboard_token(42, weak)


@pytest.fixture
def client():
    conn = connect(":memory:")
    uid = tools.get_or_create_user(conn, 42, "Meera", NOW).user_id
    trips = [("rajiv chowk", "hauz khas"), ("hauz khas", "cyber city"), ("kashmere gate", "pari chowk")]
    for i, (a, b) in enumerate(trips):
        when = NOW - timedelta(days=3 - i)
        q = tools.quote_trip(conn, uid, a, b, "fastest", when)
        tools.log_trip(conn, q.quote_id, 42, when)
    cfg = Settings("", BOT_TOKEN, "example_test_bot", "demo@upi", "Demo", "", SECRET, Path(":memory:"))
    return TestClient(create_app(conn, cfg))


def auth(telegram_id: int = 42) -> dict:
    return {"X-Dashboard-Token": tools.sign_dashboard_token(telegram_id, SECRET)}


def test_api_requires_auth(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"X-Dashboard-Token": "forged"}).status_code == 401
    assert client.get("/app").status_code == 200  # the page itself is public; it asks the API with credentials


def test_api_with_magic_link(client):
    me = client.get("/api/me", headers=auth()).json()
    assert me["first_name"] == "Meera" and me["stats"]["trips"] == 3
    m = client.get("/api/map", headers=auth()).json()
    assert len(m["stations"]) == 275 and m["segments"] and sum(s["visits"] > 0 for s in m["stations"]) >= 5
    assert {c["name"] for c in m["completion"] if c["visited"]} >= {"Yellow Line", "Aqua Line"}
    assert any(b["earned_at"] for b in client.get("/api/badges", headers=auth()).json())
    ins = client.get("/api/insights", headers=auth()).json()
    assert ins["totals"]["trips"] == 3 and len(ins["trips_per_week"]) == 8
    wrapped = client.get("/api/wrapped", headers=auth()).json()
    assert wrapped[0]["month"] == "2026-10" and wrapped[0]["trips"] == 3
    assert wrapped[0]["slides"][0]["key"] == "trips" and wrapped[0]["narration"] is None  # no LLM recap saved yet
    card = client.get("/api/wrapped/2026-10/card.png", headers=auth())
    assert card.headers["content-type"] == "image/png"


def test_api_with_telegram_init_data_creates_rider(client, monkeypatch):
    import agla.web.app as web

    monkeypatch.setattr(web, "now", lambda: NOW)
    headers = {"X-Telegram-Init-Data": init_data({"id": 77, "first_name": "Ravi"}, NOW)}
    me = client.get("/api/me", headers=headers).json()
    assert me["first_name"] == "Ravi" and me["stats"]["trips"] == 0


def test_redeem_through_api(client):
    miles = client.get("/api/miles", headers=auth()).json()
    affordable = [r for r in miles["rewards"] if r["cost"] <= miles["balance"]]
    too_dear = [r for r in miles["rewards"] if r["cost"] > miles["balance"]]
    if affordable:
        res = client.post("/api/redeem", json={"reward_id": affordable[0]["reward_id"]}, headers=auth()).json()
        assert res["balance"] == miles["balance"] - affordable[0]["cost"]
        assert "not redeemable" in res["voucher"]["label"]
    r = client.post("/api/redeem", json={"reward_id": too_dear[-1]["reward_id"]}, headers=auth())
    assert r.status_code == 400 and "Not enough Metro Miles" in r.json()["detail"]
