"""Telegram message templates. Presentation only: every number is read from a tool-layer object."""

from __future__ import annotations

from datetime import datetime
from html import escape

from agla import tools

DEMO_NOTE = "<i>Demo: payment isn't verified and tickets aren't valid for travel.</i>"


def _name(station_id: str) -> str:
    return escape(tools.get_station(station_id).name)


def _hm(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%-I:%M %p")


CAPTION_LIMIT = 1024  # Telegram's limit for photo captions


def quote_card_short(quote: tools.Quote) -> str:
    return (f"🚇 <b>{_name(quote.route.from_id)} → {_name(quote.route.to_id)}</b> · <b>₹{quote.fare.total}</b>\n"
            "Scan to pay with any UPI app. Route and payment link below 👇")


def quote_card(quote: tools.Quote, pay: tools.PaymentLink) -> str:
    r, f = quote.route, quote.fare
    lines = [f"🚇 <b>{_name(r.from_id)} → {_name(r.to_id)}</b>"]
    for leg in r.legs:
        if leg.line_id == "WALK":
            lines.append(f"🚶 {escape(leg.line_name)} (~{leg.minutes:.0f} min)")
        else:
            stops = len(leg.station_ids) - 1
            lines.append(f"• {escape(leg.line_name)}: {_name(leg.from_id)} → {_name(leg.to_id)}, "
                         f"{stops} stop{'s' if stops != 1 else ''}")
    changes = len(r.interchange_ids)
    change_txt = "no changes" if not changes else "change at " + ", ".join(_name(s) for s in r.interchange_ids)
    lines += [
        f"⏱ ~{r.minutes} min · {r.distance_km} km · {change_txt}",
        f"💰 <b>₹{f.total}</b> ({f.day_type.replace('_', '/')} fare"
        + (", " + " + ".join(f"{c.operator} ₹{c.amount}" for c in f.components) if len(f.components) > 1 else "")
        + ")",
        "",
        f"Pay <b>{escape(pay.payee_name)}</b> with any UPI app: scan this QR (or save it and scan from your gallery), "
        "or copy the link:",
        f"<code>{escape(pay.upi_uri)}</code>",
        "",
        "Then tap <b>✅ I've paid</b> for your ticket.",
        DEMO_NOTE,
    ]
    return "\n".join(lines)


def ticket_caption(result: tools.TripResult) -> str:
    t = result.trip
    if result.already_logged:
        return f"🎫 You already have this ticket: <b>{t.ticket_id}</b> (DEMO)."
    lines = [
        f"🎫 <b>Ticket {t.ticket_id}</b> (DEMO)",
        f"{_name(t.route.from_id)} → {_name(t.route.to_id)} · ₹{t.fare.total}",
        f"Departs {_hm(t.depart_at)} · estimated arrival <b>{_hm(t.eta)}</b>",
    ]
    if result.new_visits:
        lines.append("🆕 First time at: " + ", ".join(escape(n) for n in result.new_visits))
    miles = result.hook_results.get("miles")
    if miles and miles["total"]:
        parts = ", ".join(escape(a["reason"]) for a in miles["awards"][1:])
        lines.append(f"✨ <b>+{miles['total']} Metro Miles</b>" + (f" ({parts})" if parts else ""))
    for b in result.hook_results.get("badges", []):
        lines.append(f"🏅 New badge: <b>{escape(b['name'])}</b> ({escape(b['description'])})")
    lines.append("Agla station... happy journey! 🚇")
    return "\n".join(lines)


def _date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%-d %b")


def miles_text(m: tools.MilesSummary, rewards: list[tools.Reward], vouchers: list[tools.Voucher]) -> str:
    lines = [f"✨ <b>{m.balance} Metro Miles</b> (earned {m.earned_total} in total)", ""]
    if m.recent:
        lines.append("<b>Recent</b>")
        lines += [f"{a.delta:+d} · {escape(a.reason)} · {_date(a.created_at)}" for a in m.recent]
        lines.append("")
    lines.append("<b>Rewards</b> (tap to redeem)")
    lines += [f"{'✅' if m.balance >= r.cost else '🔒'} {escape(r.name)}: {r.cost}" for r in rewards]
    if vouchers:
        lines += ["", "<b>Your vouchers</b>"]
        lines += [f"🎟 <code>{v.code}</code> {escape(v.name)} · {_date(v.created_at)}" for v in vouchers]
    lines += ["", "<i>Metro Miles are a concept demo: vouchers are not redeemable.</i>"]
    return "\n".join(lines)


def voucher_text(v: tools.Voucher, balance: int) -> str:
    return (f"🎟 <b>{escape(v.name)}</b>\nCode: <code>{v.code}</code> · {v.miles_spent} Metro Miles spent · "
            f"{balance} left\n<b>{escape(v.label)}</b>")


def badges_text(badges: list[tools.BadgeStatus]) -> str:
    earned = sorted((b for b in badges if b.earned_at), key=lambda b: b.earned_at)
    core_locked = [b for b in badges if not b.earned_at and not b.badge_id.startswith("line_collector_")]
    collectors_locked = sum(1 for b in badges if not b.earned_at and b.badge_id.startswith("line_collector_"))
    lines = [f"🏅 <b>Badges: {len(earned)} of {len(badges)}</b>", ""]
    lines += [f"✅ <b>{escape(b.name)}</b> · {escape(b.description)} · {_date(b.earned_at)}" for b in earned]
    if core_locked:
        lines += ["", "<b>Still to unlock</b>"]
        lines += [f"🔒 {escape(b.name)}: {escape(b.hint)}" for b in core_locked]
    if collectors_locked:
        lines.append(f"🔒 Line Collector ({collectors_locked} lines): visit every station on a line.")
    return "\n".join(lines)


def stats_text(s: tools.Stats) -> str:
    if not s.trips:
        return "No trips yet. Tell me where you're headed, e.g. <i>rajiv chowk to hauz khas</i>."
    hours, mins = divmod(s.total_minutes, 60)
    top = ", ".join(f"{escape(n)} ({c})" for n, c in s.top_stations)
    return "\n".join([
        "📊 <b>Your metro stats</b>",
        f"Trips: <b>{s.trips}</b> · stations visited: <b>{s.unique_stations}</b>",
        f"Time on the metro: <b>{hours}h {mins}m</b> · distance: <b>{s.total_km} km</b>",
        f"Spent: <b>₹{s.total_fare}</b>",
        f"Favourite line: <b>{escape(s.favourite_line or '-')}</b>",
        f"Top stations: {top}",
        f"States: {', '.join(s.states_visited)}",
    ])


# Persistent menu buttons (a reply keyboard): tapping one works like a command, no slashes to remember.
BTN_STATS, BTN_MILES, BTN_BADGES = "📊 My stats", "✨ Miles", "🏅 Badges"
BTN_WRAPPED, BTN_DASHBOARD, BTN_LANGUAGE = "🎁 Wrapped", "🗺️ Dashboard", "🌐 Language"
MENU_ROWS = [[BTN_STATS, BTN_MILES, BTN_BADGES], [BTN_WRAPPED, BTN_DASHBOARD, BTN_LANGUAGE]]
INPUT_HINT = "Where to? e.g. RC se Hauz Khas"

LANGUAGE_PROMPT = "Which language should I reply in? / किस भाषा में जवाब दूँ?"
LANGUAGE_SET = {
    "en": "Done! I'll reply in English. Change any time with /language.",
    "hinglish": "Done! Ab main Hinglish mein reply karunga. Badalna ho to /language.",
    "hi": "हो गया! अब मैं हिंदी में जवाब दूँगा। बदलने के लिए /language भेजें।",
}

WELCOME = (
    "Namaste {name}! 🚇 I'm <b>Agla Station</b>, your Delhi NCR metro buddy.\n\n"
    "Just type where you're going:\n"
    "• <i>rajiv chowk to hauz khas</i>\n"
    "• <i>RC se botanical garden, sasta wala</i>\n"
    "• <i>cyber hub to noida sec 18, kam change</i>\n\n"
    "I'll find the route and fare, send a UPI payment QR, and give you a (demo) ticket. "
    "Everything else is in the buttons below 👇"
)

HELP = (
    "<b>What I can do</b>\n"
    "• Plan any trip on DMRC, Airport Express, Rapid Metro Gurugram and the Noida Aqua Line: just type it\n"
    "• Fastest, fewest changes or cheapest (\"sasta\") route\n"
    "• UPI payment link + demo QR ticket, with 📤 Share journey and ✅ I've reached\n\n"
    "<b>Buttons below</b>\n"
    "📊 your trips · ✨ Metro Miles and rewards · 🏅 badges\n"
    "🎁 monthly Wrapped · 🗺️ map and insights · 🌐 English, Hinglish or हिंदी\n\n"
    + DEMO_NOTE
)

RETIRED = {  # commands that were replaced; still answered so old menus and habits don't hit silence
    "safety": "The safety check is now simpler: tap ✅ I've reached on your ticket and send the message to "
              "whoever's waiting. 📤 Share journey sends them a live link while you travel.",
    "trusted": "No contacts to set up any more: tap ✅ I've reached on your ticket and pick who to tell.",
    "demo_fast": "Not needed any more: there are no timed safety messages.",
}


def wrapped_caption(stats: tools.WrappedStats, text: str) -> str:
    # cut the plain text before escaping, so the 1024-char caption limit can't split an HTML entity
    return f"<b>{escape(stats.month_name)}</b>\n{escape(text[:900])}"
