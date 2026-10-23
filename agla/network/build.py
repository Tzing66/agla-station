"""Build data/network.json from the official snapshots and the manual CSVs.

Run: python -m agla.network.build

Inputs (see data/manual/README.md for provenance):
- data/raw/dmrc_api/snapshot.json      DMRC + Rapid Metro stations, lines, coordinates
- data/raw/dmrc_api/segments_*.json    DMRC journey-planner time between adjacent stations
- data/manual/*.csv                    Aqua Line, topology fixes, walks, states, names, aliases
"""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from agla.network.geo import haversine_km

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
MANUAL = ROOT / "data" / "manual"
OUT = ROOT / "data" / "network.json"

DMRC_API = "https://backend.delhimetrorail.com/api/v2/en/"
NMRC_PLANNER = "https://www.nmrcnoida.com/Passenger-Information/Journey-Planner-and-Fares"

# DMRC line_code -> (line_id, display name, operator, fare_operator, family)
LINES = {
    "LN1": ("DMRC_RED", "Red Line", "DMRC", "DMRC", "RED"),
    "LN2": ("DMRC_YELLOW", "Yellow Line", "DMRC", "DMRC", "YELLOW"),
    "LN3": ("DMRC_BLUE", "Blue Line", "DMRC", "DMRC", "BLUE"),
    "LN4": ("DMRC_BLUE_BRANCH", "Blue Line (Vaishali branch)", "DMRC", "DMRC", "BLUE"),
    "LN5": ("DMRC_GREEN", "Green Line", "DMRC", "DMRC", "GREEN"),
    "LN6": ("DMRC_VIOLET", "Violet Line", "DMRC", "DMRC", "VIOLET"),
    "LN7": ("DMRC_PINK", "Pink Line", "DMRC", "DMRC", "PINK"),
    "LN7EXTN": ("DMRC_PINK_EXT", "Pink Line (extension)", "DMRC", "DMRC", "PINK"),
    "LN8": ("DMRC_MAGENTA", "Magenta Line", "DMRC", "DMRC", "MAGENTA"),
    "LN8EXTN": ("DMRC_MAGENTA_EXT", "Magenta Line (extension)", "DMRC", "DMRC", "MAGENTA"),
    "LN9": ("DMRC_GREY", "Grey Line", "DMRC", "DMRC", "GREY"),
    "LN10": ("DMRC_AIRPORT", "Airport Express", "DMRC", "DMRC_AIRPORT", "AIRPORT"),
    "LN11": ("RAPID", "Rapid Metro Gurugram", "Rapid Metro", "RAPID", "RAPID"),
}
AQUA = ("NMRC_AQUA", "Aqua Line", "NMRC", "NMRC", "AQUA", "#00b4d8")
WALK_LINE = "LN12"  # DMRC models the Dhaula Kuan footbridge as a "line"; we treat it as a walk

# Adjacent-station times outside this band are treated as placeholders and re-estimated.
MIN_MINUTES = 0.5
MAX_KMH = 90.0
EST_KMH = 34.0

