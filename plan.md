# Agla Station — Build Plan for Claude Code

> Read this whole file before doing anything. Work phase by phase. Do not start a phase until the previous one meets its "Done when" checks. Stop and ask me before any decision that changes the architecture below.

## 1. What we are building

**Agla Station** is a Telegram bot for the whole Delhi NCR metro network (DMRC lines, Rapid Metro Gurugram, Noida Aqua Line). The name comes from the metro announcement "agla station...". Its story in one line: **ride more, ride safer, have fun doing it.**

A user texts where they want to go in plain language ("rajiv chowk to hauz khas, cheapest", "RC se botanical garden"). The bot:

1. Resolves the stations (fuzzy, Hinglish, abbreviations).
2. Returns the route, interchanges, travel time estimate and fare.
3. Sends a UPI payment link (opens Paytm, GPay or PhonePe) and a QR of it.
4. On "I've paid", issues a **mock** QR ticket, logs the trip and awards **Metro Miles**.
5. Lets the user **share the journey** as a live link with a timetable-based ETA, and runs an opt-in **"I've reached" safety check** that alerts trusted contacts if they don't confirm arrival.
6. Tracks visited stations, awards non-consequential badges, and produces a monthly **Metro Wrapped** recap.
7. Offers a dashboard (Telegram Mini App) with a map of visited stations, badges, miles and rewards, insights and recaps.

This is a 24-hour assignment for an "AI Native SDE" role. The process matters as much as the product, so the **process ledger (Phase 0) is mandatory and comes first**.

### Honest constraints (also go in the README)

- Tickets are mock QR tickets. DMRC has no public ticket-issuing API.
- Payment is a UPI intent link; payment is not verified. Paytm's payment-link API needs a merchant account and is a stretch goal only.
- Fares come from official sources and are spot-checked by me; never invent fares.
- Journey sharing is an **estimate from the timetable**, not live GPS (there is no signal underground). The share page says so.
- Metro Miles and rewards are a **concept demo**. Vouchers are labelled "demo, not redeemable".

## 2. Ground rules (copy into CLAUDE.md)

- **Code decides, the LLM narrates.** Routes, fares, ETAs, miles, badges, stats and recap numbers are computed in Python. The LLM only picks tools, parses user intent and writes words. Never let the model state a number that did not come from a tool result.
- **One tool layer.** All metro logic lives in `agla/tools/`. The Telegram bot, the MCP server and the dashboard API are thin front ends over it. No business logic in front ends.
- **Cost discipline.** Use `claude-sonnet-5-5` for everything by default. Enable prompt caching on the system prompt and tool definitions. Keep the bot's context small: no chat history beyond the last 6 messages.
- **Privacy by default.** Sharing and safety alerts are opt-in, share links expire, share pages show first name only, and trusted contacts must accept an invite.
- **Never commit secrets.** All keys in `.env`; `.env` is gitignored; the ledger hook scrubs secrets.
- Python 3.11+, type hints, `ruff` for lint, `pytest` for tests. Small modules, no framework magic.
- After finishing each phase: run tests, then remind me to run `/checkpoint`.

## 3. Stack

| Concern | Choice |
| --- | --- |
| Language | Python 3.11+ |
| Bot | python-telegram-bot (polling for dev), its `JobQueue` for safety-check timers |
| LLM | Anthropic Python SDK, `claude-sonnet-5-5`, tool use + prompt caching |
| Routing | networkx |
| Storage | SQLite (via `sqlite3` or SQLModel, keep it light) |
| MCP server | Official MCP Python SDK (`mcp`), built with the `mcp-builder` skill |
| Dashboard + share pages | FastAPI + Jinja2 + HTMX, Leaflet for the map, Chart.js for charts |
| QR codes | `qrcode` + Pillow |
| Wrapped card | Pillow (or HTML → PNG with Playwright if time allows) |
| Hosting | Railway/Render, or a Cloudflare tunnel for the demo (Mini Apps and share links need HTTPS) |

## 4. Repo layout

