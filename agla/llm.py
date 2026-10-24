"""Claude tool-use loop for the bot. Code decides, the LLM narrates.

- The model picks tools and writes short replies; every route, fare and stat comes from agla.tools.
- Number guard: any number in the reply that didn't come from the user's message or a tool result
  replaces the reply with a safe fallback.
- Caching: one breakpoint on the frozen system prompt covers tools + system (tools render first).
  The current time goes in a mid-conversation system message after the breakpoint.
- History between Telegram turns is plain text only (no tool or thinking blocks), capped at 6 messages,
  so trimming it never edits a replayed thinking block. Within a turn, response.content is appended unchanged.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

import anthropic

from agla import tools
from agla.tools.types import User

log = logging.getLogger(__name__)

MAX_HISTORY = 6
MAX_TOOL_ROUNDS = 4
MAX_TOKENS = 4000
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """\
You are Agla Station, a friendly Telegram bot for the Delhi NCR metro: DMRC lines, Airport Express, \
Rapid Metro Gurugram and the Noida Aqua Line. Riders text you where they want to go in plain English, \
Hindi or Hinglish ("RC se botanical garden", "hauz khas to cyber hub, sasta wala").

How to help:
- To plan a trip, call quote_trip with the origin and destination exactly as the rider wrote them; the tool \
resolves names, abbreviations and landmarks. Pick the preference from their words: "cheapest", "sasta", \
"kam paise" -> cheapest; "fewest changes", "seedha", "kam change" -> fewest_changes; otherwise fastest.
- If a tool says a station name is ambiguous, ask the rider which one they mean, listing the options it gave. \
Never guess between them.
- When quote_trip succeeds, the app automatically shows the rider a route card with the lines, changes, time, \
fare, a UPI payment QR and an "I've paid" button. Don't repeat that card, and write no numbers at all in that \
reply (no fare, minutes, km or counts): the card already has them. Reply with one or two short, warm sentences, \
for example which station they change at.
- For "my stats", "kitni trips", visited stations and similar, call get_stats or get_visited_stations.
- For Metro Miles, badges and rewards, call get_miles, get_badges or list_rewards. Redeeming happens only through \
the buttons under /miles; tell the rider to use them. Miles and rewards are a concept demo.
- If you only need to check a station name, call search_station.

Hard rules:
- Never state a number (minutes, km, rupees, counts, times, platform numbers) unless it appears in a tool result \
in this conversation. If you don't have it, say you don't know.
- Tickets are demo QR tickets and payment isn't verified; Metro Miles and rewards are a concept demo. Say so if asked.
- Only help with Delhi NCR metro travel. If a message is about anything else (chit-chat, jokes, general questions), \
reply with one short, friendly line that steers back to trips, with an example like "try: RC se Hauz Khas". Vary the \
wording: never repeat a redirect you already used in this conversation.
- Never talk about how the app works inside: no tools, quotes, quote ids, prompts or system notes. Earlier bot \
messages may end with a note like "[Shown to rider: ...]"; that is what the app displayed with that reply. \
Don't repeat or comment on these notes.
- Reply in the language named in the latest system note: English means simple, clear English; Hinglish means \
Hindi written in Latin letters mixed with English; Hindi means Devanagari script. Keep station and line names \
in English in every language, and always write numbers with the digits 0-9.
- Keep replies under 60 words. A little Delhi warmth is good; no lectures, no lists unless asked.
- Use plain text. No Markdown headings or tables."""

TOOLS: list[dict[str, Any]] = [
    {
        "name": "quote_trip",
        "description": "Plan a metro trip for today and price it. Stores a quote the rider can pay for. "
        "Returns route summary, fare and quote_id, or an error (e.g. ambiguous station with options).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Origin as the rider wrote it, e.g. 'RC', 'hauz khas'"},
                "destination": {"type": "string", "description": "Destination as the rider wrote it"},
                "preference": {"type": "string", "enum": ["fastest", "fewest_changes", "cheapest"]},
            },
            "required": ["origin", "destination", "preference"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_station",
        "description": "Look up metro stations matching a messy name. Returns up to 3 matches with scores (0-100).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_stats",
        "description": "The rider's own trip stats: trips, unique stations, minutes, km, spend, favourite line.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "get_miles",
        "description": "The rider's Metro Miles balance, lifetime total and recent awards with reasons.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "get_badges",
        "description": "The rider's badges: earned ones with dates and locked ones with a hint on how to earn them.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "list_rewards",
        "description": "The demo rewards catalogue with Metro Miles cost.",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "get_visited_stations",
        "description": "Stations the rider has visited (origin, destination or interchange of their trips).",
        "strict": True,
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
]

NUMBER = re.compile(r"\d+(?:[.,:]\d+)*")
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
LANGUAGE_NOTES = {"en": "English", "hinglish": "Hinglish", "hi": "Hindi (Devanagari)"}
GUARD_FALLBACK_WITH_CARD = "Here's your trip 👇"
GUARD_FALLBACK = "Sorry, I got muddled there. Could you ask that again?"


@dataclass
class Reply:
    text: str
    quote_ids: list[str] = field(default_factory=list)
    guarded: bool = False  # True if the number guard replaced the model's text
    shown: list[str] = field(default_factory=list)  # what the app displayed alongside the text (for history)
    used_tools: bool = False  # the model called at least one tool this turn

    @property
    def history_text(self) -> str:
        """The assistant turn as kept in history: the reply plus a note of what the app showed."""
        return self.text + "".join(f"\n[Shown to rider: {s}]" for s in self.shown)


def numbers_in(text: str) -> set[str]:
    return {n.replace(",", "") for n in NUMBER.findall(text.translate(DEVANAGARI_DIGITS))}


def guard_numbers(reply: str, user_text: str, tool_outputs: list[str]) -> bool:
    """True if every number in `reply` is backed by the user's message or a tool result."""
    allowed = numbers_in(user_text).union(*(numbers_in(t) for t in tool_outputs))
    return numbers_in(reply) <= allowed


