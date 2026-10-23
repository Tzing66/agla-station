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
    lines.append("Agla station... happy journey! 🚇")
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


LANGUAGE_PROMPT = "Which language should I reply in? / किस भाषा में जवाब दूँ?"
LANGUAGE_SET = {
    "en": "Done! I'll reply in English. Change any time with /language.",
    "hinglish": "Done! Ab main Hinglish mein reply karunga. Badalna ho to /language.",
    "hi": "हो गया! अब मैं हिंदी में जवाब दूँगा। बदलने के लिए /language भेजें।",
}

WELCOME = (
    "Namaste {name}! 🚇 I'm <b>Agla Station</b>, your Delhi NCR metro buddy.\n\n"
    "Tell me where you're going in plain words:\n"
    "• <i>rajiv chowk to hauz khas</i>\n"
    "• <i>RC se botanical garden, sasta wala</i>\n"
    "• <i>cyber hub to noida sec 18, kam change</i>\n\n"
    "I'll find the route and fare, send a UPI payment QR, and give you a (demo) ticket. "
    "Try /help for everything else."
)

HELP = (
    "<b>What I can do</b>\n"
    "• Plan any trip on DMRC, Airport Express, Rapid Metro Gurugram and the Noida Aqua Line\n"
    "• Fastest, fewest changes or cheapest route\n"
    "• UPI payment link + demo QR ticket\n\n"
    "<b>Commands</b>\n"
    "/stats your trips · /badges · /miles · /wrapped monthly recap\n"
    "/language English, Hinglish or हिंदी\n"
    "/dashboard your map and insights · /safety arrival check · /trusted invite a contact\n\n"
    + DEMO_NOTE
)

COMING_SOON = {
    "badges": "🏅 Badges are coming soon. Keep riding: your trips already count!",
    "miles": "✨ Metro Miles are coming soon. Your trips already count towards them!",
    "wrapped": "🎁 Metro Wrapped, your monthly recap, is coming soon.",
    "dashboard": "🗺 Your dashboard is coming soon.",
    "trusted": "🤝 Trusted contacts are coming soon.",
    "safety": "🛟 The \"I've reached\" safety check is coming soon.",
}
