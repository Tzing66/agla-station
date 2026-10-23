"""The persistent button menu that replaces slash commands."""

from __future__ import annotations

from pathlib import Path

from agla.bot import render
from agla.bot.app import Bot
from agla.config import Settings


def bot(public_url: str) -> Bot:
    cfg = Settings("", "1:x", "example_test_bot", "demo@upi", "Demo", "", "s", frozenset(), Path(":memory:"))
    return Bot(cfg, conn=None, agent=None, public_url=public_url)  # type: ignore[arg-type]


def test_menu_has_every_button_once():
    labels = [btn.text for row in bot("").menu().keyboard for btn in row]
    assert labels == [lbl for row in render.MENU_ROWS for lbl in row]
    assert len(set(labels)) == 6


def test_dashboard_button_opens_mini_app_when_public():
    public = {b.text: b for row in bot("https://x.example").menu().keyboard for b in row}
    assert public[render.BTN_DASHBOARD].web_app.url == "https://x.example/app"
    local = {b.text: b for row in bot("").menu().keyboard for b in row}
    assert local[render.BTN_DASHBOARD].web_app is None  # falls back to the /dashboard reply


def test_keyboard_stays_and_hints_at_typing_a_trip():
    kb = bot("").menu()
    assert kb.is_persistent and kb.resize_keyboard and kb.input_field_placeholder == render.INPUT_HINT
