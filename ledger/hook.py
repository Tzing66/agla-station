#!/usr/bin/env python3
"""Process ledger hook: one script for every Claude Code hook event.

Reads the hook JSON from stdin and appends one scrubbed line to
ledger/events.jsonl. Must never crash or block the session: every error is
swallowed and the script always exits 0.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

LEDGER_DIR = Path(__file__).resolve().parent
EVENTS_FILE = LEDGER_DIR / "events.jsonl"
ENV_FILE = LEDGER_DIR.parent / ".env"

SUMMARY_LEN = 200
TARGET_LEN = 300

ACTORS = {
    "UserPromptSubmit": "human",
    "PreToolUse": "claude",
    "PostToolUse": "claude",
    "Stop": "claude",
    "SubagentStop": "claude",
    "PreCompact": "system",
    "SessionStart": "system",
}

SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),                    # Anthropic keys
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{30,}"),            # Telegram bot tokens
    re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}"),  # GitHub tokens
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),                      # long hex
    # long base64-ish blobs: mixed case + digits, so paths and words survive
    re.compile(r"(?=[\w+\-]*\d)(?=[\w+\-]*[A-Z])(?=[\w+\-]*[a-z])\b[\w+\-]{40,}={0,2}"),
    re.compile(r"\b[\w.+\-]+@[\w\-]+\.[\w.\-]+\b"),  # email addresses
    # UPI VPAs on common handles (the repo is public)
    re.compile(
        r"\b[\w.\-]+@(?:upi|ybl|ibl|axl|paytm|ptyes|ptaxis|pthdfc|ptsbi|apl|"
        r"okaxis|oksbi|okhdfcbank|okicici|kotak|icici|hdfcbank|sbi|axisbank)\b",
        re.IGNORECASE,
    ),
]


def env_secrets() -> list[str]:
    """Values from .env long enough to be worth redacting verbatim."""
    values: list[str] = []
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            value = line.split("=", 1)[1].strip().strip("'\"")
            if len(value) >= 6:
                values.append(value)
    except OSError:
        pass
    return values


def scrub(text: str) -> str:
    for value in env_secrets():
        text = text.replace(value, "[REDACTED]")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def clip(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return scrub(text)[:limit]


def tool_target(tool_input: dict) -> object:
    for key in ("file_path", "notebook_path", "command", "url", "pattern", "path", "query"):
        if tool_input.get(key):
            return tool_input[key]
    return None


def tool_summary(tool_input: dict) -> object:
    for key in ("description", "prompt", "command", "old_string", "content"):
        if tool_input.get(key):
            return tool_input[key]
    return tool_input or None


def build_event(payload: dict) -> dict:
    event = payload.get("hook_event_name", "unknown")
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {"value": tool_input}

    target: object = None
    summary: object = None
    if event == "UserPromptSubmit":
        summary = payload.get("prompt")
    elif event in ("PreToolUse", "PostToolUse"):
        target = tool_target(tool_input)
        summary = tool_summary(tool_input)
    elif event == "SessionStart":
        summary = f"source={payload.get('source')}"
    elif event == "PreCompact":
        summary = f"trigger={payload.get('trigger')}"
    elif event in ("Stop", "SubagentStop"):
        summary = payload.get("last_assistant_message") or "turn ended"

    return {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "session": payload.get("session_id"),
        "event": event,
        "actor": ACTORS.get(event, "system"),
        "tool": tool,
        "target": clip(target, TARGET_LEN),
        "summary": clip(summary, SUMMARY_LEN),
    }


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        line = json.dumps(build_event(payload), ensure_ascii=False)
        with EVENTS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001 - the ledger must never break a session
        pass


if __name__ == "__main__":
    try:
        main()
    finally:
        os._exit(0)
