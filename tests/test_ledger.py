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


def test_timeline_merges_every_source_and_repairs_old_lines():
    import build_timeline

    events, unreadable = build_timeline.read_events()
    assert unreadable == 0  # the two lines from the old scrubbing bug are repaired on read
    items = build_timeline.event_items(events) + build_timeline.decision_items() + build_timeline.git_items()
    kinds = {i["kind"] for i in items}
    assert {"prompt", "tool", "checkpoint", "decision", "override", "surprise", "commit"} <= kinds
    override = next(i for i in items if i["kind"] == "override")
    assert {"Question", "Claude suggested", "Chose", "Why"} <= set(override["fields"])
    assert all("Session cost" not in i.get("fields", {}) for i in items)


def test_journal_notes_must_match_the_ledger(tmp_path):
    sys.path.insert(0, str(LEDGER.parent / ".claude" / "skills" / "build-journal" / "scripts"))
    import render_journal as rj

    timeline = {"stats": {"prompts": 124, "active_hours": 6.9},
                "items": [{"kind": "override", "title": "Safety check simplified", "ts": "2026-10-23T17:00:00+00:00"}]}
    notes = rj.load_notes(None, timeline["stats"])
    assert notes == {"intro": "", "moments": []}
    good = {"intro": "{prompts} prompts, {active_hours} h", "moments": [{"match": "safety check", "note": "Cut it."}]}
    bad = {"intro": "999 prompts", "moments": [{"match": "no such moment", "note": "x"}]}
    for case, n_problems in [(good, 0), (bad, 2)]:  # bad: an unknown moment and a number not in the data
        path = tmp_path / "notes.json"
        path.write_text(json.dumps(case))
        assert len(rj.check_notes(timeline, rj.load_notes(path, timeline["stats"]))) == n_problems
    html = rj.render({**timeline, "project": "X", "items": [{**timeline["items"][0], "title": "</script><b>"}]}, good)
    assert "</script><b>" not in html  # ledger text can't break out of the embedded data
