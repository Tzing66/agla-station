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
