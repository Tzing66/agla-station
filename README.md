# Agla Station

A Telegram bot for the Delhi NCR metro network (DMRC, Rapid Metro Gurugram, Noida Aqua Line): ride more, ride safer, have fun doing it.

> Work in progress. See `plan.md` for the build plan.

## Honest constraints

- Tickets are mock QR tickets. DMRC has no public ticket-issuing API.
- Payment is a UPI intent link; payment is not verified.
- Fares come from official sources and are spot-checked by hand; never invented.
- Journey sharing is an estimate from the timetable, not live GPS.
- Metro Miles and rewards are a concept demo. Vouchers are labelled "demo, not redeemable".

## agla-mcp: the metro tools over MCP

`agla/mcp_server.py` exposes the tool layer as an MCP server (stdio), so Claude Code, Claude Desktop or any MCP client can plan NCR metro trips with the same code the bot uses.

| Tool | What it does |
| --- | --- |
| `agla_search_station` | Fuzzy station search: names, abbreviations ("RC", "HKV"), landmarks ("cyber hub"), Hinglish |
| `agla_plan_route` | Route between two stations (names or ids), `fastest` / `fewest_changes` / `cheapest`, with fare |
| `agla_get_fare` | Official token fare for a trip, split per operator with sources |
| `agla_get_stats`, `agla_get_visited_stations`, `agla_get_badges`, `agla_get_miles` | Rider data (available once the bot logs trips) |

Ambiguous names ("dwarka") return an error listing the candidates so the agent can ask the user.

**Claude Code** (already registered for this repo in `.mcp.json`; approve it when Claude Code asks). Elsewhere:

```bash
claude mcp add --scope project agla -- uv run --directory /path/to/agla-station python -m agla.mcp_server
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "agla": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/agla-station", "python", "-m", "agla.mcp_server"]
    }
  }
}
```

Use the absolute path to `uv` (`which uv`) if Claude Desktop can't find it.

## Known limitations

- **DMRC fares near a slab boundary can be one slab off.** DMRC charges by track distance in slabs (2, 5, 12, 21, 32 km). We approximate track distance by summing straight-line distances between consecutive stations, which under-measures curvy lines. Trips that land within about 1.5 km of a boundary can get the neighbouring slab's fare. Known case from a manual spot-check: Kashmere Gate -> Noida City Centre, we compute 20.7 km (Rs 43) but DMRC charges Rs 54 (over 21 km). Against 384 official fares, 376 match. Planned fix: fit a per-line track-distance factor from official terminal-to-station fares. Details in `data/manual/README.md`.
