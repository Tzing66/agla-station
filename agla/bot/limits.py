"""Per-rider cap on LLM-backed messages, so nobody who finds the bot can run up the API bill.

Menu buttons, canned off-topic replies and button taps don't count: only messages that would call Claude.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

PER_MINUTE = 10
PER_DAY = 150

SLOW_DOWN = {
    "en": "Easy there! 🚦 That's a lot of messages; give me a minute and try again.",
    "hinglish": "Thoda ruko! 🚦 Bahut saare messages ho gaye, ek minute baad try karo.",
    "hi": "थोड़ा रुकिए! 🚦 बहुत सारे संदेश हो गए, एक मिनट बाद फिर कोशिश करें।",
}
DAILY_CAP = {
    "en": "You've hit today's limit for chat messages. The menu buttons still work, and chat resets tomorrow.",
    "hinglish": "Aaj ke chat messages ki limit poori ho gayi. Menu buttons chalte rahenge, chat kal se phir.",
    "hi": "आज के चैट संदेशों की सीमा पूरी हो गई। मेनू बटन चलते रहेंगे, चैट कल से फिर।",
}


@dataclass
class RateLimiter:
    per_minute: int = PER_MINUTE
    per_day: int = PER_DAY
    _seen: dict[int, deque[datetime]] = field(default_factory=lambda: defaultdict(deque))

    def check(self, user_id: int, now: datetime) -> str | None:
        """None if allowed (and counted), else "minute" or "day"."""
        q = self._seen[user_id]
        while q and now - q[0] >= timedelta(days=1):
            q.popleft()
        if len(q) >= self.per_day:
            return "day"
        if sum(1 for t in q if now - t < timedelta(minutes=1)) >= self.per_minute:
            return "minute"
        q.append(now)
        return None