```
agla-station/
├── CLAUDE.md
├── plan.md                      # this file
├── README.md
├── .env.example
├── pyproject.toml
├── .claude/
│   ├── settings.json            # hooks + statusline
│   ├── commands/                # /decision /surprise /checkpoint
│   ├── agents/                  # gtfs-explorer, reviewer, eval-runner
│   └── skills/                  # metro-wrapped-voice, build-journal
├── .claude-plugin/              # agla-dev plugin manifest (Phase 10)
├── ledger/
│   ├── hook.py
│   ├── events.jsonl             # auto, from hooks
│   ├── decisions.md             # manual, from /decision and /surprise
│   ├── chats/                   # exported claude.ai conversations
│   └── build_timeline.py        # merges ledger + git log into a timeline
├── data/
│   ├── raw/                     # GTFS zips (gitignored if large)
│   ├── manual/                  # hand-made CSVs for gaps (Aqua Line, interchanges)
│   ├── fares.yaml               # fare rules per operator, with sources
│   ├── miles.yaml               # earning rules
│   └── rewards.yaml             # mock rewards catalogue
├── agla/
│   ├── network/                 # GTFS loading, graph building
│   ├── tools/                   # THE tool layer (pure functions)
│   ├── db.py                    # SQLite schema + queries
│   ├── badges.py                # deterministic badge rules
│   ├── miles.py                 # deterministic miles rules + redemption
│   ├── sharing.py               # share links, ETA estimates, safety checks
│   ├── wrapped.py               # recap aggregates + card rendering
│   ├── llm.py                   # Claude client, tool-use loop, caching
│   ├── bot/                     # Telegram handlers
│   ├── mcp_server.py            # agla-mcp
│   └── web/                     # FastAPI: dashboard + public share pages
├── evals/
│   ├── station_parsing.jsonl    # messy inputs → expected station ids
│   ├── run_eval.py              # Batch API runner
│   └── results.md
├── scripts/seed_demo.py         # a month of fake trips for the demo user
└── tests/
```

## 5. Phases

Clock times assume a 4pm Friday start. The real deadline is 8pm Saturday; anything after ~4:30pm Saturday is buffer.

| Phase | Hours | Clock |
| --- | --- | --- |
| 0 · Ledger and Claude setup | H0–1 | Fri 4–5pm |
| 1 · Architecture in plan mode | H1–2 | 5–6pm |
| 2 · NCR network and routing | H2–4 | 6–8pm |
| 3 · agla-mcp server | H4–5 | 8–9pm |
| 4 · Telegram bot | H5–8 | 9pm–12am |
| 5 · Station-parsing eval | H8–9 | 12–1am |
| Sleep | H9–15 | 1–7am |
| 6 · Badges and Metro Miles | H15–17 | Sat 7–9am |
| 7 · Metro Wrapped | H17–18 | 9–10am |
| 8 · Journey sharing and safety check | H18–19.5 | 10–11:30am |
| 9 · Dashboard Mini App | H19.5–21.5 | 11:30am–1:30pm |
| 10 · Review, packaging, demo | H21.5–22.5 | 1:30–2:30pm |
| 11 · Timeline and write-up | H22.5–24.5 | 2:30–4:30pm |

### Phase 0 — Process ledger and Claude setup (H0–1)

Goal: every prompt I type and every action you take is logged from this point on.

1. **`ledger/hook.py`**: one script for all hook events. Reads the hook JSON from stdin and appends one line to `ledger/events.jsonl`:
   ```json
   {"ts": "...", "session": "...", "event": "UserPromptSubmit|PreToolUse|PostToolUse|Stop|SubagentStop|PreCompact|SessionStart",
    "actor": "human|claude|system", "tool": "Edit|Bash|mcp__github__...|null",
    "target": "file path / command / null", "summary": "first 200 chars"}
   ```
   - `UserPromptSubmit` → actor `human`, summary = the prompt.
   - `PreToolUse`/`PostToolUse` → actor `claude`, tool name, target = `file_path` or the command.
   - `Stop` → actor `claude`, marks end of a turn. `SubagentStop` → actor `claude`, marks subagent work. `PreCompact` → actor `system`.
   - Scrub anything matching API-key/token patterns (`sk-ant-`, bot tokens `\d+:[A-Za-z0-9_-]{30,}`, long hex/base64) to `[REDACTED]`.
   - Must never crash or block: wrap everything in try/except and exit 0.
