# Agla Station

Telegram bot for the Delhi NCR metro (DMRC lines, Airport Express, Rapid Metro Gurugram, Noida Aqua Line): plain-language route planning, official fares, UPI payment link, mock QR tickets, Metro Miles, badges, monthly Metro Wrapped, journey sharing with a timetable ETA and an "I've reached" message. Dashboard is a Telegram Mini App.

`plan.md` is the original build plan; `docs/architecture.md` is the system as built, and `ledger/decisions.md` records every change from the plan and why. **Stop and ask before any decision that changes the architecture.**

## Ground rules

- **Code decides, the LLM narrates.** Routes, fares, ETAs, miles, badges, stats and recap numbers are computed in Python. The LLM only picks tools, parses intent and writes words; a number guard rejects any number in its reply that didn't come from a tool result.
- **One tool layer.** All metro logic lives in `agla/tools/` (plus the domain modules it re-exports: `badges.py`, `miles.py`, `sharing.py`, `wrapped.py`). The bot, the MCP server and the web app are thin front ends; `tests/test_layering.py` enforces it.
- **Money stays in code.** The LLM can quote a trip but never set an amount, log a trip or redeem: payments reference a stored quote id; "I've paid", "I've reached" and redeem are buttons.
- **Cost discipline.** `claude-sonnet-5-5` at low effort, prompt caching on system prompt + tools, chat history capped at 6 plain-text messages, menu buttons and repeated off-topic chatter answered without an API call.
- **Privacy by default.** Share links expire and show the first name only; the bot never messages anyone but the rider (sending "I've reached" uses Telegram's own share sheet).
- **Never commit secrets.** All keys in `.env` (gitignored, along with the SQLite db and its WAL files); the ledger hook redacts `.env` values, tokens and emails. The repo is **public**. (The bot's Telegram handle is the one `.env` value that is public on purpose: README and QR code.)
- **Never invent fares.** Fares come from official sources recorded in `data/fares.yaml` and are checked by `scripts/verify_fares.py` and a human spot-check.
- Python 3.12 (3.11+ compatible), type hints, `ruff`, `pytest`. Small modules, no framework magic. Run everything from the repo root with `uv run python -m ...` (the project isn't installed as a package).
- After finishing each piece of work: run tests, then remind the human to run `/checkpoint`.

## Honest constraints (also in README)

- Tickets are mock QR tickets; DMRC has no public ticket API.
- Payment is a UPI intent link and is not verified.
- Journey sharing is a timetable estimate, not live GPS.
- Metro Miles and rewards are a concept demo; vouchers say "DEMO — concept only, not redeemable".

## Stack

| Concern | Choice |
| --- | --- |
| Env / deps | `uv` (`uv run pytest`, `uv run ruff check .`) |
| Bot | python-telegram-bot, long polling; persistent button menu instead of slash commands |
| LLM | Anthropic SDK, `claude-sonnet-5-5`, tool use + prompt caching + server-side refusal fallbacks |
| Network data | Snapshot of DMRC's journey-planner API + NMRC planner + OpenStreetMap (GTFS feed was unavailable) |
| Routing | networkx |
| Storage | SQLite (WAL), schema + migrations in `agla/db.py` |
| MCP server | official `mcp` Python SDK 2.x (`MCPServer`), stdio |
| Web | FastAPI + Jinja2 + HTMX (share pages), Leaflet + Chart.js (Mini App) |
| Images | `qrcode` + Pillow (tickets, Wrapped card) |
| Run | `uv run python -m agla --tunnel` (bot + web + cloudflared in one process) |

## Layout

```
.claude/          settings.json (hooks + statusline), commands/, agents/, skills/ (incl. build-journal)
.claude-plugin/   the agla-dev plugin (same setup, installable elsewhere)
.github/          CI: ruff, pytest, gitleaks (.gitleaks.toml adds a UPI-address rule)
.mcp.json         project-scoped MCP servers (Playwright, agla-mcp)
ledger/           hook.py, events.jsonl (auto), decisions.md (/decision /surprise /checkpoint), chats/,
                  build_timeline.py -> timeline.json, journal_notes.json
data/             network.json (built), raw/ (official snapshots), manual/ (hand-made CSVs + provenance),
                  fares.yaml (slabs + track factors), fares/*.csv, miles.yaml, rewards.yaml, fonts/
agla/
  network/        build.py (snapshots -> network.json), graph.py, geo.py
  tools/          THE tool layer (stations, routing, fares, quotes, payments, trips, stats, intent, auth, insights)
  db.py badges.py miles.py sharing.py wrapped.py llm.py config.py
  bot/            Telegram handlers, templates, off-topic chatter policy
  mcp_server.py   agla-mcp
  web/            FastAPI: share pages, dashboard Mini App + JSON API
evals/            station_parsing.jsonl, run_eval.py, resolver_baseline.py, results.md
scripts/          run.sh (keep-awake runner), seed_demo.py, verify_fares.py, fit_track_factors.py,
                  e2e_dashboard.py, dashboard_link.py, bot_qr.py
docs/             architecture.md, guide.md, Agla-Station-Knowledge-Document.pdf/.docx, build-journal.html,
                  backlog.md, telegram-qr.png, screenshots/
tests/
```

## Project scope

Everything Claude-related for this project lives in this directory: project `.claude/`, `.mcp.json` (add MCP servers with `--scope project`). Don't write to `~/.claude`.
