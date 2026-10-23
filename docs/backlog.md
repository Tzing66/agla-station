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
