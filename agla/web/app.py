"""FastAPI front end: public journey-share pages (Phase 8); the dashboard Mini App joins in Phase 9.

Thin: every route reads from agla.tools and renders a template. No business logic here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agla import tools
from agla.config import Settings, now, settings

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
PRIVATE_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",  # share links must never show up in search results
    "Referrer-Policy": "no-referrer",  # don't leak the token to other sites
    "Cache-Control": "no-store",
}


class RedeemBody(BaseModel):
    reward_id: str


def create_app(conn: sqlite3.Connection, cfg: Settings | None = None) -> FastAPI:
    """All handlers are `async def` on purpose: they then run on the event loop, the same thread as the bot, so the
    shared SQLite connection is never used by two threads at once (sync handlers would run in a thread pool)."""
    cfg = cfg or settings()
    app = FastAPI(title="Agla Station", docs_url=None, redoc_url=None, openapi_url=None)

    async def rider(request: Request) -> tools.User:
        """Dashboard auth: Telegram Mini App initData, or a signed magic link for normal browsers."""
        try:
            if init := request.headers.get("X-Telegram-Init-Data"):
                tg = tools.verify_init_data(init, cfg.telegram_bot_token, now())
                return tools.get_or_create_user(conn, int(tg["id"]), tg.get("first_name"), now())
            if token := request.headers.get("X-Dashboard-Token"):
                user = tools.find_user_by_telegram_id(conn, tools.verify_dashboard_token(token, cfg.dashboard_secret))
                if user:
                    return user
        except tools.ToolError as exc:
            raise HTTPException(401, str(exc)) from exc
        raise HTTPException(401, "Open the dashboard from the bot with /dashboard.")

    Rider = Depends(rider)

    @app.get("/app", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(request, "app.html", {}, headers=PRIVATE_HEADERS)

    @app.get("/api/me")
    async def me(user: tools.User = Rider) -> dict:
        s = tools.get_stats(conn, user.user_id)
        return {"first_name": user.first_name, "stats": s.to_dict(),
                "miles": tools.get_miles(conn, user.user_id, recent=0).balance,
                "badges_earned": sum(1 for b in tools.get_badges(conn, user.user_id) if b.earned_at)}

    @app.get("/api/map")
    async def map_(user: tools.User = Rider) -> dict:
        return tools.map_data(conn, user.user_id)

    @app.get("/api/badges")
    async def badges(user: tools.User = Rider) -> list[dict]:
        return [b.to_dict() for b in tools.get_badges(conn, user.user_id)]

    @app.get("/api/miles")
    async def miles(user: tools.User = Rider) -> dict:
        return {**tools.get_miles(conn, user.user_id, recent=15).to_dict(),
                "rewards": [r.to_dict() for r in tools.list_rewards()],
                "vouchers": [v.to_dict() for v in tools.list_vouchers(conn, user.user_id)]}

    @app.post("/api/redeem")
    async def redeem(body: RedeemBody, user: tools.User = Rider) -> dict:
        try:
            voucher = tools.redeem_reward(conn, user.user_id, body.reward_id, now())
        except tools.ToolError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"voucher": voucher.to_dict(), "balance": tools.get_miles(conn, user.user_id, recent=0).balance}

    @app.get("/api/insights")
    async def insights(user: tools.User = Rider) -> dict:
        return tools.insights(conn, user.user_id, now().date())

    @app.get("/api/wrapped")
    async def wrapped(user: tools.User = Rider) -> list[dict]:
        """Every month with trips. Saved recap text if the rider ran /wrapped, else the plain template (no LLM)."""
        out = []
        for month in tools.trip_months(conn, user.user_id):
            stats = tools.wrapped_stats(conn, user.user_id, month)
            recap = tools.get_recap(conn, user.user_id, month)
            out.append({"month": month, "month_name": stats.month_name,
                        "text": recap.text if recap else tools.template_text(stats),
                        "trips": stats.trips, "km": stats.total_km, "miles": stats.miles_earned})
        return out

    @app.get("/api/wrapped/{month}/card.png")
    async def wrapped_card(month: str, user: tools.User = Rider) -> Response:
        try:
            stats = tools.wrapped_stats(conn, user.user_id, month)
        except tools.ToolError as exc:
            raise HTTPException(400, str(exc)) from exc
        return Response(tools.render_card(stats), media_type="image/png", headers=PRIVATE_HEADERS)

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(request, "home.html", {})

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        return "ok"

    @app.get("/s/{token}", response_class=HTMLResponse)
    async def share(request: Request, token: str) -> HTMLResponse:
        view = tools.get_share_view(conn, token, now())
        name = "share.html" if view else "ended.html"
        return TEMPLATES.TemplateResponse(request, name, {"v": view, "token": token},
                                          status_code=200 if view else 410, headers=PRIVATE_HEADERS)

    @app.get("/s/{token}/status", response_class=HTMLResponse)
    async def share_status(request: Request, token: str) -> HTMLResponse:
        """HTMX fragment polled every 30 s; when the link has expired, the page switches to 'journey ended'."""
        view = tools.get_share_view(conn, token, now())
        if view is None:
            return HTMLResponse('<div id="status" class="ended-inline">This journey has ended.</div>',
                                headers={**PRIVATE_HEADERS, "HX-Refresh": "true"})
        return TEMPLATES.TemplateResponse(request, "_status.html", {"v": view, "token": token},
                                          headers=PRIVATE_HEADERS)

    return app
