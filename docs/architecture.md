# Agla Station: architecture

The system as built (2026-10-23). Phase 1 agreed the shape in plan mode; every later change is logged with its reasoning in `ledger/decisions.md`. Update this file when interfaces or the schema change.

## 1. Layering

```
 Telegram bot (agla/bot)    web app (agla/web)    agla-mcp (agla/mcp_server.py)
          \                        |                        /
           └──────────── agla.tools (public API, the only import) ───┘
                    /             |               \
          agla/network        agla/db.py       domain modules re-exported by agla.tools:
          (build + graph)     (schema, SQL)    badges.py  miles.py  sharing.py  wrapped.py
```

- Front ends import only `agla.tools` and `agla.config` (the bot also uses `agla.llm`, which sits beside it). `tests/test_layering.py` checks this with an AST scan and also imports each module first in a fresh process (the domain modules are re-exported lazily to avoid a circular import).
- `agla/db.py` holds schema, migrations and a `tx()` helper; no business rules. Connections are passed explicitly, so tests use `:memory:`.
- **Time:** every time-dependent function takes `now` (tz-aware, `Asia/Kolkata`); `agla.config.now()` is the only clock. Stored as ISO-8601 with `+05:30`.
- **Config:** `agla.config.settings()` reads `.env` once into a frozen `Settings`.
- **One process:** `python -m agla [--tunnel]` runs uvicorn (web) and the Telegram bot (long polling) in one asyncio loop, one SQLite writer; `--tunnel` starts cloudflared and hands its https URL to the bot. agla-mcp is a separate stdio process.

## 2. Network data (`agla/network/`, `data/`)

- Source: a one-time snapshot of DMRC's journey-planner API (stations, coordinates, line order, adjacent-station times, official fares), NMRC's planner and fare table (Aqua Line), and OpenStreetMap (Aqua coordinates). The planned GTFS feed was unavailable (its download 404s server-side). Provenance and known approximations: `data/manual/README.md`.
- `build.py` (`python -m agla.network.build`) merges `data/raw/` and `data/manual/*.csv` into `data/network.json` and `data/fares/*.csv`, all committed. The app never calls an external API at runtime.
- `graph.py` loads a `networkx.DiGraph`: nodes `(station_id, line_id)`; ride edges carry `minutes`, `km` and `fare_km`; the Rapid Metro loop is one-way; transfers cost 6 min (2 min and not counted as a change between same-family lines, e.g. Pink ↔ Pink extension); walks (Sector 52 ↔ 51, Dhaula Kuan footbridge) use their own minutes; zero-cost `src`/`dst` nodes per station.
- Fares (`data/fares.yaml`): DMRC distance slabs, Airport Express and Rapid Metro official per-pair tables, NMRC station-count slabs, Rapid Metro flat through-fare when changing at Sikanderpur. Cross-operator trips pay the sum of each operator's contiguous segment. 376/384 official samples match (`scripts/verify_fares.py`); the misses are documented.

## 3. Tool layer (`agla/tools/`)

Results are frozen dataclasses in `types.py` with `to_dict()`; user-facing failures raise `ToolError`.

| Module | Main functions |
| --- | --- |
| `stations.py` | `search_station(query, limit)`, `resolve_station(query)` (id or messy name; `ToolError` listing candidates when ambiguous), `get_station`, `list_stations` |
| `routing.py` | `plan_route(from_id, to_id, preference="fastest"\|"fewest_changes"\|"cheapest", on)` |
| `fares.py` | `get_fare(route, on)`, `day_type(on)` |
| `quotes.py` | `quote_trip(conn, user_id, origin, destination, preference, now)` stores route + fare (30-min expiry), `get_quote` |
| `payments.py` | `make_payment_link(quote, upi_vpa, payee)`: amount always from the stored quote |
| `trips.py` | `log_trip(conn, quote_id, telegram_id, now)` (idempotent, owner-checked), `register_post_trip_hook`, `get_trip` |
| `tickets.py` | `render_ticket(trip)`: demo QR ticket PNG |
| `users.py` | `get_or_create_user`, `get_user`, `find_user_by_telegram_id`, `set_language` |
| `stats.py` | `get_stats`, `get_visited_stations` |
| `insights.py` | `map_data`, `line_completion`, `insights`, `trip_months` (dashboard) |
| `intent.py` | `is_metro_related(text)`: free local check used by the off-topic policy |
| `auth.py` | `verify_init_data` (Telegram Mini App HMAC, 24 h), `sign_/verify_dashboard_token` (magic link, 7 days) |
| `storage.py` | `open_database()`, `DEMO_TELEGRAM_ID` |
| re-exported `miles.py` | `get_miles`, `list_rewards`, `redeem_reward`, `list_vouchers`, `award_arrival`; hook `award_trip_miles` |
| re-exported `badges.py` | `get_badges`; hook `badges_hook` |
| re-exported `wrapped.py` | `wrapped_stats`, `template_text`, `save_recap`, `get_recap`, `fresh_recap`, `render_card` |
| re-exported `sharing.py` | `estimate_position` (pure), `create_share`, `get_share_view`, `share_message`, `confirm_arrival` |