2. **`.claude/settings.json`**: register `hook.py` for `SessionStart`, `UserPromptSubmit`, `PreToolUse` (matcher `*`), `PostToolUse` (matcher `*`), `Stop`, `SubagentStop` and `PreCompact`. Add a `statusLine` command that shows model name and session cost.
3. **Slash commands** in `.claude/commands/`:
   - `/decision` — ask me (one question at a time) for: the question, options considered, what Claude suggested, what I chose, why. Append a dated entry to `ledger/decisions.md` tagged `DECISION`. If I chose differently from Claude's suggestion, tag it `OVERRIDE`.
   - `/surprise` — ask what happened and whether it was good or bad; append tagged `SURPRISE`.
   - `/checkpoint` — ask for a one-line status, append it tagged `CHECKPOINT` with current session cost if available, then `git add -A && git commit -m "checkpoint: <status>"`.
4. **CLAUDE.md** from section 2 plus the stack and layout.
5. `.env.example` with `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `UPI_VPA`, `UPI_PAYEE_NAME`, `PUBLIC_BASE_URL`, `DASHBOARD_SECRET`.

**Done when:** I type a prompt, you edit a file, and both appear in `events.jsonl` with secrets scrubbed; `/decision` writes to `decisions.md`.

### Phase 1 — Architecture in plan mode (H1–2)

In plan mode, propose the module interfaces for `agla/tools/` and the full DB schema (Phase 4 plus the Phase 6 and 8 tables). Save the agreed version to `docs/architecture.md`. Prompt me to log decisions: Telegram over WhatsApp, UPI link over Paytm API, Mini App over a separate website, timetable ETA over GPS tracking.

### Phase 2 — NCR network and routing (H2–4)

1. Use the **`gtfs-explorer` subagent** (`.claude/agents/gtfs-explorer.md`, tools: Read, Bash, Grep; model: sonnet) to download and inspect the DMRC GTFS feed from Delhi Open Transit Data (`https://otd.delhi.gov.in/data/staticDMRC/`, needs a POST with any 64-char CSRF token in both the `csrftoken` cookie and `csrfmiddlewaretoken` form field). Report: lines, station count per line, interchanges, and whether Rapid Metro Gurugram and the Noida Aqua Line are present.
2. Fill gaps with hand-made CSVs in `data/manual/` (stations with lat/lon, line order, interchange walks such as Sector 52 ↔ Sector 51, Sikandarpur ↔ Rapid Metro). Mark manual data clearly.
3. `agla/network/graph.py`: nodes = (station, line); edges = consecutive stations on a line (weight = minutes, from GTFS stop times) and interchange edges (weight = transfer penalty, default 6 min). Stations have a canonical `station_id`, display name, aliases list, lat/lon, state (Delhi/Haryana/UP), lines.
4. Fares: `data/fares.yaml` holds the fare rules per operator (DMRC, Rapid Metro, NMRC). Extract them yourself, in this order of preference:
   1. `fare_attributes.txt` / `fare_rules.txt` in the GTFS feed, if present.
   2. The official fare pages or fare calculators on the DMRC, Rapid Metro and NMRC websites (WebFetch, or Playwright MCP if the page needs clicking).
   Record the source URL and date for each operator in the YAML. Then generate 8 sample station pairs and ask me to spot-check them against the official DMRC app or website before we rely on the table. Note Sunday/holiday fare differences if the source mentions them. Cross-operator trips sum per-operator fares.
5. Tools:
   - `search_station(query) -> list[StationMatch]` (rapidfuzz over names + aliases; returns top 3 with scores).
   - `plan_route(from_id, to_id, preference="fastest"|"fewest_changes") -> Route` (legs, interchanges, est. minutes, ordered stations with cumulative minutes from departure, distance in km from station coordinates).
   - `get_fare(route) -> Fare`.
6. Tests: 6 routes including one with 2 interchanges, one into Noida (Aqua via Sector 51/52), one into Rapid Metro.

**Done when:** `pytest` passes and `python -m agla.tools.cli "rajiv chowk" "hauz khas"` prints a sensible route, distance and fare.

### Phase 3 — agla-mcp server (H4–5)

Use the **`mcp-builder` skill**. Expose `search_station`, `plan_route`, `get_fare`, `get_stats`, `get_badges`, `get_miles`, `get_visited_stations` over MCP (stdio). Tools for features not built yet return a clear "not available yet" until their phase lands. Each tool has a clear description and typed schema. Add a README section with the Claude Desktop / Claude Code config snippet.

**Done when:** from Claude Code (`claude mcp add`) or Claude Desktop, "what's the route from Botanical Garden to Cyber City?" is answered via agla-mcp.

### Phase 4 — Telegram bot (H5–8)

