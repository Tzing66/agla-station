"""Telegram front end. Handlers only: parse the update, call agla.tools / the LLM agent, render a template."""

from __future__ import annotations

import logging
import sqlite3
from html import escape
from urllib.parse import quote

import anthropic
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
    WebAppInfo,
)
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
from agla.bot.chatter import ChatterState
from agla.bot.limits import DAILY_CAP, SLOW_DOWN, RateLimiter
from agla.config import Settings, now
from agla.llm import MAX_HISTORY, Agent, narrate_wrapped

log = logging.getLogger(__name__)

PAID = "paid:"
LANG = "lang:"
REDEEM = "redeem:"
SHARE = "share:"
REACHED = "reached:"



class Bot:
    def __init__(self, settings: Settings, conn: sqlite3.Connection, agent: Agent, public_url: str) -> None:
        self.settings = settings
        self.conn = conn
        self.agent = agent
        self.public_url = public_url.rstrip("/")
        self.limiter = RateLimiter()

    def share_url(self, token: str) -> str | None:
        return f"{self.public_url}/s/{token}" if self.public_url else None

    def menu(self) -> ReplyKeyboardMarkup:
        """The persistent button menu. Dashboard opens the Mini App straight from the keyboard when we're public."""
        def button(label: str) -> KeyboardButton:
            if label == render.BTN_DASHBOARD and self.public_url.startswith("https://"):  # Mini Apps need https
                return KeyboardButton(label, web_app=WebAppInfo(url=f"{self.public_url}/app"))
            return KeyboardButton(label)
        return ReplyKeyboardMarkup([[button(lbl) for lbl in row] for row in render.MENU_ROWS], resize_keyboard=True,
                                   is_persistent=True, input_field_placeholder=render.INPUT_HINT)

    async def menu_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """A tap on the reply keyboard: route straight to the feature, no LLM call."""
        handler = {
            render.BTN_STATS: self.stats, render.BTN_MILES: self.miles, render.BTN_BADGES: self.badges,
            render.BTN_WRAPPED: self.wrapped, render.BTN_DASHBOARD: self.dashboard, render.BTN_LANGUAGE: self.language,
        }[update.message.text]
        await handler(update, context)

    def bot_link(self) -> str:
        return f"https://t.me/{self.settings.telegram_bot_username}"

    def user(self, update: Update) -> tools.User:
        tg = update.effective_user
        return tools.get_or_create_user(self.conn, tg.id, tg.first_name, now())

    # --- commands ---

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        await update.message.reply_html(render.WELCOME.format(name=escape(user.first_name)), reply_markup=self.menu())
        await update.message.reply_html(render.LANGUAGE_PROMPT, reply_markup=language_buttons(user.language))

    async def language(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        await update.message.reply_html(render.LANGUAGE_PROMPT, reply_markup=language_buttons(user.language))

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_html(render.HELP, reply_markup=self.menu())

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

    async def wrapped(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        month = context.args[0] if context.args else now().strftime("%Y-%m")
        try:
            stats = tools.wrapped_stats(self.conn, user.user_id, month)
        except tools.ToolError as exc:
            await update.message.reply_text(str(exc))
            return
        if not stats.trips:
            await update.message.reply_text(tools.template_text(stats))
            return
        await update.message.chat.send_action(ChatAction.UPLOAD_PHOTO)
        recap = tools.fresh_recap(self.conn, user.user_id, stats)
        if recap is None:
            try:
                text, guarded = await narrate_wrapped(self.agent.client, self.agent.model, stats, user.language,
                                                      tools.template_text(stats))
            except anthropic.APIError:
                log.exception("wrapped narration failed")
                text, guarded = tools.template_text(stats), True
            if not guarded:  # only cache real narration; a fallback should be retried next time
                tools.save_recap(self.conn, user.user_id, stats, text, now())
        else:
            text = recap.text
        await update.message.reply_photo(tools.render_card(stats),
                                         caption=render.wrapped_caption(stats, text), parse_mode=ParseMode.HTML)

    async def retired(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        command = update.message.text.split()[0].lstrip("/").split("@")[0]
        await update.message.reply_text(render.RETIRED[command], reply_markup=self.menu())

    # --- chat ---

    async def chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        text = update.message.text.strip()[:500]
        history: list[dict[str, str]] = context.chat_data.setdefault("history", [])
        chatter: ChatterState = context.chat_data.setdefault("chatter", ChatterState())
        metro_related = tools.is_metro_related(text)
        if chatter.should_skip_llm(metro_related):  # repeated off-topic chatter: no API call
            await update.message.reply_text(chatter.canned(user.language), reply_markup=self.menu())
            return
        if over := self.limiter.check(user.user_id, now()):  # only messages that would call Claude count
            msgs = DAILY_CAP if over == "day" else SLOW_DOWN
            await update.message.reply_text(msgs.get(user.language, msgs["en"]), reply_markup=self.menu())
            return
        await update.message.chat.send_action(ChatAction.TYPING)
        try:
            reply = await self.agent.respond(user, history, text, now())
        except anthropic.APIError:
            log.exception("LLM call failed")
            await update.message.reply_text("My brain's stuck between stations 😅 Try again in a moment?")
            return

        chatter.record(metro_related, reply.used_tools)
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply.history_text}]
        del history[:-MAX_HISTORY]

        await update.message.reply_text(reply.text, reply_markup=self.menu())  # keeps the menu for existing chats
        for quote_id in reply.quote_ids:
            await self.send_quote(update, quote_id)

    async def send_quote(self, update: Update, quote_id: str) -> None:
        quote = tools.get_quote(self.conn, quote_id)
        pay = tools.make_payment_link(quote, self.settings.upi_vpa, self.settings.upi_payee_name)
        button = InlineKeyboardMarkup([[InlineKeyboardButton("✅ I've paid", callback_data=PAID + quote_id)]])
        card = render.quote_card(quote, pay)
        if len(card) <= render.CAPTION_LIMIT:
            await update.message.reply_photo(pay.qr_png, caption=card, parse_mode=ParseMode.HTML, reply_markup=button)
        else:  # Telegram rejects photo captions over 1024 chars: QR with a short caption, then the full card
            await update.message.reply_photo(pay.qr_png, caption=render.quote_card_short(quote),
                                             parse_mode=ParseMode.HTML)
            await update.message.reply_html(card, reply_markup=button, disable_web_page_preview=True)

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
        trip_id = result.trip.trip_id
        buttons = [[InlineKeyboardButton("📤 Share journey", callback_data=f"{SHARE}{trip_id}"),
                    InlineKeyboardButton("✅ I've reached", callback_data=f"{REACHED}{trip_id}")]]
        caption = render.ticket_caption(result)
        await query.message.reply_photo(result.ticket_png, caption=caption, parse_mode=ParseMode.HTML,
                                        reply_markup=InlineKeyboardMarkup(buttons))

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

    async def dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = self.user(update)
        if not self.public_url.startswith("https://"):
            await update.message.reply_text("The dashboard needs a public https address (start with --tunnel).")
            return
        token = tools.sign_dashboard_token(user.telegram_id, self.settings.dashboard_secret)
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗺️ Open dashboard", web_app=WebAppInfo(url=f"{self.public_url}/app"))],
            [InlineKeyboardButton("Open in browser", url=f"{self.public_url}/app?t={token}")],
        ])
        await update.message.reply_html(
            "Your map, badges, Metro Miles, insights and Wrapped archive. "
            "<i>The browser link is personal and works for 7 days.</i>", reply_markup=buttons)

    # --- sharing & arrival ---

    async def share(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        try:
            trip_id = int(query.data.removeprefix(SHARE))
            token = tools.create_share(self.conn, trip_id, query.from_user.id, now())
        except (ValueError, tools.ToolError) as exc:
            await query.answer(str(exc)[:190], show_alert=True)
            return
        url = self.share_url(token)
        if url is None:
            await query.answer("Sharing needs a public web address (start with --tunnel).", show_alert=True)
            return
        await query.answer()
        user = self.user(update)
        text = tools.share_message(user.first_name, tools.get_trip(self.conn, trip_id), url)
        await query.message.reply_text(
            f"{text}\n\n<i>The page shows a timetable estimate and your first name only, and stops working after "
            "the trip.</i>", parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            reply_markup=send_to_button(url, text.replace(f" Track me: {url}", "")))

    async def reached(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """'I've reached': mark the trip arrived and hand back a message the traveller sends to whoever they want."""
        query = update.callback_query
        try:
            trip_id = int(query.data.removeprefix(REACHED))
            res = tools.confirm_arrival(self.conn, trip_id, query.from_user.id, now())
        except (ValueError, tools.ToolError) as exc:
            await query.answer(str(exc)[:190], show_alert=True)
            return
        await query.answer("Already marked as reached ✅" if res["already"] else "Glad you made it! ✅")
        miles = f"\n+{res['miles']} Metro Miles for letting someone know." if res["miles"] else ""
        share = self.conn.execute("SELECT token FROM shares WHERE trip_id = ?", (trip_id,)).fetchone()
        url = self.share_url(share["token"]) if share else None
        await query.message.reply_text(
            f"{res['message']}{miles}\n\n<i>Tap Send to… and pick who should know.</i>",
            parse_mode=ParseMode.HTML, reply_markup=send_to_button(url or self.bot_link(), res["message"]))

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("update failed", exc_info=context.error)


def send_to_button(url: str, text: str) -> InlineKeyboardMarkup:
    """Telegram's own share sheet: the traveller picks the chat; the bot never messages anyone on its own."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        "📨 Send to…", url=f"https://t.me/share/url?url={quote(url, safe='')}&text={quote(text, safe='')}")]])


def language_buttons(current: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(("✓ " if code == current else "") + label, callback_data=LANG + code)
        for code, label in tools.LANGUAGES.items()
    ]])


def build_application(settings: Settings, conn: sqlite3.Connection, agent: Agent, public_url: str = "") -> Application:
    bot = Bot(settings, conn, agent, public_url or settings.public_base_url)
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("help", bot.help))
    app.add_handler(CommandHandler("stats", bot.stats))
    app.add_handler(CommandHandler("language", bot.language))
    app.add_handler(CommandHandler("miles", bot.miles))
    app.add_handler(CommandHandler("badges", bot.badges))
    app.add_handler(CommandHandler("wrapped", bot.wrapped))
    app.add_handler(CommandHandler("dashboard", bot.dashboard))
    app.add_handler(CommandHandler(list(render.RETIRED), bot.retired))
    app.add_handler(CallbackQueryHandler(bot.paid, pattern=f"^{PAID}"))
    app.add_handler(CallbackQueryHandler(bot.set_language, pattern=f"^{LANG}"))
    app.add_handler(CallbackQueryHandler(bot.redeem, pattern=f"^{REDEEM}"))
    app.add_handler(CallbackQueryHandler(bot.share, pattern=f"^{SHARE}"))
    app.add_handler(CallbackQueryHandler(bot.reached, pattern=f"^{REACHED}"))
    new_messages = filters.UpdateType.MESSAGE  # edited messages have no update.message; ignore them
    app.add_handler(MessageHandler(new_messages & filters.Text([lbl for row in render.MENU_ROWS for lbl in row]),
                                   bot.menu_button))
    app.add_handler(MessageHandler(new_messages & filters.TEXT & ~filters.COMMAND, bot.chat))
    app.add_error_handler(bot.on_error)
    return app


async def configure_bot(app: Application) -> None:
    """Startup: the command menu shrinks to /start (everything else lives in the button keyboard)."""
    await app.bot.set_my_commands([BotCommand("start", "Show the menu"), BotCommand("help", "What I can do")])
