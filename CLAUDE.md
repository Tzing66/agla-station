# Agla Station

Telegram bot for the Delhi NCR metro (DMRC, Rapid Metro Gurugram, Noida Aqua Line): plain-language route planning, fares, UPI payment link, mock QR tickets, Metro Miles, badges, monthly Metro Wrapped, journey sharing with a timetable ETA, and an opt-in "I've reached" safety check. Dashboard is a Telegram Mini App.

`plan.md` is the build plan. Work phase by phase; don't start a phase until the previous one meets its "Done when" checks. **Stop and ask before any decision that changes the architecture.**

## Ground rules

- **Code decides, the LLM narrates.** Routes, fares, ETAs, miles, badges, stats and recap numbers are computed in Python. The LLM only picks tools, parses user intent and writes words. Never let the model state a number that did not come from a tool result.
- **One tool layer.** All metro logic lives in `agla/tools/`. The Telegram bot, the MCP server and the dashboard API are thin front ends over it. No business logic in front ends.
- **Cost discipline.** Use `claude-sonnet-5-5` for everything by default. Enable prompt caching on the system prompt and tool definitions. Keep the bot's context small: no chat history beyond the last 6 messages.
- **Privacy by default.** Sharing and safety alerts are opt-in, share links expire, share pages show first name only, and trusted contacts must accept an invite.
- **Never commit secrets.** All keys in `.env`; `.env` is gitignored; the ledger hook scrubs secrets. The repo is **public**, so this includes the UPI VPA.
- **Never invent fares.** Fares come from official sources (recorded with URL + date in `data/fares.yaml`) and are spot-checked by the human.
- Python 3.12 (3.11+ compatible), type hints, `ruff` for lint, `pytest` for tests. Small modules, no framework magic.
- After finishing each phase: run tests, then remind the human to run `/checkpoint`.

## Honest constraints (also in README)

- Tickets are mock QR tickets; DMRC has no public ticket API.
- Payment is a UPI intent link and is not verified.
- Journey sharing is a timetable estimate, not live GPS.
- Metro Miles and rewards are a concept demo; vouchers say "DEMO — concept only, not redeemable".

## Stack

| Concern | Choice |
| --- | --- |
| Env / deps | `uv` (`uv run pytest`, `uv run ruff check`) |
| Bot | python-telegram-bot (polling for dev), `JobQueue` for safety-check timers |
| LLM | Anthropic SDK, `claude-sonnet-5-5`, tool use + prompt caching |
| Routing | networkx |
| Storage | SQLite |
| MCP server | official `mcp` Python SDK, stdio |
| Web | FastAPI + Jinja2 + HTMX, Leaflet, Chart.js |
| QR / images | `qrcode` + Pillow |
| HTTPS for demo | cloudflared tunnel |

## Layout

```
.claude/          settings.json (hooks + statusline), commands/, agents/, skills/
.mcp.json         project-scoped MCP servers (Playwright, agla-mcp)
ledger/           hook.py, events.jsonl (auto), decisions.md (/decision /surprise /checkpoint), chats/
data/             raw/ (GTFS), manual/ (hand-made CSVs), fares.yaml, miles.yaml, rewards.yaml
agla/
  network/        GTFS loading, graph building
  tools/          THE tool layer (pure functions)
  db.py badges.py miles.py sharing.py wrapped.py llm.py
  bot/            Telegram handlers
  mcp_server.py   agla-mcp
  web/            FastAPI: dashboard + public share pages
evals/            station_parsing.jsonl, run_eval.py, results.md
scripts/          seed_demo.py
tests/
```

## Project scope

Everything Claude-related for this project lives in this directory: project `.claude/`, `.mcp.json` (add MCP servers with `--scope project`). Don't write to `~/.claude`.
