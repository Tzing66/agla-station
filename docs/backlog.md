# Backlog

Ideas agreed in principle, deliberately parked until the core plan (phases 8-11) is done.

## Location -> route (Google Maps / Telegram pin)

Rider shares where they are (or where they're going) instead of typing a station. Parked 2026-10-23: "execute it correctly, but not right now".

| Piece | Est. | Notes |
| --- | --- | --- |
| Telegram location pin -> nearest stations (+ walk estimate) | ~45 min | Pure maths over our 275 station coordinates; no API cost. Reply "Nearest: X (450 m, ~6 min walk)" with buttons to use it as the origin. |
| Google Maps links with coordinates (`/@lat,lon`, `?q=lat,lon`) | +15 min | Parse the URL. |
| Google Maps short links (`maps.app.goo.gl/...`) | +15 min | Follow one redirect, then parse. |
| Destination as a pin | +10 min | Same nearest-station logic. |
| Destination as a place name that isn't a station ("India Gate") | +1 h | Needs geocoding: OSM Nominatim (free, 1 req/s, attribution) or Google Geocoding (key + billing). |

Notes: walk estimate = straight-line distance x 1.3 at 5 km/h, labelled as an estimate. Location is kept only in short-term chat memory, never in the DB or the ledger. The LLM gets "rider's nearest station: X" in the per-turn system note, not raw coordinates.

## Metro Wrapped only at month end

Wrapped should be something to wait for: unlock a month's Wrapped on its last evening (or the 1st of the next month), with a nudge in the chat, instead of being open all month. Kept always available for now so the demo can show it. Parked 2026-10-24.

| Piece | Est. | Notes |
| --- | --- | --- |
| Gate `/api/wrapped` and the chat button on month end | ~20 min | Current month hidden until its last day; past months stay in the archive. A demo flag keeps today's behaviour. |
| "Your October Wrapped is ready" message | ~30 min | Needs a daily job (python-telegram-bot's job queue extra) and only messages riders who had trips that month. |

## Follow a friend's journey in your dashboard

A friend who gets a share link can follow the trip inside their own dashboard: a "Following" tab that appears while the trip is live and disappears after arrival or expiry. Parked 2026-10-24: worth doing, too much for now (~4-5 h).

| Piece | Est. | Notes |
| --- | --- | --- |
| `follows` table (share token, follower), schema v5 | ~20 min | Rows deleted when the share expires. |
| `follow_share`, `list_following` in the tool layer | ~45 min | Live shares only, not your own trip, ~10 followers max; reuse `get_share_view`. |
| Bot deep link `t.me/<bot>?start=w_<token>` | ~30 min | Through the bot, not a `startapp` Mini App link: those need a fixed URL in BotFather and our tunnel URL changes. |
| "Follow in Telegram" button on the share page | ~15 min | The shared message keeps the web link so it still works outside Telegram. |
| `/api/following` + conditional tab with live card | ~1.5 h | Route strip, position, ETA, 30 s refresh. |
| Tests, demo seed, e2e, docs | ~1 h | |

Open decisions: should followers get bot messages (breaks "the bot only messages the rider"; suggested no), should the traveller see who follows (suggested yes), and a "Stop sharing" button (suggested yes).
