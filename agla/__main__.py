"""Run Agla Station: the Telegram bot and the web app (share pages, dashboard Mini App) in one process.

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
import httpx
import uvicorn

from agla import tools
from agla.bot.app import build_application, configure_bot, set_public_url
from agla.config import now, settings
from agla.db import connect
from agla.llm import Agent
from agla.web.app import create_app

log = logging.getLogger("agla")
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
PROBE_EVERY = 30  # seconds
PROBE_FAILURES = 3  # consecutive failed probes before the tunnel is replaced


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


class Tunnel:
    """A quick tunnel that replaces itself when it dies. Quick tunnels don't survive the laptop sleeping: cloudflared
    keeps running but the hostname stops resolving, so we probe the public URL rather than trust the process."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.proc: asyncio.subprocess.Process | None = None
        self.url = ""

    async def start(self) -> str:
        self.proc, self.url = await start_tunnel(self.port)
        return self.url

    async def healthy(self, http: httpx.AsyncClient) -> bool:
        if self.proc is None or self.proc.returncode is not None:
            return False
        try:
            return (await http.get(f"{self.url}/healthz")).status_code == 200
        except httpx.HTTPError:
            return False

    async def watch(self, on_new_url) -> None:
        failures = 0
        async with httpx.AsyncClient(timeout=10) as http:
            while True:
                await asyncio.sleep(PROBE_EVERY)
                failures = 0 if await self.healthy(http) else failures + 1
                if failures < PROBE_FAILURES:
                    continue
                log.warning("tunnel %s is unreachable; starting a new one", self.url)
                try:
                    await self.start()  # start_tunnel kills the dead cloudflared first
                except (RuntimeError, TimeoutError):
                    log.exception("could not start a new tunnel; retrying in %ss", PROBE_EVERY)
                    continue
                await on_new_url(self.url)
                log.info("new public URL %s", self.url)
                failures = 0

    async def stop(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except TimeoutError:
                self.proc.kill()


async def serve(port: int, tunnel: bool) -> None:
    s = settings()
    conn = connect(s.db_path)
    if purged := tools.purge_expired_quotes(conn, now()):
        log.info("purged %s expired, unpaid quotes", purged)
    tun = Tunnel(port) if tunnel else None
    public_url = await tun.start() if tun else s.public_base_url
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
        watchdog = asyncio.create_task(tun.watch(lambda url: set_public_url(bot, url))) if tun else None
        try:
            await server.serve()  # returns on Ctrl-C / SIGTERM
        finally:
            log.info("shutting down")
            if watchdog:
                watchdog.cancel()
            await bot.updater.stop()
            await bot.stop()
            if tun:
                await tun.stop()


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
