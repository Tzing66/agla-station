"""Off-topic chatter policy: after a couple of off-topic turns in a row, answer from a rotating pool of redirects
instead of calling the LLM, until a message looks metro-related again. Saves API spend; keeps replies fresh."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

LLM_OFF_TOPIC_TURNS = 1  # the first off-topic message still gets a natural LLM reply
RECENT = 4  # never reuse any of the last few canned lines

REDIRECTS = {
    "en": [
        "I'm a metro buddy, not a chatterbox 🚇 Where to? Try: rajiv chowk to hauz khas",
        "Tempting, but I only know trains. Tell me a start and an end station.",
        "My whole world is the Delhi NCR metro. Want a route? e.g. kashmere gate to botanical garden",
        "Let's get you moving instead! Which station are you starting from?",
        "I'd love to help, if it involves a metro line. Try: cyber city to noida sector 18",
        "Small talk isn't my line. The Yellow Line is, though. Where are you headed?",
        "Agla station? Tell me where you want to go and I'll find the route and fare.",
        "I can plan any trip on DMRC, Airport Express, Rapid Metro or the Aqua Line. Where to?",
        "Not my department! Send me two stations, like: new delhi to airport",
        "I'm best at routes, fares and tickets. Try: RC se HKV",
        "Let's keep it on track 🚆 Where are you travelling today?",
        "For anything else I'm stumped, but for metro trips I'm quick. Try: dwarka sector 21 to rajiv chowk",
    ],
    "hinglish": [
        "Main toh bas metro wala dost hoon 🚇 Kahan jaana hai? Jaise: RC se Hauz Khas",
        "Yeh mere bas ka nahi, par metro route chahiye toh batao! Start aur end station?",
        "Meri duniya sirf Delhi NCR metro hai. Route bataun? Jaise: kashmere gate se botanical garden",
        "Chalo, aapko kahin pahunchate hain! Kahan se shuru karna hai?",
        "Baatein baad mein, pehle safar! Try: cyber city se noida sector 18",
        "Gappe nahi, par Yellow Line ki poori jaankari hai. Kidhar ja rahe ho?",
        "Agla station kaunsa? Batao kahan jaana hai, main route aur kiraya bata dunga.",
        "DMRC, Airport Express, Rapid Metro, Aqua Line, sab cover karta hoon. Kahan jaana hai?",
        "Yeh topic mera nahi! Do station bhejo, jaise: new delhi se airport",
        "Route, kiraya, ticket, yeh mera kaam hai. Try: RC se HKV",
        "Track pe rehte hain 🚆 Aaj kahan ka safar hai?",
        "Baaki sab mein main zero, metro mein hero. Try: dwarka sector 21 se rajiv chowk",
    ],
    "hi": [
        "मैं बस मेट्रो वाला दोस्त हूँ 🚇 कहाँ जाना है? जैसे: rajiv chowk से hauz khas",
        "यह मेरे बस का नहीं, पर मेट्रो रूट चाहिए तो बताइए! शुरुआत और मंज़िल?",
        "मेरी दुनिया बस Delhi NCR मेट्रो है। रूट बताऊँ? जैसे: kashmere gate से botanical garden",
        "चलिए, आपको कहीं पहुँचाते हैं! कहाँ से शुरू करना है?",
        "बातें बाद में, पहले सफ़र! आज़माएँ: cyber city से noida sector 18",
        "गपशप नहीं, पर Yellow Line की पूरी जानकारी है। किधर जा रहे हैं?",
        "अगला स्टेशन कौन सा? बताइए कहाँ जाना है, मैं रूट और किराया बता दूँगा।",
        "DMRC, Airport Express, Rapid Metro, Aqua Line, सब कवर करता हूँ। कहाँ जाना है?",
        "यह विषय मेरा नहीं! दो स्टेशन भेजिए, जैसे: new delhi से airport",
        "रूट, किराया, टिकट, यह मेरा काम है। आज़माएँ: RC से HKV",
        "पटरी पर रहते हैं 🚆 आज कहाँ का सफ़र है?",
        "बाकी सब में ज़ीरो, मेट्रो में हीरो। आज़माएँ: dwarka sector 21 से rajiv chowk",
    ],
}


@dataclass
class ChatterState:
    off_topic_streak: int = 0
    recent: list[int] = field(default_factory=list)

    def should_skip_llm(self, metro_related: bool) -> bool:
        return not metro_related and self.off_topic_streak >= LLM_OFF_TOPIC_TURNS

    def record(self, metro_related: bool, used_tools: bool) -> None:
        self.off_topic_streak = 0 if (metro_related or used_tools) else self.off_topic_streak + 1

    def canned(self, language: str, rng: random.Random | None = None) -> str:
        pool = REDIRECTS.get(language, REDIRECTS["en"])
        choices = [i for i in range(len(pool)) if i not in self.recent] or list(range(len(pool)))
        i = (rng or random).choice(choices)
        self.recent = [*self.recent, i][-RECENT:]
        self.off_topic_streak += 1
        return pool[i]
