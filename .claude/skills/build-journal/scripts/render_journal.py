#!/usr/bin/env python3
"""Render the build journal: ledger/timeline.json (+ optional notes) -> one self-contained HTML page.

    python3 .claude/skills/build-journal/scripts/render_journal.py \
        --timeline ledger/timeline.json --notes ledger/journal_notes.json --out docs/build-journal.html

The page is the template in ../assets/template.html with the timeline and notes embedded as JSON: no network
requests, no fonts or scripts to fetch, so it can be published or opened anywhere.

Notes can say {prompts}, {claude_actions}, {active_hours} or any other key of timeline["stats"]; the renderer fills
them in, so figures that grow as the ledger grows stay current. Notes are then checked: every note must point at a
real moment in the timeline, and every number typed into a note must appear somewhere in the timeline data (the same
"numbers come from data" rule the bot follows). A note that fails stops the render, so a wrong figure never reaches
the published page. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "template.html"
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def load_notes(path: Path | None, stats: dict) -> dict:
    if path is None or not path.exists():
        return {"intro": "", "moments": []}
    notes = json.loads(path.read_text(encoding="utf-8"))
    fill = _Stats(stats).__getitem__
    sub = lambda text: PLACEHOLDER.sub(lambda m: fill(m.group(1)), text)  # noqa: E731
    return {"intro": sub(notes.get("intro", "")),
            "moments": [{**m, "note": sub(m.get("note", ""))} for m in notes.get("moments", [])]}


PLACEHOLDER = re.compile(r"\{(\w+)\}")


class _Stats(dict):
    """Placeholder values: numbers formatted the way the page shows them; unknown names fail loudly."""

    def __getitem__(self, key: str) -> str:
        if key not in self:
            raise SystemExit(f"Unknown placeholder {{{key}}}; use one of: {', '.join(sorted(self))}")
        value = dict.__getitem__(self, key)
        return f"{value:,}" if isinstance(value, int) else str(value)


def check_notes(timeline: dict, notes: dict) -> list[str]:
    """Problems with the notes: moments that match no item, and numbers the timeline doesn't contain."""
    problems = []
    corpus = json.dumps(timeline, ensure_ascii=False)
    known = set(NUMBER.findall(corpus)) | {str(v) for v in _numbers(timeline["stats"])} \
        | {f"{v:,}" for v in _numbers(timeline["stats"]) if isinstance(v, int)}
    texts = [("intro", notes["intro"])]
    for i, m in enumerate(notes["moments"]):
        hits = [it for it in timeline["items"] if m.get("match", "").lower() in it.get("title", "").lower()
                and (not m.get("kind") or it["kind"] == m["kind"])]
        if not m.get("match") or not hits:
            problems.append(f"moment {i + 1}: no timeline item matches {m.get('match')!r}")
        texts.append((f"moment {i + 1}", m.get("note", "")))
    for where, text in texts:
        for n in NUMBER.findall(text):
            if n not in known and n.replace(",", "") not in known:
                problems.append(f"{where}: the number {n} isn't in the timeline data")
    return problems


def _numbers(value: object):
    if isinstance(value, dict):
        for v in value.values():
            yield from _numbers(v)
    elif isinstance(value, int | float) and not isinstance(value, bool):
        yield value


def render(timeline: dict, notes: dict) -> str:
    def embed(obj: object) -> str:  # safe inside <script>: no "</script>" or "<!--" can close it early
        return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")

    html = TEMPLATE.read_text(encoding="utf-8")
    return (html.replace("__TITLE__", f"How {timeline.get('project', 'this project')} was built")
                .replace("/*__DATA__*/null", embed(timeline))
                .replace("/*__NOTES__*/null", embed(notes)))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--timeline", type=Path, default=Path("ledger/timeline.json"))
    p.add_argument("--notes", type=Path, default=Path("ledger/journal_notes.json"))
    p.add_argument("--out", type=Path, default=Path("docs/build-journal.html"))
    args = p.parse_args()

    timeline = json.loads(args.timeline.read_text(encoding="utf-8"))
    notes = load_notes(args.notes, timeline["stats"])
    if problems := check_notes(timeline, notes):
        print("Not rendered; fix the notes first:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(timeline, notes), encoding="utf-8")
    s = timeline["stats"]
    print(f"{args.out}: {len(timeline['items'])} items, {len(notes['moments'])} annotated moments, "
          f"{args.out.stat().st_size // 1024} KB; {s['prompts']} prompts, {s['claude_actions']} Claude actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
