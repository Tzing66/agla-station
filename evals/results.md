# Station-parsing eval

Run 2026-10-23 19:02 IST · 50 cases (`evals/station_parsing.jsonl`) · batch `msgbatch_019GQ6LpFU8BEVkguPKq8uwb` · scored on the full system (model's `quote_trip` args -> `resolve_station`).
Resolver alone on rule-split text: `uv run python -m evals.resolver_baseline`.

| Model | Accuracy | Normal cases | Ambiguous -> asks | Preference | Median latency | $ / 1k messages |
| --- | --- | --- | --- | --- | --- | --- |
| `claude-sonnet-5-5` | **50/50** | 45/45 | 5/5 | 3/3 | 3.90 s | $3.62 |
| `claude-haiku-5-5` | **50/50** | 45/45 | 5/5 | 3/3 | 3.24 s | $0.19 |

**By category**

| Category | sonnet | haiku |
| --- | --- | --- |
| abbreviation | 8/8 | 8/8 |
| ambiguous | 5/5 | 5/5 |
| hinglish | 10/10 | 10/10 |
| landmark | 7/7 | 7/7 |
| partial | 7/7 | 7/7 |
| plain | 5/5 | 5/5 |
| typo | 8/8 | 8/8 |

**Cost notes**

- `claude-sonnet-5-5`: this batch (first call only, 50% batch price) $0.0419; live sample 10 full bot turns $0.0362 at standard prices; live tokens {'input': 5039, 'output': 1629, 'cache_read': 29678, 'cache_write': 1562}.
- `claude-haiku-5-5`: this batch (first call only, 50% batch price) $0.0045; live sample 10 full bot turns $0.0019 at standard prices; live tokens {'input': 5027, 'output': 1767, 'cache_read': 29678, 'cache_write': 1562}.
- $/1k messages = live-sample cost per full bot turn (all tool rounds, caching as observed) x 1000.
- Haiku 5.5 cache prices are assumed (0.1x / 1.25x input); see `PRICES` in `evals/run_eval.py`.

**Failures**

- `claude-sonnet-5-5`: none
- `claude-haiku-5-5`: none

## Decision and scaling note (2026-10-23)

The bot stays on `claude-sonnet-5-5` (logged as an OVERRIDE in `ledger/decisions.md`). On this eval Haiku 5.5 matched Sonnet on every case at about 1/19th of the cost per message, so it is the first lever to pull if traffic grows:

- Switch with one line in `.env`: `AGLA_MODEL=claude-haiku-5-5` (the agent drops server-side fallbacks automatically for Haiku).
- Before switching, add reply-quality cases (English, Hinglish, Hindi tone; under-60-word replies; number-guard trips) and harder parsing cases, since both models scored 100% here and the eval can't separate them yet.
- Rough monthly cost at 100k messages: Sonnet ~$362, Haiku ~$19 (from the live-sample $/1k above; Haiku cache prices assumed).