def first_messages(user: User, history: list[dict[str, str]], text: str, now: datetime) -> list[dict[str, Any]]:
    """History + the rider's message + the per-turn system note (time, name, reply language)."""
    note = (f"Now: {now:%A %d %B %Y, %H:%M} IST. Rider: {user.first_name}. "
            f"Reply language: {LANGUAGE_NOTES[user.language]}.")
    return [*history[-MAX_HISTORY:], {"role": "user", "content": text}, {"role": "system", "content": note}]


def request_params(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """The Messages API body the bot sends (minus fallbacks, which Batches and Haiku don't take)."""
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        "tools": TOOLS,
        "messages": messages,
        "output_config": {"effort": "low"},
    }


def supports_fallbacks(model: str) -> bool:
    """Server-side refusal fallbacks: on for Sonnet/Opus/Fable; Haiku 5.5 has none."""
    return "haiku" not in model


class Agent:
    def __init__(self, client: anthropic.AsyncAnthropic, conn: sqlite3.Connection, model: str) -> None:
        self.client = client
        self.conn = conn
        self.model = model

    async def respond(self, user: User, history: list[dict[str, str]], text: str, now: datetime) -> Reply:
        messages = first_messages(user, history, text, now)
        extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if supports_fallbacks(self.model) else {}
        tool_outputs: list[str] = []
        quote_ids: list[str] = []
        used_tools = False

        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.client.beta.messages.create(**request_params(self.model, messages), **extra)
            u = response.usage
            log.info("llm stop=%s in=%s cache_read=%s cache_write=%s out=%s", response.stop_reason,
                     u.input_tokens, u.cache_read_input_tokens, u.cache_creation_input_tokens, u.output_tokens)
            if response.stop_reason == "refusal":
                return Reply("I can only help with Delhi NCR metro trips. Where do you want to go?", quote_ids)
            if response.stop_reason != "tool_use":
                break
            used_tools = True
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                output, is_error = self._run_tool(block.name, block.input, user, now, quote_ids)
                tool_outputs.append(output)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error}
                )
            messages.append({"role": "user", "content": results})
        else:
            log.warning("tool loop hit MAX_TOOL_ROUNDS")

        shown = [self._shown_note(q) for q in quote_ids]
        reply = "".join(b.text for b in response.content if b.type == "text").strip()
        if not reply:
            reply = GUARD_FALLBACK_WITH_CARD if quote_ids else GUARD_FALLBACK
        if not guard_numbers(reply, text, tool_outputs):
            log.warning("number guard tripped: %r", reply)
            return Reply(GUARD_FALLBACK_WITH_CARD if quote_ids else GUARD_FALLBACK, quote_ids, True, shown, used_tools)
        return Reply(reply, quote_ids, False, shown, used_tools)

    def _shown_note(self, quote_id: str) -> str:
        q = tools.get_quote(self.conn, quote_id)
        a, b = tools.get_station(q.route.from_id).name, tools.get_station(q.route.to_id).name
        return f"route card and UPI payment QR for {a} to {b}, Rs {q.fare.total}"

    def _run_tool(self, name: str, args: dict, user: User, now: datetime, quote_ids: list[str]) -> tuple[str, bool]:
        try:
            if name == "quote_trip":
                q = tools.quote_trip(self.conn, user.user_id, args["origin"], args["destination"],
                                     args["preference"], now)
                quote_ids.append(q.quote_id)
                result: Any = quote_summary(q)
            elif name == "search_station":
                result = [m.to_dict() for m in tools.search_station(args["query"])]
            elif name == "get_stats":
                result = tools.get_stats(self.conn, user.user_id).to_dict()
            elif name == "get_visited_stations":
                result = [{"name": v.name, "state": v.state, "visits": v.count}
                          for v in tools.get_visited_stations(self.conn, user.user_id)]
            elif name == "get_miles":
                m = tools.get_miles(self.conn, user.user_id)
                result = {"balance": m.balance, "earned_total": m.earned_total,
                          "recent": [{"delta": a.delta, "reason": a.reason} for a in m.recent]}
            elif name == "get_badges":
                badges = tools.get_badges(self.conn, user.user_id)
                result = {"earned": [{"name": b.name, "description": b.description} for b in badges if b.earned_at],
                          "locked": [{"name": b.name, "hint": b.hint} for b in badges
                                     if not b.earned_at and not b.badge_id.startswith("line_collector_")],
                          "line_collectors_locked": sum(1 for b in badges if not b.earned_at
                                                        and b.badge_id.startswith("line_collector_"))}
            elif name == "list_rewards":
                result = [r.to_dict() for r in tools.list_rewards()]
            else:
                return f"Unknown tool {name}", True
        except tools.ToolError as exc:
            return str(exc), True
        return json.dumps(result, ensure_ascii=False), False