KEEP_UPPER = {
    "AIIMS", "IIT", "ITO", "INA", "ISBT", "IGI", "NSIC", "ESI", "JLN", "NHPC", "MIA", "NSEZ", "GNIDA", "IFFCO",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    lines = [ln for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    return list(csv.DictReader(lines))


def load_json(path: Path) -> object:
    data = json.loads(path.read_text())
    return json.loads(data) if isinstance(data, str) else data  # Playwright saves a JSON string


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def clean_name(raw: str) -> tuple[str, list[str]]:
    """Title-case a DMRC API name; return (display name, aliases from '(earlier X)')."""
    aliases = [m.strip() for m in re.findall(r"\(earlier ([^)]+)\)", raw, flags=re.I)]
    name = re.sub(r"\(earlier [^)]+\)+", "", raw, flags=re.I)
    name = re.sub(r"(SECTOR|PHASE)\s*-\s*(\d)", r"\1 \2", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" -")
    name = re.sub(r"[A-Za-z]+", lambda m: m[0] if m[0].upper() in KEEP_UPPER else m[0].capitalize(), name)
    return name, [a.title() for a in aliases]


def seconds(hms: str) -> float:
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s


def fare_km(code_line: str, km: float, official_fare: int | None) -> float:
    """Distance used for DMRC slab fares.

    Straight-line km between neighbours is a little off DMRC's track km. Where the official fare for the
    adjacent pair shows the pair sits on the other side of the 2 km slab boundary, nudge it across.
    """
    if LINES[code_line][3] != "DMRC" or official_fare is None:
        return km
    if official_fare == 11 and km > 2:
        return 2.0
    if official_fare >= 21 and km <= 2:
        return 2.01
    return km


def build() -> dict:
    snap = load_json(RAW / "dmrc_api" / "snapshot.json")
    names = {r["code"]: r["name"] for r in read_csv(MANUAL / "names.csv")}
    states = {r["code"]: r["state"] for r in read_csv(MANUAL / "states.csv")}
    coords = {r["code"]: (float(r["lat"]), float(r["lon"])) for r in read_csv(MANUAL / "coords.csv")}

    colours = {ln["line_code"]: ln["primary_color_code"] for ln in snap["lines"]}
    lines = {
        lid: {"name": nm, "operator": op, "fare_operator": fop, "family": fam, "colour": colours.get(code)}
        for code, (lid, nm, op, fop, fam) in LINES.items()
    }
    lid, nm, op, fop, fam, colour = AQUA
    lines[lid] = {"name": nm, "operator": op, "fare_operator": fop, "family": fam, "colour": colour}

    stations: dict[str, dict] = {}
    code_to_id: dict[str, str] = {}
    for s in snap["stations"]:
        on_lines = [LINES[c][0] for c in s["lines"] if c in LINES]
        if not on_lines and WALK_LINE not in s["lines"]:
            continue  # depots and closed entries
        display, earlier = clean_name(s["name"])
        display = names.get(s["code"], display)
        sid = slug(display)
        code_to_id[s["code"]] = sid
        lat, lon = coords.get(s["code"], (float(s["lat"]), float(s["lon"])))
        stations[sid] = {
            "name": display,
            "code": s["code"],
            "lat": lat,
            "lon": lon,
            "state": states.get(s["code"], "Delhi"),
            "lines": on_lines,
            "aliases": earlier,
            "source": "dmrc_api" + (" + manual coords" if s["code"] in coords else ""),
        }

    aqua = read_csv(MANUAL / "aqua_line.csv")
    for r in aqua:
        sid = slug(r["name"])
        code_to_id[r["code"]] = sid
        stations[sid] = {
            "name": r["name"],
            "code": r["code"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "state": "UP",
            "lines": [AQUA[0]],
            "aliases": [],
            "source": "manual",
        }

    for r in read_csv(MANUAL / "aliases.csv"):
        stations[code_to_id[r["code"]]]["aliases"].append(r["alias"])

    # adjacent-station times from the DMRC journey planner
    seg_time: dict[tuple[str, str], float] = {}
    seg_fare: dict[tuple[str, str], int] = {}
    for f in sorted((RAW / "dmrc_api").glob("segments_*.json")):
        for row in load_json(f):
            if row.get("total_time"):
                seg_time[(row["from"], row["to"])] = seconds(row["total_time"]) / 60
            if row.get("fare"):
                seg_fare[(row["from"], row["to"])] = row["fare"]

    links = read_csv(MANUAL / "links.csv")
    removed = {(r["from"], r["to"]) for r in links if r["action"] == "remove_edge"}
    removed |= {(b, a) for a, b in removed}

    edges: list[dict] = []
    flagged: list[str] = []

    def add_edge(code_line: str, a: str, b: str, minutes: float | None, directed: bool, source: str) -> None:
        sa, sb = stations[code_to_id[a]], stations[code_to_id[b]]
        km = round(haversine_km(sa["lat"], sa["lon"], sb["lat"], sb["lon"]), 3)
        flag = None
        if minutes is None or minutes < MIN_MINUTES or km / (minutes / 60) > MAX_KMH:
            flag = f"estimated (planner gave {minutes!r} min)"
            minutes = max(1.5, km / EST_KMH * 60)
            flagged.append(f"{a}-{b}: {flag}")
        edges.append({
            "line": LINES[code_line][0],
            "from": code_to_id[a],
            "to": code_to_id[b],
            "minutes": round(minutes, 2),
            "km": km,
            "fare_km": fare_km(code_line, km, seg_fare.get((a, b))),
            "directed": directed,
            "source": source,
            **({"flag": flag} if flag else {}),
        })

    for code, members in snap["station_by_line"].items():
        if code not in LINES:
            continue
        codes = [m["code"] for m in members if m["code"] in code_to_id]
        for a, b in zip(codes, codes[1:], strict=False):
            if (a, b) in removed:
                continue
            add_edge(code, a, b, seg_time.get((a, b)), False, "dmrc_api")

    for r in links:
        if r["action"] == "add_edge":
            add_edge(r["line"], r["from"], r["to"], float(r["minutes"]), r["directed"] == "1", "manual")

    for a, b in zip(aqua, aqua[1:], strict=False):
        km = float(b["cum_km"]) - float(a["cum_km"])
        if km <= 0:  # NMRC publishes NSEZ and Sector 83 at the same distance
            km = haversine_km(float(a["lat"]), float(a["lon"]), float(b["lat"]), float(b["lon"]))
        edges.append({
            "line": AQUA[0],
            "from": code_to_id[a["code"]],
            "to": code_to_id[b["code"]],
            "minutes": float(b["cum_minutes"]) - float(a["cum_minutes"]),
            "km": round(km, 3),
            "directed": False,
            "source": "manual (nmrc planner)",
        })

    walks = [
        {"from": code_to_id[r["from"]], "to": code_to_id[r["to"]], "minutes": float(r["minutes"]), "note": r["note"]}
        for r in links
        if r["action"] == "walk"
    ]

    return {
        "meta": {
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "sources": {
                "dmrc_api": f"{DMRC_API} (stations, station_by_line, station_route), fetched 2026-10-23",
                "nmrc_planner": f"{NMRC_PLANNER}, fetched 2026-10-23",
                "osm": "OpenStreetMap via overpass-api.de (Aqua Line coordinates), fetched 2026-10-23",
                "manual": "data/manual/*.csv",
            },
            "flagged_edges": flagged,
        },
        "lines": lines,
        "stations": dict(sorted(stations.items())),
        "edges": edges,
        "walks": walks,
    }


def write_od_fares(net: dict) -> None:
    """Official per-pair fares for Airport Express and Rapid Metro -> data/fares/*.csv."""
    code_to_id = {s["code"]: sid for sid, s in net["stations"].items()}
    tables = load_json(RAW / "dmrc_api" / "od_fares_airport_rapid.json")["tables"]
    out_dir = ROOT / "data" / "fares"
    out_dir.mkdir(exist_ok=True)
    for code, filename in (("LN10", "airport_od.csv"), ("LN11", "rapid_od.csv")):
        fares: dict[tuple[str, str], dict[str, int]] = {}
        for r in tables[code]:
            if r["fare"]:  # the planner returns 0 where it has no fare; leave those out
                fares.setdefault((r["from"], r["to"]), {})[r["day"]] = r["fare"]
        with (out_dir / filename).open("w", newline="") as fh:
            fh.write(f"# Official DMRC journey planner fares for {code}, fetched 2026-10-23.\n"
                     "# Generated by agla.network.build.\n")
            w = csv.writer(fh)
            w.writerow(["from_id", "to_id", "weekday", "sunday_holiday"])
            for (a, b), f in sorted(fares.items()):
                if "weekday" in f and "sunday" in f:
                    w.writerow([code_to_id[a], code_to_id[b], f["weekday"], f["sunday"]])


def main() -> None:
    net = build()
    OUT.write_text(json.dumps(net, indent=1, ensure_ascii=False) + "\n")
    write_od_fares(net)
    print(
        f"wrote {OUT.relative_to(ROOT)}: {len(net['stations'])} stations, {len(net['lines'])} lines, "
        f"{len(net['edges'])} edges, {len(net['walks'])} walks"
    )
    for f in net["meta"]["flagged_edges"]:
        print("  flagged:", f)


if __name__ == "__main__":
    main()