1. `agla/llm.py`: tool-use loop with `claude-sonnet-5-5`. Tools = the tool layer plus `make_payment_link`, `log_trip`, `get_stats`, `get_badges`, `get_miles`. System prompt: friendly, short, a little Delhi in tone, never states numbers not returned by tools, asks for clarification when `search_station` is ambiguous. **Prompt caching** on system prompt + tool definitions. History capped at 6 messages.
2. `make_payment_link(route, fare)`: builds `upi://pay?pa={UPI_VPA}&pn={UPI_PAYEE_NAME}&am={fare}&cu=INR&tn=Agla%20Station%20{from}-{to}`, returns it plus a QR PNG. Telegram can't open `upi://` from inline buttons on all clients, so send the QR image plus the link as text, and a "✅ I've paid" button.
3. On "I've paid": generate a mock QR ticket image (clearly labelled DEMO, with route, fare, timestamp, ticket id), call `log_trip`, then run the post-trip hooks (badges in Phase 6, miles in Phase 6, share and safety buttons in Phase 8). Design `log_trip` so these hooks plug in without touching bot code.
4. Commands: `/start`, `/help`, `/stats`, `/badges`, `/miles`, `/wrapped`, `/dashboard`, `/trusted`, `/safety`.
5. Core SQLite schema:
   ```sql
   users(id INTEGER PK, telegram_id INTEGER UNIQUE, first_name TEXT, safety_on INT DEFAULT 0, created_at TEXT)
   trips(id INTEGER PK, user_id INT, from_id TEXT, to_id TEXT, stations_json TEXT,
         lines_json TEXT, interchanges INT, minutes INT, distance_km REAL, fare REAL,
         depart_at TEXT, eta TEXT, created_at TEXT)
   visits(user_id INT, station_id TEXT, first_visit TEXT, count INT, PRIMARY KEY(user_id, station_id))
   badges(user_id INT, badge_id TEXT, earned_at TEXT, PRIMARY KEY(user_id, badge_id))
   ```
   A station counts as visited if it is a trip's origin, destination or interchange (not every station passed; note this rule in the README — it's a deliberate decision, log it).

**Done when:** a full chat flow works end to end on my phone.

### Phase 5 — Station-parsing eval (H8–9)

1. `evals/station_parsing.jsonl`: 50 messy inputs with expected `station_id`s. Mix: abbreviations ("RC", "HKV"), typos ("rajiv chok"), partial ("botanical"), landmarks ("cyber hub"), Hinglish ("kashmere gate se noida sec 18"), and 5 deliberately ambiguous ones where the correct behaviour is to ask.
2. `evals/run_eval.py` using the **`eval-runner` subagent**: run the parsing step with `claude-sonnet-5-5` and `claude-haiku-5-5` via the **Message Batches API**. Report accuracy, ambiguity handling, median latency (from a small non-batch sample) and estimated cost per 1,000 messages in `evals/results.md`.
3. Prompt me to `/decision` the runtime model. Default stays Sonnet unless Haiku matches its accuracy.

### Phase 6 — Badges and Metro Miles (H15–17)

**Badges.** `agla/badges.py`: pure functions over the DB, evaluated after every trip. Each badge: `id`, `name`, `description`, `hint` (shown while locked), `check(user) -> bool`. Starter set:

| id | Name | Rule |
| --- | --- | --- |
| first_ride | Agla Station | First trip logged |
| explorer_10 | Explorer | 10 unique stations |
| explorer_25 | Cartographer | 25 unique stations |
| interchange_goblin | Interchange Goblin | 10 trips with ≥ 2 interchanges |
| terminal_to_terminal | End of the Line | Trip between both terminals of one line |
| line_collector_* | Line Collector: <Line> | Every station on a line visited |
| night_owl | Night Owl | A trip after 10pm |
| early_bird | Early Bird | A trip before 7am |
| state_hopper | State Hopper | Delhi, Haryana and UP in one week |
| loyal | Regular | Same route 10 times |
| miles_1000 | Thousand Miler | 1,000 Metro Miles earned |
| safe_and_sound | Safe and Sound | 5 confirmed arrivals with the safety check on |

**Metro Miles.** `agla/miles.py`, rules in `data/miles.yaml` so they're tweakable without code changes:

- Base: 5 miles per km travelled (`distance_km` from the route).
- Off-peak: 2x outside weekday peaks (08:00–11:00 and 17:00–20:00) and all weekend. The point: nudge riders to spread out demand.
- First visit: +50 per station visited for the first time.
- Streak: +20 per day from the 3rd consecutive day with a trip.
- Safe arrival: +10 when the safety check is confirmed (Phase 8).

Every award is a row with a human-readable reason, so the bot can say "+42 Metro Miles (2x off-peak, +50 new station: Hauz Khas)".

```sql
miles_ledger(id INTEGER PK, user_id INT, trip_id INT NULL, delta INT, reason TEXT, created_at TEXT)
vouchers(id INTEGER PK, user_id INT, reward_id TEXT, miles_spent INT, code TEXT, created_at TEXT)
```

`data/rewards.yaml`: a mock catalogue with generic names only (no real brands), for example: 10% off next ticket (500), free chai at a station kiosk (300), 15% off at a station bookstore (800), free day pass (2,000). `redeem_reward(user, reward_id)` deducts miles and creates a voucher labelled **"DEMO — concept only, not redeemable"**.

Tools: `get_miles(user)` (balance, recent ledger), `list_rewards()`, `redeem_reward(user, reward_id)`. The bot's ticket confirmation shows miles earned; `/miles` shows balance and recent awards.

`scripts/seed_demo.py`: a realistic month of trips for a demo user (weekday commute + weekend outings across all three states) that unlocks about half the badges and builds a miles balance big enough to redeem something.

**Done when:** seeding produces sensible badges and a miles ledger whose every row has a correct reason; tests cover off-peak, first visit and streak rules.

### Phase 7 — Metro Wrapped (H17–18)

1. `agla/wrapped.py`: SQL aggregates for a month — trips, unique stations, new stations, top 3 stations, favourite line, total minutes, total distance, total fare, miles earned, badges earned, busiest day.
2. Narration uses the **`metro-wrapped-voice` skill** (`.claude/skills/metro-wrapped-voice/SKILL.md`): tone rules (cheeky, warm, Delhi references, max 60 words, never invent numbers) and 3 example recaps. The runtime prompt is generated from this skill's content.
3. `/wrapped` sends it. Build the text version first; render the vertical card PNG (Pillow) only if time allows.

### Phase 8 — Journey sharing and safety check (H18–19.5)

**Share my journey.**

1. After a ticket is issued, the bot shows a "📤 Share journey" button. It creates a share with a random token and returns `PUBLIC_BASE_URL/s/{token}` plus a ready-to-forward message ("I'm on my way: Rajiv Chowk → Hauz Khas, ETA 6:42pm. Track me: <link>").
2. `estimate_position(trip, now) -> Position` in the tool layer (pure function): uses `depart_at` and the route's cumulative minutes to return the current state — "between Saket and Malviya Nagar", "changing at Rajiv Chowk", or "should have arrived" — plus progress % and ETA. Unit-test it with fixed timestamps for each state.
3. Public share page at `/s/{token}` (no login): first name only, route, a progress bar along the stations, current estimate, ETA, and status (on the way / arrived / overdue). HTMX refresh every 30s. A visible note: "Estimated from the metro timetable, not live GPS."
4. Expiry: 30 minutes after confirmed arrival, or ETA + 2h, whichever comes first. Expired links show a friendly "This journey has ended" page.

**"I've reached" safety check (opt-in).**

1. `/safety` toggles it on or off. `/trusted` creates an invite deep link (`https://t.me/{TELEGRAM_BOT_USERNAME}?start=trust_{token}`); the friend opens it, taps Accept, and becomes a trusted contact. Telegram bots can only message people who have started the bot, which is why the invite step exists.
2. When safety is on and a trip is logged, schedule three `JobQueue` jobs: at ETA, ask "Reached? ✅"; at ETA + 15 min, nudge again; at ETA + 25 min, message trusted contacts with the share link and "hasn't confirmed arrival yet". Tapping Reached at any point cancels pending jobs, sets `arrived_at`, marks the share as arrived, and awards safe-arrival miles.
3. If the bot restarts, reschedule pending checks from the DB on startup.

```sql
shares(token TEXT PK, user_id INT, trip_id INT, created_at TEXT, expires_at TEXT, arrived_at TEXT NULL)
trusted_contacts(user_id INT, contact_user_id INT, accepted_at TEXT, PRIMARY KEY(user_id, contact_user_id))
safety_checks(trip_id INT PK, user_id INT, eta TEXT, stage INT DEFAULT 0, arrived_at TEXT NULL)
```