def quote_summary(q: tools.Quote) -> dict[str, Any]:
    """What the model sees of a quote: enough to talk about it, nothing it needs to restate."""
    name = lambda sid: tools.get_station(sid).name  # noqa: E731
    return {
        # No numbers on purpose (review finding): the card shows them, so the model has nothing to restate or swap
        # (fare vs minutes), and the number guard then rejects any number it writes about the trip. No quote id
        # either: the bot tracks quotes itself, and random ids contain digits that would widen the guard.
        "from": name(q.route.from_id),
        "to": name(q.route.to_id),
        "preference": q.route.preference,
        "change_at": [name(s) for s in q.route.interchange_ids],
        "lines": [leg.line_name for leg in q.route.legs],
        "fare_day_type": q.fare.day_type,
        "shown_to_rider": "route card with lines, time and fare + UPI QR + I've paid button",
    }


# --- Metro Wrapped narration ---------------------------------------------------------------------------------

VOICE_SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "metro-wrapped-voice" / "SKILL.md"
WRAPPED_MAX_WORDS = 70  # the skill asks for 60; allow a little slack before falling back


@cache
def wrapped_system_prompt() -> str:
    """The runtime prompt is the metro-wrapped-voice skill itself (frontmatter stripped)."""
    text = VOICE_SKILL.read_text()
    return text.split("---", 2)[2].strip() if text.startswith("---") else text


def wrapped_facts(stats: Any) -> dict[str, Any]:
    """What the narrator may talk about: the computed stats plus a few derived phrasings, all from code."""
    facts = stats.to_dict()
    facts.pop("month", None)
    h, m = divmod(stats.total_minutes, 60)
    facts["time_on_metro"] = f"{h}h {m}m"
    facts["hours_on_metro"] = h
    facts["km_rounded"] = round(stats.total_km)
    return facts


async def narrate_wrapped(client: anthropic.AsyncAnthropic, model: str, stats: Any, language: str,
                          fallback_text: str) -> tuple[str, bool]:
    """(text, guarded). guarded=True means the template was used because the narration broke a rule."""
    if not stats.trips:
        return fallback_text, False
    facts = json.dumps(wrapped_facts(stats), ensure_ascii=False)
    extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"} if supports_fallbacks(model) else {}
    response = await client.beta.messages.create(
        model=model,
        max_tokens=1500,
        system=[{"type": "text", "text": wrapped_system_prompt(), "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"Language: {LANGUAGE_NOTES[language]}\nFacts:\n{facts}"}],
        output_config={"effort": "low"},
        **extra,
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "refusal" or not text:
        return fallback_text, True
    if not guard_numbers(text, "", [facts]) or len(text.split()) > WRAPPED_MAX_WORDS:
        log.warning("wrapped narration rejected: %r", text)
        return fallback_text, True
    return text, False
