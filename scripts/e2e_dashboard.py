"""End-to-end check of the dashboard Mini App and a share page in a real (headless) browser.

    uv run python -m scripts.e2e_dashboard [--base http://127.0.0.1:8000] [--redeem] [--light-only]

Needs the server running (`uv run python -m agla`) and the demo rider seeded (`scripts.seed_demo`).
Clicks every tab at phone size in light and dark mode, optionally redeems the cheapest affordable reward,
opens a share page, fails on any console error, and saves screenshots to docs/screenshots/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from agla import tools
from agla.config import settings

SHOTS = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
TABS = ["map", "badges", "miles", "insights", "wrapped"]
PHONE = {"width": 390, "height": 844}


def check_tabs(page: Page, scheme: str, errors: list[str], redeem: bool) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("#lines li")  # map tab rendered
    for tab in TABS:
        page.click(f"nav button[data-tab='{tab}']")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)  # charts / map tiles settle
        section = page.locator(f"#tab-{tab}")
        assert section.is_visible(), f"{tab} tab not visible"
        assert "state" not in (section.inner_html()[:200]), f"{tab} tab shows an error state"
        if tab == "miles" and redeem and scheme == "light":
            buttons = page.locator("#rewards button:not([disabled])")
            if buttons.count():
                page.once("dialog", lambda d: d.accept())  # confirm() outside Telegram
                buttons.first.click()
                page.wait_for_selector(".voucher")
                print("  redeemed:", page.locator(".voucher").inner_text().replace("\n", " | "))
        page.screenshot(path=str(SHOTS / f"dashboard-{tab}-{scheme}.png"), full_page=True)
        print(f"  {scheme:5} {tab:9} ok")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://127.0.0.1:8000")
    p.add_argument("--redeem", action="store_true", help="redeem the cheapest affordable reward (changes demo data)")
    p.add_argument("--light-only", action="store_true")
    args = p.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    token = tools.sign_dashboard_token(tools.DEMO_TELEGRAM_ID, settings().dashboard_secret)

    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for scheme in ["light"] if args.light_only else ["light", "dark"]:
            ctx = browser.new_context(viewport=PHONE, device_scale_factor=2, color_scheme=scheme)
            page = ctx.new_page()
            page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.goto(f"{args.base}/app?t={token}")
            check_tabs(page, scheme, errors, args.redeem)
            ctx.close()

        # an ended or unknown share link shows the "journey has ended" page (live pages are covered by tests)
        ctx = browser.new_context(viewport=PHONE, device_scale_factor=2)
        page = ctx.new_page()
        page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        page.goto(f"{args.base}/s/ended-or-unknown-token")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SHOTS / "share-ended.png"), full_page=True)
        print("  share page:", page.locator("h1").inner_text())
        browser.close()

    real = [e for e in errors if "status of 410" not in e]  # an ended share page answers 410 on purpose
    if real:
        print("console errors:\n  " + "\n  ".join(real))
        return 1
    print(f"no console errors; screenshots in {SHOTS.relative_to(SHOTS.parents[1])}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
