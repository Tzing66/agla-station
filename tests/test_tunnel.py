"""The quick-tunnel watchdog: a tunnel that stops answering is replaced and the bot gets the new URL."""

from __future__ import annotations

import asyncio

import agla.__main__ as main


def test_dead_tunnel_is_replaced_after_repeated_failures(monkeypatch):
    monkeypatch.setattr(main, "PROBE_EVERY", 0)
    tun = main.Tunnel(8000)
    tun.url = "https://old.trycloudflare.com"
    probes = iter([False, True, False, False, False])  # one blip is forgiven; three in a row are not
    started, seen = [], []

    async def healthy(http):
        return next(probes)

    async def start():
        tun.url = f"https://new{len(started)}.trycloudflare.com"
        started.append(tun.url)
        return tun.url

    async def on_new_url(url):
        seen.append(url)
        raise asyncio.CancelledError  # stop the loop once the bot has been told

    monkeypatch.setattr(tun, "healthy", healthy)
    monkeypatch.setattr(tun, "start", start)
    try:
        asyncio.run(tun.watch(on_new_url))
    except asyncio.CancelledError:
        pass
    assert started == seen == ["https://new0.trycloudflare.com"]


def test_watchdog_survives_an_outage(monkeypatch):
    """2026-10-25: the network dropped mid-replacement and the watchdog died silently, so the tunnel stayed dead
    after the network came back. Now a hung attempt times out, an unreachable Telegram is retried, and it carries on."""
    monkeypatch.setattr(main, "PROBE_EVERY", 0)
    monkeypatch.setattr(main, "START_TIMEOUT", 0.05)
    tun = main.Tunnel(8000)
    tun.url = "https://old.trycloudflare.com"
    attempts, told = [], []

    async def healthy(http):
        return tun.url != "https://old.trycloudflare.com"  # only a replaced tunnel answers

    async def start():
        attempts.append(1)
        if len(attempts) == 1:
            await asyncio.sleep(10)  # offline: the first attempt never finishes
        tun.url = "https://new.trycloudflare.com"

    async def on_new_url(url):
        told.append(url)
        if len(told) == 1:
            raise OSError("Telegram unreachable")  # still offline when the new tunnel comes up
        raise asyncio.CancelledError  # told successfully: stop the test

    monkeypatch.setattr(tun, "healthy", healthy)
    monkeypatch.setattr(tun, "start", start)
    try:
        asyncio.run(tun.watch(on_new_url))
    except asyncio.CancelledError:
        pass
    assert len(attempts) == 2  # the hung attempt timed out and was retried
    assert told == ["https://new.trycloudflare.com"] * 2  # the failed hand-over was retried too
