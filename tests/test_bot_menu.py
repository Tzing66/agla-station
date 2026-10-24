"""The persistent button menu that replaces slash commands."""

from __future__ import annotations

from pathlib import Path

from agla.bot import render
from agla.bot.app import Bot
from agla.config import Settings


def bot(public_url: str) -> Bot:
    cfg = Settings("", "1:x", "example_test_bot", "demo@upi", "Demo", "", "s", Path(":memory:"))
    return Bot(cfg, conn=None, agent=None, public_url=public_url)  # type: ignore[arg-type]


def test_menu_has_every_button_once():
    labels = [btn.text for row in bot("").menu().keyboard for btn in row]
    assert labels == [lbl for row in render.MENU_ROWS for lbl in row]
    assert len(set(labels)) == 6


def test_keyboard_never_holds_a_url():
    """Telegram keeps the keyboard on the phone; a tunnel URL baked into it goes dead when the tunnel changes."""
    for url in ("", "http://example.org", "https://x.example"):
        assert all(b.web_app is None for row in bot(url).menu().keyboard for b in row)


def test_keyboard_stays_and_hints_at_typing_a_trip():
    kb = bot("").menu()
    assert kb.is_persistent and kb.resize_keyboard and kb.input_field_placeholder == render.INPUT_HINT


def test_mini_app_needs_https():
    assert bot("https://x.example/").mini_app_url() == "https://x.example/app"
    assert bot("http://example.org").mini_app_url() is None
    assert bot("").mini_app_url() is None


def test_new_tunnel_url_updates_links_and_menu_button():
    import asyncio
    from types import SimpleNamespace as NS

    from agla.bot.app import set_public_url

    sent = []

    async def set_chat_menu_button(menu_button):
        sent.append(menu_button)

    b = bot("https://old.example")
    app = NS(bot_data={"agla": b}, bot=NS(set_chat_menu_button=set_chat_menu_button))
    asyncio.run(set_public_url(app, "https://new.example/"))
    assert b.share_url("tok") == "https://new.example/s/tok"
    assert sent[-1].web_app.url == "https://new.example/app"
    asyncio.run(set_public_url(app, ""))
    assert sent[-1].type == "default"  # no public URL: plain commands menu


def test_captions_are_escaped_and_cut_safely():
    import html
    import re
    from types import SimpleNamespace as NS

    caption = render.wrapped_caption(NS(month_name="October 2026"), "A & B " * 400)
    visible = html.unescape(re.sub(r"<[^>]+>", "", caption))  # Telegram counts the limit after parsing entities
    assert len(visible) <= render.CAPTION_LIMIT
    assert "&amp;" in caption and not re.search(r"&(?!amp;|lt;|gt;|quot;|#x27;)", caption)  # no half entity


def test_fare_label_never_says_weekday_on_a_saturday():
    """Rider report: a Saturday quote said "weekday fare". The amount was right (DMRC discounts Sundays and national
    holidays only); the label wasn't."""
    from datetime import datetime

    from agla import tools
    from agla.config import IST
    from agla.db import connect

    conn = connect(":memory:")
    uid = tools.get_or_create_user(conn, 5, "Asha", datetime(2026, 10, 24, 10, tzinfo=IST)).user_id
    cards = {}
    for day in (24, 25):  # Saturday, Sunday
        q = tools.quote_trip(conn, uid, "rajiv chowk", "hauz khas", "fastest", datetime(2026, 10, day, 10, tzinfo=IST))
        cards[day] = (q.fare.total, render.quote_card(q, tools.make_payment_link(q, "demo@upi", "Demo")))
    (sat_fare, sat), (sun_fare, sun) = cards[24], cards[25]
    assert "weekday" not in sat and "regular fare, Mon–Sat" in sat and "Sunday fares are lower" in sat
    assert "Sunday &amp; holiday fare" in sun and "Sunday fares are lower" not in sun  # & escaped for Telegram HTML
    assert (sat_fare, sun_fare) == (32, 21)
