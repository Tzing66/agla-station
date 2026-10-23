"""Public share pages: content, privacy headers, live status fragment, expiry."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from agla import tools
from agla.config import IST
from agla.db import connect
from agla.web import app as web

T0 = datetime(2026, 10, 26, 13, 0, tzinfo=IST)


@pytest.fixture
def setup(monkeypatch):
    conn = connect(":memory:")
    uid = tools.get_or_create_user(conn, 42, "Meera Sharma", T0).user_id
    q = tools.quote_trip(conn, uid, "rajiv chowk", "hauz khas", "fastest", T0)
    trip = tools.log_trip(conn, q.quote_id, 42, T0).trip
    token = tools.create_share(conn, trip.trip_id, 42, T0)
    clock = {"now": T0 + timedelta(minutes=5)}
    monkeypatch.setattr(web, "now", lambda: clock["now"])
    return TestClient(web.create_app(conn)), token, clock, conn, trip


def test_share_page(setup):
    client, token, *_ = setup
    r = client.get(f"/s/{token}")
    assert r.status_code == 200
    html = r.text
    assert "Meera is travelling" in html and "Sharma" not in html  # first name only
    assert "Rajiv Chowk → Hauz Khas" in html and "not live GPS" in html
    assert 'hx-trigger="every 30s"' in html
    assert r.headers["x-robots-tag"] == "noindex, nofollow" and r.headers["referrer-policy"] == "no-referrer"


def test_status_fragment_tracks_time_and_arrival(setup):
    client, token, clock, conn, trip = setup
    assert "On the way" in client.get(f"/s/{token}/status").text
    clock["now"] = T0 + timedelta(minutes=40)
    assert "hasn't confirmed arrival yet" in client.get(f"/s/{token}/status").text  # overdue
    tools.confirm_arrival(conn, trip.trip_id, 42, clock["now"])
    assert "confirmed they've reached Hauz Khas" in client.get(f"/s/{token}/status").text


def test_expired_and_unknown_links(setup):
    client, token, clock, *_ = setup
    clock["now"] = T0 + timedelta(hours=3)
    r = client.get(f"/s/{token}")
    assert r.status_code == 410 and "This journey has ended" in r.text
    assert client.get(f"/s/{token}/status").headers["hx-refresh"] == "true"
    assert client.get("/s/nope").status_code == 410


def test_health(setup):
    assert setup[0].get("/healthz").text == "ok"
