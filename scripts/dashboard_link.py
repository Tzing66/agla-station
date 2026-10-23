"""Print a signed dashboard link (works in any browser for 7 days).

    uv run python -m scripts.dashboard_link                         # demo rider, local server
    uv run python -m scripts.dashboard_link --base https://x.trycloudflare.com --telegram-id 123
"""

from __future__ import annotations

import argparse

from agla import tools
from agla.config import settings


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default=settings().public_base_url or "http://127.0.0.1:8000")
    p.add_argument("--telegram-id", type=int, default=tools.DEMO_TELEGRAM_ID)
    args = p.parse_args()
    token = tools.sign_dashboard_token(args.telegram_id, settings().dashboard_secret)
    print(f"{args.base.rstrip('/')}/app?t={token}")


if __name__ == "__main__":
    main()
