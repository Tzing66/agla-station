#!/usr/bin/env python3
"""Status line: model name and session cost.

Also writes the latest cost to ledger/.session_cost.json so /checkpoint can
record it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

COST_FILE = Path(__file__).resolve().parent.parent / "ledger" / ".session_cost.json"


def main() -> None:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        data = {}
    model = (data.get("model") or {}).get("display_name") or "?"
    cost = (data.get("cost") or {}).get("total_cost_usd")
    try:
        COST_FILE.write_text(json.dumps({"session": data.get("session_id"), "cost_usd": cost}))
    except OSError:
        pass
    cost_text = f"${cost:.2f}" if isinstance(cost, (int, float)) else "$?"
    print(f"🚇 Agla Station · {model} · {cost_text}")


if __name__ == "__main__":
    main()
