# Agla Station — Architecture

> Agreed in Phase 1 (plan mode), 2026-10-23. Source of truth for module interfaces and the DB schema; update it when they change.

## Context

Phase 1 of plan.md: agreed the module interfaces for `agla/tools/` and the full SQLite schema (core + Phase 6 + Phase 8 tables) before writing code.

Three deliberate deviations from plan.md, agreed with the human:
1. **Quote IDs**: the LLM never passes amounts or logs trips. It calls `quote_trip`; the server stores route+fare; the payment link and "✅ I've paid" button reference `quote_id`; only the button handler calls `log_trip(quote_id)`.
2. **One polling safety job** (every 20s, `due_safety_actions(now)`) instead of three run_once jobs per trip. DB is the only state, so restarts need no rescheduling.
3. **One process**: `python -m agla` runs FastAPI (uvicorn) + the PTB bot in one asyncio loop. agla-mcp stays a separate stdio process.


## 1. Layering

```
 Telegram bot (agla/bot)   FastAPI web (agla/web)   agla-mcp (agla/mcp_server.py)
          \                       |                        /
           └──────────── agla.tools  (public API, the only import) ───┘
                         /        |          \
           agla/network      agla/db.py     domain modules: badges.py miles.py
           (load+graph)      (SQL only)     sharing.py wrapped.py
```

- Front ends import **only** `agla.tools` (plus `agla.config`). Enforced by `tests/test_layering.py` (AST scan of `agla/bot`, `agla/web`, `agla/mcp_server.py`).
- `agla/tools/` = thin public façade + pure computations (routing, fare, position). Stateful logic lives in the domain modules the plan names (`badges.py`, `miles.py`, `sharing.py`, `wrapped.py`); tools re-export them with stable signatures.
- `agla/db.py` holds the schema and SQL, no business rules. Connections passed explicitly (`conn` first arg) so tests use `:memory:`.
- `agla/llm.py` sits beside the bot: Claude tool-use loop whose tool handlers call `agla.tools`.
- **Time**: every time-dependent function takes `now: datetime` (tz-aware, `Asia/Kolkata`); stored as ISO-8601 strings with `+05:30`. `agla.config.now()` is the only clock.
- **Config**: `agla/config.py` reads `.env` once into a frozen `Settings`. New env var: `ADMIN_TELEGRAM_IDS` (comma list, gates `/demo_fast`).

## 2. Network data (agla/network/)

> **Changed in Phase 2:** the source is a snapshot of DMRC's official journey-planner API plus NMRC's planner, not GTFS (the OTD GTFS download is broken server-side). Provenance: `data/manual/README.md`.

- `build.py` — `python -m agla.network.build` merges `data/raw/` snapshots and `data/manual/*.csv` into **`data/network.json`** and `data/fares/*.csv` (all committed; the app never calls external APIs at runtime).
- `geo.py` — haversine distance.
- `graph.py` — `Network` loaded from `network.json` once (`functools.cache`), as a `networkx.DiGraph`:
  - nodes `(station_id, line_id)`; ride edges carry `minutes`, `km` and `fare_km`; the Rapid Metro loop edges are one-way.
  - transfer edges between lines at a station: 6 min; same-family lines (Pink ↔ Pink ext.) 2 min and not counted as a change; walk edges (Sector 52 ↔ 51, Dhaula Kuan footbridge) use their own minutes.
  - virtual `("src", station_id)` / `("dst", station_id)` nodes at 0 cost so the start/end line choice isn't penalised.
  - `fewest_changes` = minutes + 1000 × (transfer + walk edges).
- IDs: `station_id` = slug of the display name (`rajiv_chowk`, `noida_sector_52`); `line_id` = `DMRC_YELLOW`, `DMRC_AIRPORT`, `RAPID`, `NMRC_AQUA` …
- Fares: `fares.yaml` per operator — DMRC distance slabs, Airport Express and Rapid Metro official per-pair tables, NMRC station-count slabs, Rapid Metro flat `through_fare` when changing at Sikanderpur. Cross-operator = sum of each operator's contiguous segment.

## 3. Tool layer interfaces (`agla/tools/`)

Types (`agla/tools/types.py`, frozen dataclasses, `to_dict()` for JSON/MCP/LLM):

