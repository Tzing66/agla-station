#!/usr/bin/env python3
"""Merge the process ledger into one timeline: ledger/timeline.json, the input for the build-journal skill.

    python3 ledger/build_timeline.py

Sources, all in this folder or the repo:
- events.jsonl: every prompt and tool call, written by the hooks (already scrubbed of secrets).
- decisions.md: /decision, /surprise and /checkpoint entries.
- git log: every commit.
- chats/*.md: conversations from before the hooks existed (the kickoff), placed first as "ideation".

Output lanes: "human" (prompts), "claude" (tool calls, subagents), "decision" (decisions, overrides, surprises) and
"milestone" (checkpoints, commits, sessions, compactions). Not recorded: rewinds (hooks can't see them) and cost
(dropped on 2026-10-24). Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

# The project being documented, like hook.py: when this runs from the agla-dev plugin, the script lives in Claude
# Code's plugin cache but the ledger belongs to the project ($CLAUDE_PROJECT_DIR).
ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[1])
LEDGER = ROOT / "ledger"
OUT = LEDGER / "timeline.json"
IST = timezone(timedelta(hours=5, minutes=30))
ACTIVE_GAP = timedelta(minutes=30)  # a longer silence ends a working stretch
DETAIL_LEN = 240

# tool name -> what the journal calls it
TOOL_GROUPS = [
    ("Shell", ("Bash", "TaskStop", "Monitor")),
    ("Edit files", ("Write", "Edit", "NotebookEdit")),
    ("Read files", ("Read", "Grep", "Glob")),
    ("Browser", ("mcp__playwright__",)),
    ("agla-mcp", ("mcp__agla__",)),
    ("Ask the human", ("AskUserQuestion",)),
    ("Subagents", ("Agent", "Task", "SubagentHandback")),
    ("Web", ("WebFetch", "WebSearch")),
    ("Skills", ("Skill",)),
    ("Plan mode", ("EnterPlanMode", "ExitPlanMode")),
]


def tool_group(tool: str) -> str:
    for group, prefixes in TOOL_GROUPS:
        if any(tool == p or (p.endswith("_") and tool.startswith(p)) for p in prefixes):
            return group
    return "Other"


def clip(text: str | None, n: int = DETAIL_LEN) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def read_events() -> tuple[list[dict], int]:
    """Hook events. Two early lines were written with a stray backslash before [REDACTED] (a scrubbing bug since
    fixed in hook.py); they are repaired here rather than rewritten in the ledger."""
    events, unreadable = [], 0
    for line in (LEDGER / "events.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            try:
                events.append(json.loads(line.replace("\\[REDACTED]", "[REDACTED]")))
            except json.JSONDecodeError:
                unreadable += 1
    return events, unreadable


def event_items(events: list[dict]) -> list[dict]:
    items = []
    for e in events:
        ts, kind = e["ts"], e["event"]
        if kind == "UserPromptSubmit":
            items.append({"ts": ts, "lane": "human", "kind": "prompt", "title": clip(e.get("summary"), 120),
                          "detail": clip(e.get("summary"))})
        elif kind == "PreToolUse":
            tool = e.get("tool") or "?"
            items.append({"ts": ts, "lane": "claude", "kind": "tool", "tool": tool, "group": tool_group(tool),
                          "title": clip(e.get("summary") or e.get("target"), 120),
                          "detail": clip(e.get("target") or e.get("summary"))})
        elif kind == "SubagentStop":
            items.append({"ts": ts, "lane": "claude", "kind": "subagent", "title": "Subagent finished",
                          "detail": clip(e.get("summary"))})
        elif kind == "SessionStart":
            items.append({"ts": ts, "lane": "milestone", "kind": "session", "title": "Session started",
                          "detail": clip(e.get("summary"))})
        elif kind == "PreCompact":
            items.append({"ts": ts, "lane": "milestone", "kind": "compaction", "title": "Context compacted",
                          "detail": clip(e.get("summary"))})
    return items


HEADING = re.compile(r"^## \[(DECISION|OVERRIDE|SURPRISE|CHECKPOINT)\] (\d{4}-\d\d-\d\d \d\d:\d\d) IST — (.+)$")
FIELD = re.compile(r"^- \*\*(.+?):\*\* (.*)$")


def decision_items() -> list[dict]:
    items, current = [], None
    for line in (LEDGER / "decisions.md").read_text(encoding="utf-8").splitlines():
        if m := HEADING.match(line):
            tag, when, title = m.groups()
            ts = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=IST).astimezone(UTC).isoformat()
            lane = "milestone" if tag == "CHECKPOINT" else "decision"
            current = {"ts": ts, "lane": lane, "kind": tag.lower(), "title": title.strip(), "fields": {}}
            items.append(current)
        elif current and (m := FIELD.match(line)):
            if m.group(1) != "Session cost":  # cost tracking was dropped; the field only ever said n/a
                current["fields"][m.group(1)] = m.group(2).strip()
    return items


def git_items() -> list[dict]:
    out = subprocess.run(["git", "-C", str(ROOT), "log", "--reverse", "--format=%h%x1f%aI%x1f%s"],
                         capture_output=True, text=True, check=True).stdout
    items = []
    for line in out.splitlines():
        sha, when, subject = line.split("\x1f")
        items.append({"ts": datetime.fromisoformat(when).astimezone(UTC).isoformat(), "lane": "milestone",
                      "kind": "commit", "title": subject, "sha": sha})
    return items


def chat_items(first_ts: str) -> list[dict]:
    """Pre-hook conversations, placed just before the first recorded event."""
    items = []
    for i, path in enumerate(sorted((LEDGER / "chats").glob("*.md"))):
        text = path.read_text(encoding="utf-8")
        title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), path.stem)
        ts = (datetime.fromisoformat(first_ts) - timedelta(minutes=5 - i)).isoformat()
        items.append({"ts": ts, "lane": "human", "kind": "ideation", "title": title,
                      "file": f"ledger/chats/{path.name}", "detail": clip(re.sub(r"(?s)^---.*?---", "", text), 400)})
    return items


def active_hours(times: list[datetime]) -> float:
    total = timedelta()
    for a, b in zip(times, times[1:], strict=False):
        if b - a <= ACTIVE_GAP:
            total += b - a
    return round(total.total_seconds() / 3600, 1)


def stats(items: list[dict], events: list[dict], unreadable: int) -> dict:
    times = sorted(datetime.fromisoformat(i["ts"]) for i in items if i["kind"] in ("prompt", "tool", "subagent"))
    prompts = [i for i in items if i["kind"] == "prompt"]
    tools = [i for i in items if i["kind"] == "tool"]
    tags = Counter(i["kind"] for i in items if i["lane"] in ("decision", "milestone"))
    return {
        "start": times[0].isoformat(), "end": times[-1].isoformat(),
        "elapsed_hours": round((times[-1] - times[0]).total_seconds() / 3600, 1),
        "active_hours": active_hours(times),
        "prompts": len(prompts),
        "one_word_replies": sum(1 for p in prompts if len(p["detail"].split()) <= 2),  # "yes", "yep, go ahead"
        "claude_actions": len(tools),
        "actions_by_group": dict(Counter(i["group"] for i in tools).most_common()),
        "actions_by_tool": dict(Counter(i["tool"] for i in tools).most_common()),
        "turns": sum(1 for e in events if e["event"] == "Stop"),
        "subagent_runs": sum(1 for e in events if e["event"] == "SubagentStop"),
        "decisions": tags["decision"], "overrides": tags["override"], "surprises": tags["surprise"],
        "checkpoints": tags["checkpoint"], "commits": tags["commit"],
        "sessions": len({e["session"] for e in events if e.get("session")}),
        "compactions": tags["compaction"],
        "rewinds": None,  # hooks don't see rewinds
        "cost_usd": None,  # not tracked: dropped on 2026-10-24 as unnecessary for this project
        "unreadable_events": unreadable,
    }


def phases(items: list[dict]) -> list[dict]:
    """Phase boundaries from checkpoint titles ("Phase 2: ...", "Phases 8-9: ..."); other checkpoints are steps."""
    out = []
    for i in items:
        if i["kind"] == "checkpoint":
            m = re.match(r"Phases? ([\d+\-– ]+(?:\+ \d+)?)", i["title"])
            out.append({"ts": i["ts"], "label": f"Phase {m.group(1).strip()}" if m else None, "title": i["title"]})
    return out


def _repo_url() -> str:
    url = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"], capture_output=True, text=True).stdout
    url = url.strip().removesuffix(".git")
    return re.sub(r"^git@([^:]+):", r"https://\1/", url)


def main() -> int:
    events, unreadable = read_events()
    items = event_items(events) + decision_items() + git_items()
    first = min(i["ts"] for i in items)
    items += chat_items(first)
    items.sort(key=lambda i: (i["ts"], i["lane"]))
    timeline = {
        "project": "Agla Station" if ROOT.name == "agla-station" else ROOT.name,
        "repo": _repo_url(),
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "timezone_note": "timestamps are UTC; IST is UTC+05:30",
        "stats": stats(items, events, unreadable),
        "phases": phases(items),
        "items": items,
    }
    OUT.write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    s = timeline["stats"]
    print(f"{OUT.relative_to(ROOT)}: {len(items)} items, {s['prompts']} prompts, {s['claude_actions']} Claude actions, "
          f"{s['decisions']} decisions, {s['overrides']} overrides, {s['surprises']} surprises, "
          f"{s['checkpoints']} checkpoints, {s['commits']} commits; {s['active_hours']} active hours over "
          f"{s['elapsed_hours']} h" + (f"; {unreadable} unreadable events" if unreadable else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
