# Agla Station: a guide to the repository

This guide explains what every folder and file in the repo is for, and how Claude was used to build it: the Claude Code setup, the subagents, skills and MCP servers, and where Claude runs inside the product itself.

- To **run** the bot, see the [README](../README.md).
- For **design decisions**, see [architecture.md](architecture.md) and the [decisions log](../ledger/decisions.md).
- [plan.md](../plan.md) is the original build plan, kept as written.

## Contents

1. [The project in one minute](#1-the-project-in-one-minute)
2. [Map of the repository](#2-map-of-the-repository)
3. [What happens when a rider sends a message](#3-what-happens-when-a-rider-sends-a-message)
4. [File by file](#4-file-by-file)
5. [Claude: how it was used to build this](#5-claude-how-it-was-used-to-build-this)
6. [Claude inside the product](#6-claude-inside-the-product)
7. [Where to change things](#7-where-to-change-things)

## 1. The project in one minute

Agla Station is a Telegram bot for the Delhi NCR metro. A rider types where they're going in plain English or Hinglish ("rc se hauz khas"). The bot then:

- finds the stations and plans a route
- quotes the official fare and gives a UPI payment link
- issues a demo QR ticket
- awards Metro Miles and badges
- lets the rider share a live link of their journey and send "I've reached"

A dashboard Mini App inside Telegram shows the rider's map, badges, miles, insights and a monthly Metro Wrapped.

Three ideas shape the code:

- **Code decides, the LLM narrates.** Every number (route, time, fare, miles, ETA) is computed in Python. Claude only picks tools and writes words. A "number guard" rejects any reply that contains a number the code didn't produce.
- **One tool layer.** All metro logic lives in `agla/tools/`. The Telegram bot, the web app and the MCP server are thin front ends over it, and a test enforces that.
- **Never invent fares.** Fares come from official sources in `data/`, and every official fare we hold is checked by the tests.

## 2. Map of the repository

```
agla-station/
├── agla/                  the application (Python package)
│   ├── tools/             THE tool layer: stations, routing, fares, quotes, payments, trips, stats, auth...
│   ├── network/           builds and loads the metro network graph
│   ├── bot/               Telegram front end (handlers, message templates, limits)
│   ├── web/               FastAPI front end (share pages, dashboard Mini App + API)
│   ├── badges.py  miles.py  sharing.py  wrapped.py     domain modules, re-exported by agla.tools
│   ├── llm.py             Claude tool-use loop and Wrapped narration
│   ├── mcp_server.py      agla-mcp: the tool layer over MCP
│   ├── db.py  config.py   SQLite schema/migrations; settings and the only clock
│   └── __main__.py        `python -m agla`: bot + web + tunnel in one process
├── data/                  network, official fare data, rules for miles and rewards, fonts
├── scripts/               run, seed, verify fares, fit track factors, browser checks
├── evals/                 station-parsing eval (Sonnet vs Haiku)
├── tests/                 pytest suite (174 tests)
├── docs/                  architecture, this guide, knowledge document, build journal, backlog, screenshots
├── ledger/                the process ledger: every prompt and tool call, decisions, timeline
├── .claude/               Claude Code project setup: hooks, commands, subagents, skills, status line
├── .claude-plugin/        the agla-dev plugin (the same setup, installable elsewhere)
├── .github/workflows/     CI: lint, tests, secret scan
├── .mcp.json              MCP servers for Claude Code: Playwright and agla-mcp
├── CLAUDE.md              standing instructions Claude Code reads every session
└── plan.md                the original build plan
```

## 3. What happens when a rider sends a message

Following one trip through the code ties the folders together.

1. **Telegram to the bot.** `agla/bot/app.py` receives *"rajiv chowk to hauz khas"*.
   - Menu buttons (Stats, Miles…) are answered directly, without Claude.
   - Repeated off-topic chatter gets a canned redirect (`bot/chatter.py`).
   - A per-rider rate limit caps spend (`bot/limits.py`).
2. **Claude picks a tool.** `agla/llm.py` sends the message to Claude (Sonnet 5.5) with a small set of tools. Claude calls `quote_trip(origin, destination, preference)`.
3. **The tool layer does the work.**
   - `tools/stations.py` resolves the names: fuzzy and Hinglish-tolerant, and asks the rider when a name is ambiguous.
   - `tools/routing.py` plans the route over the graph from `network/graph.py`.
   - `tools/fares.py` prices it from `data/fares.yaml`.
   - `tools/quotes.py` stores route and fare under a quote id.
4. **The reply.** Claude writes a short line with no numbers; the number guard enforces that. `bot/render.py` draws the route card with the real figures, and `tools/payments.py` adds a UPI link and QR code.
5. **"I've paid".** The button calls `tools/trips.py → log_trip(quote_id)`. Post-trip hooks then run in order: visits, then `miles.py`, then `badges.py`. `tools/tickets.py` draws the demo QR ticket.
6. **After the trip.**
   - 📤 Share journey creates a link (`sharing.py`); the page lives in `web/`.
   - ✅ I've reached marks the trip arrived and hands the rider a message to send.
   - The dashboard (`web/templates/app.html`) reads everything back through `/api/*`.

## 4. File by file

### Root

| File | What it is |
| --- | --- |
| `README.md` | What the bot does, how to run it, honest constraints, known limitations. |
| `plan.md` | The original 24-hour build plan, phase by phase. Kept as written; changes are in `docs/architecture.md` §7 and the decisions log. |
| `CLAUDE.md` | Instructions Claude Code loads at the start of every session: ground rules, stack, layout, project scope. |
| `pyproject.toml`, `uv.lock` | Dependencies, managed by `uv`. The project isn't installed as a package, so run everything as `uv run python -m ...` from the root. |
| `.python-version` | Python 3.12. |
| `.env.example` | The environment variables the app needs (keys, bot token, UPI address, dashboard secret). Copy to `.env`, which is gitignored. |
| `.gitignore` | Keeps secrets, the SQLite database (and its WAL files) and logs out of git. |
| `.gitleaks.toml` | Secret-scanner config: gitleaks' default rules plus one for UPI payment addresses. |
| `.mcp.json` | MCP servers available to Claude Code in this project (see §5). |

### `agla/`: the application

| File | What it does |
| --- | --- |
| `__main__.py` | Entry point. `python -m agla [--tunnel]` runs the Telegram bot (long polling) and the web app (uvicorn) in one event loop with one SQLite connection. With `--tunnel` it starts a Cloudflare quick tunnel for a public https URL, and a watchdog replaces the tunnel if it dies. |
| `config.py` | Reads `.env` once into a frozen `Settings`. `now()` is the only clock (Asia/Kolkata). |
| `db.py` | SQLite schema (users, quotes, trips, visits, badges, miles ledger, vouchers, Wrapped recaps, shares) and migrations (`user_version` 4). SQL only, no business rules. |
| `llm.py` | The Claude tool-use loop for the bot: system prompt, tool definitions, prompt caching, the number guard, a short chat history. Also writes the Metro Wrapped narration, using the `metro-wrapped-voice` skill as its prompt. |
| `mcp_server.py` | **agla-mcp**: the tool layer as an MCP server over stdio, so Claude Code or Claude Desktop can plan routes and read stats directly. |
| `badges.py` | Badge rules (first ride, explorer, streaks, line collector…), checked after every trip. |
| `miles.py` | Metro Miles: earning rules from `data/miles.yaml`, the miles ledger, demo reward redemption. |
| `sharing.py` | Journey sharing: where the rider probably is (from the timetable, not GPS), expiring share links, and "I've reached" (with an "Are you sure?" if it's tapped well before the ETA). |
| `wrapped.py` | Metro Wrapped: a month's stats, the three-stop story slides with their "what it means" lines, and the warm share card (Pillow). |

#### `agla/tools/`: the tool layer

This is the only API the front ends may use. Results are frozen dataclasses; user-facing errors raise `ToolError`.

| File | What it does |
| --- | --- |
| `__init__.py` | The public surface: re-exports every tool, plus the domain modules (lazily, to avoid a circular import). Registers the post-trip hooks. |
| `types.py` | Result types: `Station`, `Route`, `Leg`, `Fare`, `Quote`, `Trip`, `Stats`, `MilesSummary`… Every number a front end shows comes from one of these. |
| `stations.py` | Station search and resolution: fuzzy matching over names and aliases, Hinglish-tolerant. Ambiguous names ("dwarka") return candidates to ask about. |
| `routing.py` | Route planning: fastest, fewest changes, or cheapest (prices several candidate routes). |
| `fares.py` | Fares: DMRC distance slabs (on shortest track distance, with per-line track factors), Airport Express and Rapid Metro official tables, NMRC station-count slabs. |
| `quotes.py` | Stores a priced route under a quote id (30-minute expiry). Payments refer to the quote, so the LLM can never set an amount. |
| `payments.py` | UPI intent link and QR code. Payment isn't verified. |
| `trips.py` | `log_trip` (idempotent, owner-checked) and the post-trip hook registry. |
| `tickets.py` | The demo QR ticket image, clearly marked DEMO. |
| `users.py` | Riders: internal ids, Telegram ids at the edge, language preference. |
| `stats.py` | Rider statistics and visited stations. |
| `insights.py` | Dashboard data: map, per-line completion, weekly charts, Wrapped archive months. |
| `intent.py` | A free, local "is this about the metro?" check for the off-topic policy. |
| `auth.py` | Dashboard login: Telegram Mini App `initData` signature, or a signed 7-day magic link. |
| `storage.py` | Opens the database for front ends that don't own a connection (MCP server, scripts). |
| `cli.py` | A developer CLI: `uv run python -m agla.tools.cli "rc" "hkv"` prints route and fare. |

#### `agla/network/`: the metro network

| File | What it does |
| --- | --- |
| `build.py` | `python -m agla.network.build` merges the official snapshots (`data/raw/`) and hand-made CSVs (`data/manual/`) into `data/network.json` and the fare tables. Run once; the app never calls an external API. |
| `graph.py` | Loads `network.json` into a networkx graph. Nodes are (station, line); edges are rides, transfers and walks. |
| `geo.py` | Great-circle distance between stations. |

#### `agla/bot/`: the Telegram front end

| File | What it does |
| --- | --- |
| `app.py` | All Telegram handlers: free text to Claude, the button menu, "I've paid", Share journey, I've reached, redeem, language, dashboard, Wrapped. Also keeps Telegram's menu button pointing at the current tunnel URL. |
| `render.py` | Message templates and menu labels. Presentation only: numbers come from tool results. |
| `chatter.py` | Off-topic policy: after a couple of off-topic turns, answer from rotating canned redirects instead of calling Claude. |
| `limits.py` | Per-rider rate limit (10 Claude-backed messages a minute, 150 a day). |

#### `agla/web/`: the web front end

| File | What it does |
| --- | --- |
| `app.py` | FastAPI routes: `/s/{token}` public share page, `/app` dashboard Mini App, `/api/*` JSON (map, badges, miles, redeem, insights, Wrapped and its card), `/healthz`. Handlers are thin and async. |
| `templates/app.html` | The dashboard Mini App: map (Leaflet), badges, miles, insights (Chart.js), and Metro Wrapped as a three-stop "ride". Warm marigold-and-gulabi palette, light and dark. |
| `templates/base.html`, `share.html`, `_status.html`, `ended.html`, `home.html` | The public share page (refreshes every 30 s with HTMX), its live status fragment, the "journey has ended" page, and a small home page. |

### `data/`: everything the app knows

| Path | What it is |
| --- | --- |
| `network.json` | The built network: 275 stations, 14 lines, ride edges with minutes and km, walks. Generated by `agla/network/build.py`; committed. |
| `fares.yaml` | Fare rules per operator, each with its source: DMRC slabs (weekday and Sunday) and track factors, Airport Express and Rapid Metro tables, NMRC slabs, national holidays. |
| `fares/airport_od.csv`, `fares/rapid_od.csv` | Official station-to-station fares for the Airport Express and Rapid Metro. |
| `raw/` | One-time snapshots of official sources: DMRC journey-planner API (stations, times, fares, fare samples), NMRC planner, OpenStreetMap. Used to build the network and to check fares. |
| `manual/` | Hand-made fixes with provenance (`README.md`): Aqua Line, topology links and walks, a coordinate fix, states, display names, and **aliases** (abbreviations and landmarks people type, like "rc" or "cyber hub"). |
| `miles.yaml` | Metro Miles earning rules (per km, off-peak bonus, new station, streak, arrival). |
| `rewards.yaml` | The demo rewards catalogue (concept only, not redeemable). |
| `fonts/` | Baloo 2 and Mukta (OFL licence) for the server-drawn Wrapped card. |

### `scripts/`: tools for running and checking

| File | What it does |
| --- | --- |
| `run.sh` | Keeps the bot up for testing and demos: keeps the Mac awake (`caffeinate`), restarts the app if it exits, logs to `logs/agla.log`. |
| `seed_demo.py` | Seeds a month of realistic trips for a demo rider through the real pipeline, so miles and badges are computed as they would be live. |
| `verify_fares.py` | Prices 405 official DMRC fares on DMRC's own routes and compares (all match; one documented planner quirk is listed separately). Also run by the tests. |
| `fit_track_factors.py` | Checks, and can re-fit, the per-line track-distance factors in `fares.yaml` against every official fare. |
| `e2e_dashboard.py` | Opens the dashboard in a headless browser at phone size, clicks every tab and plays Wrapped in light and dark, fails on any console error, and saves `docs/screenshots/`. |
| `dashboard_link.py` | Prints a signed dashboard link for a normal browser. |

### `evals/`: measuring the LLM

| File | What it does |
| --- | --- |
| `station_parsing.jsonl` | 50 hand-written rider messages (typos, Hinglish, landmarks, ambiguous names) with the expected stations. |
| `run_eval.py` | Runs Sonnet 5.5 and Haiku 5.5 on the set through the Message Batches API and scores them. Both scored 50/50. |
| `resolver_baseline.py` | The same set with no LLM: simple rules plus the station resolver. A free baseline. |
| `results.md`, `results.json` | The recorded results and the decision they led to (stay on Sonnet). |

### `tests/`

174 tests run with `uv run pytest`, and by CI on every push. Each file's docstring says what it covers. Some that are worth knowing:

- `test_layering.py` enforces that front ends only import the tool layer and never run SQL themselves.
- `test_network.py` covers routing and fares, including every official fare.
- `test_llm.py` tests the Claude loop and the number guard with a scripted fake client, so it makes no API calls.
- `test_mcp_server.py` talks to agla-mcp over a real stdio connection.

### `docs/`

| File | What it is |
| --- | --- |
| `architecture.md` | The system as built: layering, data, tool layer, schema, front ends, security notes, and a table of every change from plan.md. |
| `guide.md` | This guide. |
| `Agla-Station-Knowledge-Document.docx` | The whole system in one formal document: product, architecture, nine system design diagrams, data and fares, AI design, security, quality, operations, how it was built. |
| `backlog.md` | Ideas agreed in principle but parked, with estimates (location pins, following a friend's journey, month-end Wrapped). |
| `screenshots/` | Dashboard and Wrapped screenshots taken by `scripts/e2e_dashboard.py`. |
| `build-journal.html` | The build timeline as one page (generated by the `build-journal` skill, §5). |

### `ledger/`: the process ledger

The build process is part of the deliverable, so it was recorded as it happened.

| File | What it is |
| --- | --- |
| `hook.py` | One script for every Claude Code hook event. Appends a line per prompt and tool call to `events.jsonl`, redacting secrets, `.env` values, emails and UPI addresses. Never blocks a session. |
| `events.jsonl` | The raw log: about 1,500 events (prompts, tool calls, turn ends, compactions), written automatically. |
| `decisions.md` | The human-curated log: every `/decision` (and `OVERRIDE`, when the human went against Claude's suggestion), `/surprise` and `/checkpoint`. |
| `chats/` | Conversations from before the hooks existed (the kickoff). |
| `build_timeline.py` | Merges events, decisions, git history and chats into one timeline (`timeline.json`) with stats. |

### `.github/workflows/ci.yml`

On every push and pull request, CI runs two jobs:

- **test:** ruff, then the full test suite, including all 405 official fares.
- **secrets:** gitleaks scans every commit for secrets, including UPI addresses.

Actions are pinned by commit hash.

## 5. Claude: how it was used to build this

The whole project was built in Claude Code (Claude Opus 5.5) over one long session, phase by phase from `plan.md`. A human made every product decision; Claude proposed, built and tested. Everything Claude-related lives inside this repo (`.claude/`, `.mcp.json`), so nothing depends on one person's global setup.

### Claude Code features

| Feature | Where | What it did here |
| --- | --- | --- |
| **CLAUDE.md** | `CLAUDE.md` | Standing rules loaded every session ("code decides, the LLM narrates", "never invent fares", "never commit secrets", "ask before changing the architecture"). |
| **Plan mode** | Phase 1 | Designed the module interfaces and database schema before any code; the result became `docs/architecture.md`. |
| **Hooks** | `.claude/settings.json` → `ledger/hook.py` | Seven events (session start, prompt, before and after each tool, turn end, subagent end, compaction) each append a line to the ledger. This is how the process was captured without manual notes. |
| **Slash commands** | `.claude/commands/` | **`/decision`** asks five questions (question, options, Claude's suggestion, choice, why) and logs it, tagged `OVERRIDE` if the human chose differently. **`/surprise`** logs something unexpected. **`/checkpoint`** logs a status line, checks nothing secret is about to be committed, commits and pushes. |
| **Status line** | `.claude/statusline.py` | Shows the model and session cost in the terminal. (It doesn't run in the VS Code extension.) |
| **Subagents** | `.claude/agents/` | Separate Claude instances with their own brief and limited tools (below). |
| **Skills** | `.claude/skills/` | Reusable instructions Claude loads when a task matches (below). |
| **MCP servers** | `.mcp.json` | Extra tools for Claude Code (below). |
| **Plugin** | `.claude-plugin/` | The whole setup packaged for reuse (below). |

### Subagents (created for this project)

| Agent | Brief | When it was used |
| --- | --- | --- |
| `reviewer` | An independent, read-only code audit by a reviewer who hasn't seen the build: bugs, leaked secrets, numbers stated by the LLM, business logic in front ends, privacy in sharing. Reports ranked findings with file and line. | Phase 10. It found 15 issues, including a real fare bug the tests had missed and forgeable dashboard links; all were fixed or documented, each with a regression test. |
| `eval-runner` | Runs the station-parsing eval through the Message Batches API and checks the report for misgrading. | Phase 5 (Sonnet vs Haiku). |
| `gtfs-explorer` | Downloads and inspects GTFS transit feeds. | Phase 2. It found the official DMRC GTFS download was broken (404), which is why the network comes from journey-planner snapshots instead. |

### Skills

**Created for this project:**

| Skill | What it is |
| --- | --- |
| `metro-wrapped-voice` | The voice for Metro Wrapped: cheeky, warm, Delhi, under 60 words, numbers only from the stats. Used by Claude Code when writing Wrapped copy, **and** at runtime: `agla/llm.py` builds the narration prompt from this file, so the product and the dev tooling share one source. |
| `build-journal` | Turns the ledger timeline into a single HTML page with three lanes (human prompts, Claude's actions, decisions) and the build's stats. Created with `skill-creator` in Phase 11. |

**Vendored from [anthropics/skills](https://github.com/anthropics/skills)** (copied into the repo with their licences; see `.claude/skills/SOURCES.md`):

| Skill | What it did here |
| --- | --- |
| `mcp-builder` | Guided the design of agla-mcp: tool naming, annotations, structured output, the stdio test. |
| `frontend-design` | Design direction for the dashboard and the Wrapped redesign. |
| `webapp-testing` | Patterns for the Playwright browser checks behind `scripts/e2e_dashboard.py`. |
| `skill-creator` | Used to create the `build-journal` skill. |

**Built into Claude Code:** `claude-api` (the reference for Anthropic SDK usage, model ids, prompt caching and pricing) was used whenever code called Claude.

### MCP servers (`.mcp.json`)

| Server | What it is | What it did here |
| --- | --- | --- |
| `playwright` | Microsoft's Playwright MCP: lets Claude drive a real browser. | DMRC's journey-planner API rejects non-browser requests, so the official station, time and fare data was read once through a real browser and snapshotted. Also used to inspect the dashboard. |
| `agla` | **agla-mcp**, built in Phase 3 (`agla/mcp_server.py`). | Exposes seven read-only tools: `agla_search_station`, `agla_plan_route`, `agla_get_fare`, `agla_get_stats`, `agla_get_visited_stations`, `agla_get_badges`, `agla_get_miles`. Claude Code used it to answer route questions during the build, and it works in Claude Desktop too. It has no auth, so it's local stdio only. |

### The `agla-dev` plugin (`.claude-plugin/`)

The same setup, installable in any project with `/plugin install agla-dev --marketplace Tzing66/agla-station`:

- the ledger hooks
- the three commands
- the three subagents
- the `metro-wrapped-voice` and `build-journal` skills

| File | Contents |
| --- | --- |
| `plugin.json` | The manifest. |
| `hooks.json` | The hook wiring. |
| `marketplace.json` | Makes the repo a one-plugin marketplace. |
| `icon.png` | The plugin icon. |

## 6. Claude inside the product

| Where | How Claude is used |
| --- | --- |
| Bot conversations (`agla/llm.py`) | **Claude Sonnet 5.5** via the Anthropic Python SDK, at low effort. Tool use with seven tools, none of which can pay, log a trip or redeem. **Prompt caching** on the system prompt and tool definitions. **Server-side fallbacks** if a reply is refused. Language (English, Hinglish, हिंदी) is set per rider in a per-turn system note. |
| Number guard (`agla/llm.py`) | Every digit in Claude's reply must come from that turn's tool results, and trip replies may contain no numbers at all. Otherwise the reply falls back to a template. |
| Metro Wrapped narration | A short recap written from the month's stats with the `metro-wrapped-voice` skill as prompt, checked by the same guard and cached once it passes. |
| Cost controls | Menu buttons and repeated off-topic chatter never call Claude. Per-rider rate limits, at most 4 tool rounds per message, chat history capped at 6 messages. |
| Evaluation (`evals/`) | Sonnet 5.5 vs Haiku 5.5 on 50 station-parsing cases via the **Message Batches API**. Both scored 50/50; the bot stays on Sonnet. |

## 7. Where to change things

| To… | Edit | Then |
| --- | --- | --- |
| Add a name riders type for a station | `data/manual/aliases.csv` | `uv run python -m agla.network.build` |
| Change a fare rule or slab | `data/fares.yaml` (with its source) | `uv run python -m scripts.verify_fares` and `scripts.fit_track_factors` |
| Change how miles are earned | `data/miles.yaml` | tests in `test_miles_badges.py` |
| Add a reward | `data/rewards.yaml` | — |
| Add a badge | `agla/badges.py` | — |
| Change Wrapped's tone | `.claude/skills/metro-wrapped-voice/SKILL.md` | — |
| Change Wrapped's slides | `agla/wrapped.py` → `wrapped_story` | `uv run python -m scripts.e2e_dashboard` |
| Change a bot message | `agla/bot/render.py` | — |
| Change the dashboard | `agla/web/templates/app.html` | `scripts.e2e_dashboard` |
| Give Claude a new tool | add it to `agla/tools/`, then expose it in `agla/llm.py` (and `mcp_server.py`) | `test_llm.py`, `test_layering.py` |
| Change the database | `agla/db.py`: add a migration and bump `user_version` | `docs/architecture.md` §4 |