Post-trip hooks run in order inside the trip's transaction: `record_visits` → miles → badges. The bot never changes when a hook is added.

**Visit rule:** origin, destination and interchange stations count as visited; stations passed through don't.

## 4. SQLite schema (`agla/db.py`, WAL, foreign keys on, `user_version` = 4)

```sql
users(id PK, telegram_id UNIQUE, first_name, language DEFAULT 'en', created_at)
quotes(id PK, user_id, from_id, to_id, preference, route_json, fare_json, created_at, expires_at)
trips(id PK, user_id, quote_id UNIQUE, ticket_id UNIQUE, from_id, to_id, stations_json, lines_json,
      route_json, fare_json, interchanges, minutes, distance_km, fare, depart_at, eta, arrived_at NULL, created_at)
visits(user_id, station_id, first_visit, count, PK(user_id, station_id))
badges(user_id, badge_id, earned_at, PK(user_id, badge_id))
miles_ledger(id PK, user_id, trip_id NULL, delta, reason NOT NULL, created_at)   -- balance = SUM(delta)
vouchers(id PK, user_id, reward_id, miles_spent, code UNIQUE, created_at)
wrapped_recaps(user_id, month, stats_json, text, created_at, PK(user_id, month))
shares(token PK, user_id, trip_id, created_at, expires_at, arrived_at NULL)
```

Migrations run in `db.migrate()`: v2 adds `users.language`, v3 adds `trips.arrived_at`, v4 drops the removed safety-check tables and columns.

## 5. Front ends

- **Bot (`agla/bot/`):** free text goes to the LLM agent; route cards, tickets, stats, miles, badges and Wrapped are templates over tool results. A persistent button menu (stats, miles, badges, Wrapped, dashboard, language) replaces slash commands and never calls the LLM. Repeated off-topic chatter gets canned redirects without an API call (`chatter.py`). Tickets carry 📤 Share journey and ✅ I've reached, both ending in Telegram's own share sheet so the rider picks the recipient.
- **LLM (`agla/llm.py`):** `claude-sonnet-5-5`, low effort, prompt caching on system prompt + tools, server-side refusal fallbacks, language in a per-turn system note, 6-message plain-text history annotated with what the app showed. Tools exposed: `quote_trip`, `search_station`, `get_stats`, `get_visited_stations`, `get_miles`, `get_badges`, `list_rewards`. Never exposed: logging trips, redeeming, arrival (buttons only). Number guard on every reply. Metro Wrapped narration uses the `metro-wrapped-voice` skill as its prompt, guarded the same way.
- **Web (`agla/web/`):** `/s/{token}` public share page (HTMX refresh every 30 s, noindex/no-referrer/no-store); `/app` dashboard Mini App (map, badges, miles with redeem, insights, Wrapped archive) over `/api/*`, authenticated by Telegram `initData` or a signed magic link.
- **MCP (`agla/mcp_server.py`):** stdio, `mcp` 2.x `MCPServer`, tools prefixed `agla_`; route/fare tools take names or ids; rider tools default to the seeded demo rider.

## 6. Changes from the original plan

| Area | plan.md | As built | Why (see ledger) |
| --- | --- | --- | --- |
| Payments | LLM calls `make_payment_link(route, fare)` and `log_trip` | Stored quote ids; trips and redemption only via buttons | The LLM must never set an amount |
| Network data | DMRC GTFS from Delhi OTD | DMRC/NMRC journey-planner snapshots + OSM | GTFS download broken server-side |
| Routing | fastest, fewest changes | + cheapest | Fastest can route via the pricier Airport Express |
| Metro Miles | 5/km, +50 new station, +20 streak | 1/km, +25, +10 | 5/km gave a commuter five free day passes a month |
| Safety check | Timed ask/nudge/alert to trusted contacts, `/demo_fast` | Share link + traveller-sent "I've reached" | Setup was confusing; simpler, rider-controlled flow (OVERRIDE) |
| Commands | Slash commands | Persistent button menu | Easier to use; no LLM calls for menu taps |
| Language | (not planned) | English, Hinglish, हिंदी per rider | Clear English replies were needed |
| Runtime model | Sonnet unless Haiku matches | Sonnet (Haiku matched 50/50) | Reply quality already tested; eval kept for scaling (OVERRIDE) |
