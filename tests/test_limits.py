"""Review finding: unbounded LLM spend. Per-rider rate limit, and purging of stale unpaid quotes."""

from __future__ import annotations

from datetime import datetime, timedelta

from agla import tools
from agla.bot.limits import RateLimiter
from agla.config import IST
from agla.db import connect

T0 = datetime(2026, 10, 26, 9, 0, tzinfo=IST)


def test_per_minute_and_per_day_caps():
    lim = RateLimiter(per_minute=3, per_day=5)
    assert [lim.check(1, T0 + timedelta(seconds=i)) for i in range(4)] == [None, None, None, "minute"]
    assert lim.check(2, T0) is None  # other riders unaffected
    assert lim.check(1, T0 + timedelta(minutes=2)) is None  # minute window passed
    assert lim.check(1, T0 + timedelta(minutes=3)) is None
    assert lim.check(1, T0 + timedelta(minutes=4)) == "day"  # 5 counted today
    assert lim.check(1, T0 + timedelta(days=1, minutes=1)) is None  # next day


def test_purge_keeps_paid_and_recent_quotes():
    conn = connect(":memory:")
    uid = tools.get_or_create_user(conn, 42, "Ravi", T0).user_id
    paid = tools.quote_trip(conn, uid, "rc", "hkv", "fastest", T0)
    tools.log_trip(conn, paid.quote_id, 42, T0)
    stale = tools.quote_trip(conn, uid, "rc", "hkv", "fastest", T0)
    fresh = tools.quote_trip(conn, uid, "rc", "hkv", "fastest", T0 + timedelta(days=2))
    assert tools.purge_expired_quotes(conn, T0 + timedelta(days=2)) == 1
    ids = {r[0] for r in conn.execute("SELECT id FROM quotes")}
    assert ids == {paid.quote_id, fresh.quote_id} and stale.quote_id not in ids
