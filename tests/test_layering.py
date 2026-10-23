"""Front ends (bot, web, MCP server) may only import the tool layer and config. See docs/architecture.md."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "agla"
FRONT_ENDS = [ROOT / "mcp_server.py", *ROOT.glob("bot/**/*.py"), *ROOT.glob("web/**/*.py")]
ALLOWED = ("agla.tools", "agla.config", "agla.llm", "agla.bot")  # llm sits beside the bot (architecture §1)


def agla_imports(path: Path) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("agla"):
            found += [f"{node.module}.{a.name}" if node.module == "agla" else node.module for a in node.names]
        elif isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.startswith("agla")]
    return found


def test_front_ends_only_import_tool_layer():
    offenders = {
        str(p.relative_to(ROOT.parent)): bad
        for p in FRONT_ENDS
        if p.exists() and (bad := [m for m in agla_imports(p) if not m.startswith(ALLOWED)])
    }
    assert offenders == {}


def test_domain_modules_import_in_any_order():
    import subprocess
    import sys

    for first in ("agla.miles", "agla.badges", "agla.tools", "agla.mcp_server", "agla.bot.app"):
        code = f"import {first}; from agla import tools; assert tools.get_miles and tools.get_badges"
        proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT.parent, capture_output=True, text=True)
        assert proc.returncode == 0, f"importing {first} first: {proc.stderr[-300:]}"
