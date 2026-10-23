"""Resolver-only baseline: split each eval input with simple rules, then run resolve_station on each side.

Run: uv run python -m evals.resolver_baseline
Free (no API calls). Separates resolver mistakes from model mistakes in the LLM eval.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agla.tools import ToolError, resolve_station

CASES = Path(__file__).with_name("station_parsing.jsonl")
TAIL = re.compile(r",.*$|\b(jana hai|jaana hai|kaise jaun|tak|jaldi|kitna lagega|please)\b.*$", re.I)


def split(text: str) -> tuple[str, str]:
    t = text.replace("→", " to ")
    if m := re.search(r"^how .*?\bto (.+?) from (.+)$", t, re.I):  # "how do i get to X from Y"
        return m[2], m[1]
    t = re.sub(r"^(mujhe|i need to go|from)\s+", "", t, flags=re.I)
    t = re.sub(r"^from\s+", "", t, flags=re.I)
    t = re.sub(r"^.*?\bfrom\s+", "", t, flags=re.I)
    a, b = re.split(r"\s+(?:to|se)\s+", t, maxsplit=1)
    return a.strip(), TAIL.sub("", b).strip()


def main() -> None:
    ok = 0
    rows = [json.loads(line) for line in CASES.read_text().splitlines()]
    for r in rows:
        a, b = split(r["input"])
        exp = r["expected"]
        try:
            got = (resolve_station(a).station_id, resolve_station(b).station_id)
            verdict = "ask" not in exp and got == (exp["origin"], exp["destination"])
            detail = f"{got}"
        except ToolError as exc:
            verdict = bool(exp.get("ask")) and "ambiguous" in str(exc)
            detail = str(exc)[:110]
        ok += verdict
        if not verdict:
            print(f"FAIL {r['id']} [{r['category']}] {r['input']!r} -> split {a!r} | {b!r}\n     {detail}")
    print(f"\nresolver baseline: {ok}/{len(rows)}")


if __name__ == "__main__":
    main()
