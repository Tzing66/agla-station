"""The process ledger: hook output stays valid JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ledger"
sys.path.insert(0, str(LEDGER))

import hook  # noqa: E402


def test_scrubbing_never_breaks_the_json_line():
    """Regression: the email pattern used to run over JSON text and eat the `n` of an encoded newline."""
    event = hook.build_event({"hook_event_name": "PreToolUse", "tool_name": "Write",
                              "tool_input": {"other": "x\n@pytest.mark.parametrize(\n"}})
    line = json.dumps(event)
    assert json.loads(line)["summary"]  # parses
    assert "[REDACTED]" in hook.clip({"a": "mail me at someone@example.com"}, 300)