```python
Station(station_id, name, aliases: list[str], lat, lon, state: Literal["Delhi","Haryana","UP"], lines: list[str], operator)
StationMatch(station_id, name, score: float, matched_on: str, lines: list[str])
Stop(station_id, name, line_id, cum_minutes: float, is_interchange: bool)
Leg(line_id, line_name, operator, from_id, to_id, station_ids: list[str], minutes: float, start_minutes, end_minutes)  # line_id "WALK" for walks
Route(from_id, to_id, preference, legs: list[Leg], stops: list[Stop], interchange_ids: list[str], minutes: int, distance_km: float)
FareComponent(operator, from_id, to_id, amount: int, rule: str, source_url: str)
Fare(total: int, day_type: Literal["weekday","sunday_holiday"], components: list[FareComponent], currency="INR", note: str|None)
ToolError(Exception)  # user-facing failure: unknown station, no route, missing fare
Quote(quote_id: str, route: Route, fare: Fare, created_at, expires_at)
PaymentLink(upi_uri: str, qr_png: bytes, amount: int, note: str)
TripResult(trip_id, ticket_id, ticket_png: bytes, route, fare, eta, new_visits: list[str], miles: list[MilesAward], new_badges: list[BadgeStatus])
Position(state: Literal["not_started","riding","at_station","changing","arrived","overdue"], text: str, prev_id, next_id, progress_pct: int, eta, minutes_left: int)
```

Functions (all numbers originate here):

| Module | Function | Phase |
| --- | --- | --- |
| `stations.py` | `search_station(query, limit=3) -> list[StationMatch]` (rapidfuzz over names+aliases, Hinglish normalisation: strip "se/to/tak/metro/station", expand `sec`→`sector`) · `get_station(id) -> Station` · `list_stations() -> list[Station]` | 2 |
| `routing.py` | `plan_route(from_id, to_id, preference="fastest"|"fewest_changes"|"cheapest", on: date|None) -> Route` ("cheapest" prices fastest/fewest-changes candidates with and without Airport Express) | 2 |
| `fares.py` | `get_fare(route, on: date) -> Fare` (rules from `data/fares.yaml`; cross-operator = sum of components) | 2 |
| `quotes.py` | `quote_trip(conn, user_id, from_id, to_id, preference, now) -> Quote` (stores route+fare, 30-min expiry) · `get_quote(conn, quote_id)` | 4 |
| `payments.py` | `make_payment_link(quote: Quote, settings) -> PaymentLink` (amount comes from the stored quote, never an argument) | 4 |
| `trips.py` | `log_trip(conn, quote_id, now) -> TripResult` (idempotent per quote; writes trip, then runs post-trip hooks) · `register_post_trip_hook(fn)` | 4 |
| `tickets.py` | `render_ticket(trip) -> bytes` (PNG, "DEMO" watermark) | 4 |
| `users.py` | `get_or_create_user(conn, telegram_id, first_name) -> User` · `set_safety(conn, user_id, on)` | 4 |
| `stats.py` | `get_stats(conn, user_id) -> Stats` · `get_visited_stations(conn, user_id) -> list[Visit]` · `line_completion(conn, user_id)` | 4 |
| re-export `badges.py` | `get_badges(conn, user_id) -> list[BadgeStatus]` (earned+locked w/ hint) · `evaluate_badges(conn, user_id, now)` (hook) | 6 |
| re-export `miles.py` | `get_miles(conn, user_id) -> MilesSummary` · `award_trip_miles(conn, trip, now)` (hook) · `list_rewards()` · `redeem_reward(conn, user_id, reward_id, now) -> Voucher` | 6 |
| re-export `wrapped.py` | `wrapped_stats(conn, user_id, month) -> WrappedStats` · `save_recap(...)` · `list_recaps(conn, user_id)` · `render_card(stats, text) -> bytes` | 7 |
| re-export `sharing.py` | `estimate_position(trip, now) -> Position` (pure) · `create_share(conn, trip_id, now) -> Share` · `get_share_view(conn, token, now) -> ShareView \| Expired` · `confirm_arrival(conn, trip_id, now)` · `create_trust_invite` / `accept_trust_invite` · `due_safety_actions(conn, now, fast=False) -> list[SafetyAction]` · `mark_safety_stage(...)` | 8 |

Post-trip hooks run in order: `record_visits` → `award_trip_miles` → `evaluate_badges` → `open_safety_check` (if user.safety_on). The bot never changes when a hook is added.

**Visit rule**: origin, destination and interchange stations count as visited; passed-through stations don't. Logged as a decision; noted in README.

## 4. SQLite schema (`agla/db.py`, WAL mode, `PRAGMA foreign_keys=ON`)

