#!/usr/bin/env python3
"""Status line (terminal only; the VS Code extension doesn't run status lines): project, model and session cost."""

from __future__ import annotations

import json
import sys


def main() -> None:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        data = {}
    model = (data.get("model") or {}).get("display_name") or "?"
    cost = (data.get("cost") or {}).get("total_cost_usd")
    cost_text = f"${cost:.2f}" if isinstance(cost, (int, float)) else "$?"
    print(f"🚇 Agla Station · {model} · {cost_text}")


if __name__ == "__main__":
    main()
