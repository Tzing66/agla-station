"""Run Agla Station: the Telegram bot and the web app (share pages, later the Mini App) in one process.

    uv run python -m agla              # bot + web on http://127.0.0.1:8000, links use PUBLIC_BASE_URL
    uv run python -m agla --tunnel     # also start a cloudflared quick tunnel and use its https URL for links

One process, one SQLite writer (docs/architecture.md).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re

import anthropic
import uvicorn

from agla import tools
from agla.bot.app import build_application, configure_bot
from agla.config import now, settings
from agla.db import connect
from agla.llm import Agent
from agla.web.app import create_app

log = logging.getLogger("agla")
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


async def start_tunnel(port: int) -> tuple[asyncio.subprocess.Process, str]:
    """Start a cloudflared quick tunnel to the local web app and wait for its public https URL."""
    # a previous run that was killed hard can leave its tunnel behind; never run two for the same port
    stale = await asyncio.create_subprocess_exec("pkill", "-f", f"cloudflared tunnel --no-autoupdate --url http://127.0.0.1:{port}")
    await stale.wait()
    proc = await asyncio.create_subprocess_exec(
        "cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )

    async def find_url() -> str:
        while line := await proc.stderr.readline():
            if m := TUNNEL_URL.search(line.decode(errors="ignore")):
                return m.group(0)
        raise RuntimeError("cloudflared exited before printing a URL")

    url = await asyncio.wait_for(find_url(), timeout=45)

    async def drain() -> None:  # keep reading so cloudflared never blocks on a full pipe
        while await proc.stderr.readline():
            pass

    asyncio.get_running_loop().create_task(drain())
    return proc, url


async def serve(port: int, tunnel: bool) -> None:
    s = settings()
    conn = connect(s.db_path)
    if purged := tools.purge_expired_quotes(conn, now()):
        log.info("purged %s expired, unpaid quotes", purged)
    proc, public_url = None, s.public_base_url
    if tunnel:
        proc, public_url = await start_tunnel(port)
    if not public_url:
        log.warning("No public URL: share links are disabled. Use --tunnel or set PUBLIC_BASE_URL.")

    agent = Agent(anthropic.AsyncAnthropic(api_key=s.anthropic_api_key), conn, s.model)
    bot = build_application(s, conn, agent, public_url)
    server = uvicorn.Server(uvicorn.Config(create_app(conn), host="127.0.0.1", port=port, log_level="warning"))

    async with bot:
        await bot.start()
        await configure_bot(bot)
        await bot.updater.start_polling(drop_pending_updates=True)
        log.info("Agla Station @%s: web http://127.0.0.1:%s, public %s, model %s",
                 s.telegram_bot_username, port, public_url or "(none)", s.model)
        try:
            await server.serve()  # returns on Ctrl-C / SIGTERM
        finally:
            log.info("shutting down")
            await bot.updater.stop()
            await bot.stop()
            if proc and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except TimeoutError:
                    proc.kill()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--tunnel", action="store_true", help="start a cloudflared quick tunnel for public links")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "httpcore", "telegram.ext"):  # httpx URLs contain the bot token
        logging.getLogger(noisy).setLevel(logging.WARNING)

    s = settings()
    missing = [k for k, v in {"TELEGRAM_BOT_TOKEN": s.telegram_bot_token, "ANTHROPIC_API_KEY": s.anthropic_api_key,
                              "UPI_VPA": s.upi_vpa, "DASHBOARD_SECRET": s.dashboard_secret}.items() if not v]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)}")
    if len(s.dashboard_secret) < 32:
        raise SystemExit('DASHBOARD_SECRET is too short: python3 -c "import secrets; print(secrets.token_urlsafe(32))"')
    try:
        asyncio.run(serve(args.port, args.tunnel))
    except KeyboardInterrupt:  # Ctrl-C: serve() has already shut the bot and tunnel down
        pass


if __name__ == "__main__":
    main()