```sql
-- core (Phase 4)
users(id INTEGER PRIMARY KEY, telegram_id INTEGER UNIQUE NOT NULL, first_name TEXT,
      safety_on INTEGER DEFAULT 0, demo_fast INTEGER DEFAULT 0, created_at TEXT NOT NULL)
quotes(id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users, from_id TEXT, to_id TEXT,
       preference TEXT, route_json TEXT, fare_json TEXT, created_at TEXT, expires_at TEXT)   -- NEW
trips(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users, quote_id TEXT UNIQUE REFERENCES quotes, -- quote_id NEW
      ticket_id TEXT UNIQUE,                                                                            -- NEW
      from_id TEXT, to_id TEXT, stations_json TEXT, lines_json TEXT, interchanges INTEGER,
      minutes INTEGER, distance_km REAL, fare REAL, depart_at TEXT, eta TEXT, created_at TEXT)
visits(user_id INTEGER, station_id TEXT, first_visit TEXT, count INTEGER, PRIMARY KEY(user_id, station_id))
badges(user_id INTEGER, badge_id TEXT, earned_at TEXT, PRIMARY KEY(user_id, badge_id))

-- Phase 6
miles_ledger(id INTEGER PRIMARY KEY, user_id INTEGER, trip_id INTEGER NULL, delta INTEGER,
             reason TEXT NOT NULL, created_at TEXT)
vouchers(id INTEGER PRIMARY KEY, user_id INTEGER, reward_id TEXT, miles_spent INTEGER,
         code TEXT UNIQUE, created_at TEXT)

-- Phase 7
wrapped_recaps(user_id INTEGER, month TEXT, stats_json TEXT, text TEXT, created_at TEXT,
               PRIMARY KEY(user_id, month))                                                   -- NEW (archive tab)

-- Phase 8
shares(token TEXT PRIMARY KEY, user_id INTEGER, trip_id INTEGER, created_at TEXT,
       expires_at TEXT, arrived_at TEXT NULL)
trusted_contacts(user_id INTEGER, contact_user_id INTEGER, accepted_at TEXT,
                 PRIMARY KEY(user_id, contact_user_id))
trust_invites(token TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT, expires_at TEXT,
              used_by INTEGER NULL)                                                           -- NEW
safety_checks(trip_id INTEGER PRIMARY KEY, user_id INTEGER, eta TEXT, stage INTEGER DEFAULT 0,
              arrived_at TEXT NULL)
```

Indexes: `trips(user_id, depart_at)`, `miles_ledger(user_id, created_at)`, `safety_checks(arrived_at, stage)`.
Balance = `SUM(delta)` from `miles_ledger` (redemptions are negative rows), so the ledger is the single source of truth.
Schema migration: `db.init(conn)` runs `CREATE TABLE IF NOT EXISTS`; a `schema_version` pragma (`user_version`) bumps if a table changes.

## 5. Front ends

- **Bot (`agla/bot/`)**: handlers only. Free text → `llm.respond(history[-6:], text, user)`. Route/fare cards are **rendered by templates from tool results**; the LLM adds a short line around them. **Number guard**: every digit sequence in LLM text must appear in that turn's tool results, else fall back to the template text. Buttons carry `quote_id` / `trip_id` (fits Telegram's 64-byte callback limit).
- **LLM tools exposed to Claude**: `search_station`, `quote_trip`, `get_stats`, `get_badges`, `get_miles`, `list_rewards`. *Not exposed*: `log_trip`, `redeem_reward`, `confirm_arrival` (buttons only). Prompt caching on system prompt + tool defs; history in memory (`chat_data`), last 6 messages.
- **Safety job**: one `JobQueue.run_repeating(20s)` → `due_safety_actions(conn, now)` → send ask/nudge/alert → `mark_safety_stage`. Offsets 0/+15/+25 min; `demo_fast` → 0/+15/+25 **seconds**.
- **Web (`agla/web/`)**: `/s/{token}` public share page; `/app` Mini App; `/api/*` JSON (initData HMAC auth, `itsdangerous` magic-link fallback). Handlers call tools only.
- **MCP (`agla/mcp_server.py`)**: stdio; network tools stateless; user tools take optional `telegram_id`, default = seeded demo user (local, single-user).
- **Entry point**: `python -m agla` → uvicorn serving FastAPI, PTB started/stopped in FastAPI lifespan (polling). One process, one SQLite writer.

## 6. Decisions behind this design (see `ledger/decisions.md`)

From plan.md: Telegram over WhatsApp · UPI link over Paytm API · Mini App over separate website · timetable ETA over GPS.
Agreed today: quote IDs (LLM can't set amounts/log trips) · single polling safety job · one process · visit rule (origin/destination/interchanges).
