"""Run Agla Station: `uv run python -m agla`.

Phase 4: the Telegram bot (long polling). The FastAPI app for share pages and the Mini App joins this
process in Phase 8/9 (docs/architecture.md: one process, one SQLite writer).
"""

from __future__ import annotations

import logging

import anthropic

from agla.bot.app import build_application
from agla.config import settings
from agla.db import connect
from agla.llm import Agent


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "httpcore", "telegram.ext"):  # httpx logs request URLs, which hold the bot token
        logging.getLogger(noisy).setLevel(logging.WARNING)

    s = settings()
    missing = [k for k, v in {"TELEGRAM_BOT_TOKEN": s.telegram_bot_token, "ANTHROPIC_API_KEY": s.anthropic_api_key,
                              "UPI_VPA": s.upi_vpa}.items() if not v]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)}")

    conn = connect(s.db_path)
    agent = Agent(anthropic.AsyncAnthropic(api_key=s.anthropic_api_key), conn, s.model)
    app = build_application(s, conn, agent)
    logging.getLogger("agla").info("Agla Station bot @%s starting (db %s, model %s)",
                                   s.telegram_bot_username, s.db_path.name, s.model)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