For the demo, add a `/demo_fast` admin-only flag that compresses the timers to seconds so the full escalation can be shown on video.

**Done when:** a shared link updates as time passes, and with `/demo_fast` the full Reached → nudge → trusted-contact alert sequence works between two Telegram accounts.

### Phase 9 — Dashboard Mini App (H19.5–21.5)

Use the **`frontend-design` skill** for the look.

1. FastAPI app in `agla/web/`, served at `PUBLIC_BASE_URL` (same app as the share pages).
2. `/dashboard` in the bot replies with an inline `WebAppInfo` button opening the Mini App.
3. **Auth**: validate Telegram `initData` server-side — `secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)`, then compare `HMAC_SHA256(secret_key, data_check_string)` to `hash`; reject if `auth_date` is older than 24h. Fallback: signed magic link (`itsdangerous`, `DASHBOARD_SECRET`) for normal browsers.
4. Tabs:
   - **Map**: Leaflet, all NCR stations as dots coloured by line; visited = filled, unvisited = grey; completion % per line.
   - **Badges**: earned (with date) and locked (with hint).
   - **Miles**: balance, recent awards with reasons, the rewards catalogue with a Redeem button, and issued demo vouchers.
   - **Insights**: trips per week (Chart.js), top stations, line split, total minutes, distance and spend.
   - **Wrapped**: archive of monthly recaps.
5. Test with **Playwright MCP** and the **`webapp-testing` skill**: click every tab, redeem a reward, open a share page, check no console errors, save screenshots to `docs/screenshots/` for the README.

### Phase 10 — Review, packaging, demo (H21.5–22.5)

1. **`reviewer` subagent** (`.claude/agents/reviewer.md`, tools: Read, Grep, Glob; model: sonnet). It has not seen the build; ask it to audit for bugs, secrets, LLM-stated numbers, front ends containing business logic, and privacy issues in sharing (leaking full names, links that never expire, alerts sent without consent). Fix the top issues.
2. Package `.claude/commands`, `.claude/agents`, `.claude/skills` and the hooks as an **`agla-dev` plugin** (`.claude-plugin/plugin.json`) so anyone can install the exact dev setup.
3. Deploy or tunnel. I record a 3–5 minute video: book a trip, earn miles, share the journey, show the safety escalation with `/demo_fast`, open the dashboard, then the process timeline.

### Phase 11 — Timeline and write-up (H22.5–24.5)

1. `ledger/build_timeline.py`: merge `events.jsonl`, `decisions.md`, `git log`, and the exported claude.ai chats in `ledger/chats/` (as an "ideation" phase before the first commit) into one sorted timeline JSON. As a backup source, it can also read Claude Code's own session transcripts (JSONL files under `~/.claude/projects/` for this repo) to fill any gaps where a hook failed; copy only what's needed and scrub secrets. Compute stats: total prompts, Claude actions by tool, decisions, overrides, surprises, rewinds, sessions, total cost from checkpoints.
2. **`build-journal` skill** (create it with the `skill-creator` skill): turns the timeline JSON into a single self-contained HTML page with three lanes (my prompts, Claude's actions, decisions) over time, plus the stats. I'll publish it.
3. Help me draft the write-up from `decisions.md` against the four questions: what and why, tools and roles, how AI shaped decisions, where AI surprised me. My voice, not marketing copy.

## 6. Cut order if behind schedule

1. GitHub Action PR review (stretch)
2. Paytm staging integration (stretch)
3. Deployment (tunnel is fine)
4. Claude Desktop demo of agla-mcp
5. Wrapped card image (send text instead)
6. Redeem flow (show balance and catalogue only)
7. Share page auto-refresh (static page with ETA is fine)
8. Dashboard Map tab (keep Badges, Miles and Insights)

**Never cut:** the ledger, the eval, the safety check, the write-up.

## 7. Stretch goals (only if everything above is done)

- **Meetup groups:** `/meetup <station> <time>` creates a group link; friends join with their starting station; each sees everyone's route and ETA, and the bot tells each person when to leave so everyone arrives on time. Reuses `plan_route` and `estimate_position`.
- Claude Code GitHub Action reviewing each phase's PR.
- Paytm payment links via the staging environment.
- Route preference "least walking" and "next train" estimates from GTFS frequencies.
