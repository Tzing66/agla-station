"""Telegram front end. Handlers only: parse the update, call agla.tools / the LLM agent, render a template."""

from __future__ import annotations

import logging
import sqlite3

import anthropic
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agla import tools
from agla.bot import render
from agla.config import Settings, now
from agla.llm import MAX_HISTORY, Agent

log = logging.getLogger(__name__)

PAID = "paid:"
LANG = "lang:"
REDEEM = "redeem:"


class Bot:
    def __init__(self, settings: Settings, conn: sqlite3.Connection, agent: Agent) -> None:
        self.settings = settings
        self.conn = conn
        self.agent = agent

    def user(self, update: Update) -> tools.User:
        tg = update.effective_user
        return tools.get_or_create_user(self.conn, tg.id, tg.first_name, now())

    # --- commands ---

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        await update.message.reply_html(render.WELCOME.format(name=user.first_name))
        await update.message.reply_html(render.LANGUAGE_PROMPT, reply_markup=language_buttons(user.language))

    async def language(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        await update.message.reply_html(render.LANGUAGE_PROMPT, reply_markup=language_buttons(user.language))

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_html(render.HELP)

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        await update.message.reply_html(render.stats_text(tools.get_stats(self.conn, user.user_id)))

    async def miles(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        await update.message.reply_html(**self._miles_view(user))

    def _miles_view(self, user: tools.User) -> dict:
        m = tools.get_miles(self.conn, user.user_id)
        rewards = tools.list_rewards()
        buttons = [[InlineKeyboardButton(f"Redeem: {r.name} ({r.cost})", callback_data=REDEEM + r.reward_id)]
                   for r in rewards if m.balance >= r.cost]
        return {"text": render.miles_text(m, rewards, tools.list_vouchers(self.conn, user.user_id)),
                "reply_markup": InlineKeyboardMarkup(buttons) if buttons else None}

    async def badges(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        await update.message.reply_html(render.badges_text(tools.get_badges(self.conn, user.user_id)))

    async def redeem(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user = self.user(update)
        try:
            voucher = tools.redeem_reward(self.conn, user.user_id, query.data.removeprefix(REDEEM), now())
        except tools.ToolError as exc:
            await query.answer(str(exc)[:190], show_alert=True)
            return
        await query.answer("Redeemed (demo) 🎟")
        balance = tools.get_miles(self.conn, user.user_id, recent=0).balance
        await query.message.reply_html(render.voucher_text(voucher, balance))
        await query.edit_message_text(parse_mode=ParseMode.HTML, **self._miles_view(user))

    async def coming_soon(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        command = update.message.text.split()[0].lstrip("/").split("@")[0]
        await update.message.reply_html(render.COMING_SOON.get(command, "Coming soon."))

    # --- chat ---

    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        text = update.message.text.strip()[:500]
        history: list[dict[str, str]] = context.chat_data.setdefault("history", [])
        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            reply = await self.agent.respond(user, history, text, now())
        except anthropic.APIError:
            log.exception("LLM call failed")
            await update.message.reply_text("My brain's stuck between stations 😅 Try again in a moment?")
            return

        history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply.history_text}]
        del history[:-MAX_HISTORY]

        await update.message.reply_text(reply.text)
        for quote_id in reply.quote_ids:
            await self.send_quote(update, quote_id)

    async def send_quote(self, update: Update, quote_id: str) -> None:
        quote = tools.get_quote(self.conn, quote_id)
        pay = tools.make_payment_link(quote, self.settings.upi_vpa, self.settings.upi_payee_name)
        button = InlineKeyboardMarkup([[InlineKeyboardButton("✅ I've paid", callback_data=PAID + quote_id)]])
        await update.message.reply_photo(
            pay.qr_png, caption=render.quote_card(quote, pay), parse_mode=ParseMode.HTML, reply_markup=button
        )

    # --- buttons ---

    async def paid(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        quote_id = query.data.removeprefix(PAID)
        try:
            result = tools.log_trip(self.conn, quote_id, query.from_user.id, now())
        except tools.ToolError as exc:
            await query.answer(str(exc)[:190], show_alert=True)
            return
        await query.answer("Ticket issued 🎫" if not result.already_logged else "Already issued")
        if not result.already_logged:
            await query.edit_message_reply_markup(None)  # one ticket per quote
        await query.message.reply_photo(result.ticket_png, caption=render.ticket_caption(result),
                                        parse_mode=ParseMode.HTML)

    async def set_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user = self.user(update)
        try:
            user = tools.set_language(self.conn, user.user_id, query.data.removeprefix(LANG))
        except tools.ToolError as exc:
            await query.answer(str(exc)[:190], show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(render.LANGUAGE_SET[user.language], parse_mode=ParseMode.HTML)

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("update failed", exc_info=context.error)


def language_buttons(current: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(("✓ " if code == current else "") + label, callback_data=LANG + code)
        for code, label in tools.LANGUAGES.items()
    ]])


def build_application(settings: Settings, conn: sqlite3.Connection, agent: Agent) -> Application:
    bot = Bot(settings, conn, agent)
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("help", bot.help))
    app.add_handler(CommandHandler("stats", bot.stats))
    app.add_handler(CommandHandler("language", bot.language))
    app.add_handler(CommandHandler("miles", bot.miles))
    app.add_handler(CommandHandler("badges", bot.badges))
    app.add_handler(CommandHandler(list(render.COMING_SOON), bot.coming_soon))
    app.add_handler(CallbackQueryHandler(bot.paid, pattern=f"^{PAID}"))
    app.add_handler(CallbackQueryHandler(bot.set_language, pattern=f"^{LANG}"))
    app.add_handler(CallbackQueryHandler(bot.redeem, pattern=f"^{REDEEM}"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.chat))
    app.add_error_handler(bot.on_error)
    return app
