"""Station-parsing eval: Sonnet 5.5 vs Haiku 5.5 on evals/station_parsing.jsonl.

    uv run python -m evals.run_eval --dry-run          # show what would run, no API calls
    uv run python -m evals.run_eval --live 10          # batch accuracy + 10 live turns per model for latency

Accuracy: each case sends exactly the bot's first request (agla.llm.request_params) through the Message Batches
API, then scores the system the rider actually gets: the model's quote_trip arguments go through resolve_station.
- normal case: pass if both stations resolve to the expected ids (preference scored separately)
- ambiguous case: pass if the system asks: the model asks without quoting, or the resolver flags the ambiguous side
Latency/cost: a small live sample runs the real Agent end to end (all tool rounds) at standard prices.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic

from agla import tools
from agla.config import IST, settings
from agla.db import connect
from agla.llm import Agent, first_messages, request_params

HERE = Path(__file__).parent
CASES = HERE / "station_parsing.jsonl"
RESULTS_MD = HERE / "results.md"
RESULTS_JSON = HERE / "results.json"
NOW = datetime(2026, 10, 26, 10, 0, tzinfo=IST)  # fixed Monday morning: same request bytes every run

MODELS = {"sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
# USD per million tokens (claude-api skill pricing table, cached 2026-10-06). Haiku 5.5 cache rates aren't listed
# there; assumed at the standard multipliers (read 0.1x, 5-minute write 1.25x of input).
PRICES = {
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125},
}
BATCH_DISCOUNT = 0.5


@dataclass
class CaseResult:
    case_id: str
    category: str
    input: str
    passed: bool
    preference_ok: bool | None  # None when the case doesn't specify a preference
    outcome: str  # what the system did, for the report
    tool_input: dict | None = None


@dataclass
class ModelReport:
    model: str
    results: list[CaseResult] = field(default_factory=list)
    batch_usage: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    live_seconds: list[float] = field(default_factory=list)
    live_usage: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    live_messages: int = 0


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]


def eval_user() -> tools.User:
    return tools.User(user_id=0, telegram_id=0, first_name="Rider", language="en")


def score(case: dict, content: list[Any]) -> CaseResult:
    """Score the model's first response the way the bot would act on it."""
    exp = case["expected"]
    call = next((b for b in content if b.type == "tool_use" and b.name == "quote_trip"), None)
    text = " ".join(b.text for b in content if b.type == "text").strip()
    base = {"case_id": case["id"], "category": case["category"], "input": case["input"]}

    if call is None:
        asked = exp.get("ask", False)
        return CaseResult(**base, passed=asked, preference_ok=None,
                          outcome=f"no quote_trip; replied: {text[:90]!r}")

    args = dict(call.input)
    got: dict[str, str] = {}
    errors: dict[str, str] = {}
    for side in ("origin", "destination"):
        try:
            got[side] = tools.resolve_station(args[side]).station_id
        except tools.ToolError as exc:
            errors[side] = "ambiguous" if "ambiguous" in str(exc) else "no match"

    if exp.get("ask"):
        passed = errors.get(exp["ambiguous_side"]) == "ambiguous"
        outcome = f"resolver: {errors or got}"
        return CaseResult(**base, passed=passed, preference_ok=None, outcome=outcome, tool_input=args)

    passed = not errors and got == {"origin": exp["origin"], "destination": exp["destination"]}
    want_pref = exp.get("preference", "fastest")
    pref_ok = args.get("preference") == want_pref if "preference" in exp else None
    outcome = "ok" if passed else f"got {got} errors {errors}"
    if pref_ok is False:
        outcome += f"; preference {args.get('preference')} != {want_pref}"
    return CaseResult(**base, passed=passed, preference_ok=pref_ok, outcome=outcome, tool_input=args)


def add_usage(acc: dict[str, int], usage: Any) -> None:
    acc["input"] += usage.input_tokens or 0
    acc["output"] += usage.output_tokens or 0
    acc["cache_read"] += usage.cache_read_input_tokens or 0
    acc["cache_write"] += usage.cache_creation_input_tokens or 0


def cost(model: str, usage: dict[str, int]) -> float:
    p = PRICES[model]
    return sum(usage.get(k, 0) * p[k] for k in p) / 1_000_000


# --- batch accuracy ---------------------------------------------------------------------------------------------


def run_batch(client: anthropic.Anthropic, cases: list[dict], reports: dict[str, ModelReport]) -> str:
    user = eval_user()
    requests = [
        {"custom_id": f"{key}__{c['id']}", "params": request_params(model, first_messages(user, [], c["input"], NOW))}
        for key, model in MODELS.items()
        for c in cases
    ]
    batch = client.messages.batches.create(requests=requests)
    print(f"batch {batch.id}: {len(requests)} requests submitted")
    while (b := client.messages.batches.retrieve(batch.id)).processing_status != "ended":
        print(f"  {b.processing_status}: {b.request_counts}")
        time.sleep(15)
    by_id = {c["id"]: c for c in cases}
    for item in client.messages.batches.results(batch.id):
        key, case_id = item.custom_id.split("__")
        report = reports[key]
        if item.result.type != "succeeded":
            report.results.append(CaseResult(case_id, by_id[case_id]["category"], by_id[case_id]["input"],
                                             False, None, f"batch {item.result.type}"))
            continue
        msg = item.result.message
        add_usage(report.batch_usage, msg.usage)
        report.results.append(score(by_id[case_id], msg.content))
    return batch.id


# --- live latency sample ----------------------------------------------------------------------------------------


class UsageRecorder:
    """Wraps AsyncAnthropic so the Agent's calls are counted."""

    def __init__(self, client: anthropic.AsyncAnthropic, usage: dict[str, int]) -> None:
        self._client, self._usage = client, usage
        self.beta = type("B", (), {"messages": type("M", (), {"create": self._create})()})()

    async def _create(self, **kwargs: Any) -> Any:
        resp = await self._client.beta.messages.create(**kwargs)
        add_usage(self._usage, resp.usage)
        return resp


async def run_live(n: int, cases: list[dict], reports: dict[str, ModelReport]) -> None:
    sample = [c for c in cases if c["category"] != "ambiguous"][:n]
    aclient = anthropic.AsyncAnthropic(api_key=settings().anthropic_api_key)
    for key, model in MODELS.items():
        report = reports[key]
        conn = connect(":memory:")
        user = tools.get_or_create_user(conn, 1, "Rider", NOW)
        agent = Agent(UsageRecorder(aclient, report.live_usage), conn, model)  # type: ignore[arg-type]
        for c in sample:
            t0 = time.perf_counter()
            await agent.respond(user, [], c["input"], NOW)
            report.live_seconds.append(time.perf_counter() - t0)
            report.live_messages += 1
        print(f"live {key}: median {statistics.median(report.live_seconds):.2f}s over {report.live_messages}")


# --- report -----------------------------------------------------------------------------------------------------


def write_report(reports: dict[str, ModelReport], batch_id: str | None, n_cases: int) -> None:
    lines = [
        "# Station-parsing eval",
        "",
        f"Run {datetime.now(IST):%Y-%m-%d %H:%M} IST · {n_cases} cases (`evals/station_parsing.jsonl`) · "
        f"batch `{batch_id}` · scored on the full system (model's `quote_trip` args -> `resolve_station`).",
        "Resolver alone on rule-split text: `uv run python -m evals.resolver_baseline`.",
        "",
        "| Model | Accuracy | Normal cases | Ambiguous -> asks | Preference | Median latency | $ / 1k messages |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in reports.values():
        normal = [x for x in r.results if x.category != "ambiguous"]
        amb = [x for x in r.results if x.category == "ambiguous"]
        prefs = [x.preference_ok for x in r.results if x.preference_ok is not None]
        median = f"{statistics.median(r.live_seconds):.2f} s" if r.live_seconds else "n/a"
        per_k = f"${cost(r.model, r.live_usage) / r.live_messages * 1000:.2f}" if r.live_messages else "n/a"
        lines.append(
            f"| `{r.model}` | **{sum(x.passed for x in r.results)}/{len(r.results)}** | "
            f"{sum(x.passed for x in normal)}/{len(normal)} | {sum(x.passed for x in amb)}/{len(amb)} | "
            f"{sum(prefs)}/{len(prefs)} | {median} | {per_k} |"
        )
    lines += ["", "**By category**", "", "| Category | " + " | ".join(reports) + " |",
              "| --- | " + " | ".join("---" for _ in reports) + " |"]
    cats = sorted({x.category for r in reports.values() for x in r.results})
    for cat in cats:
        cells = []
        for r in reports.values():
            xs = [x for x in r.results if x.category == cat]
            cells.append(f"{sum(x.passed for x in xs)}/{len(xs)}")
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    lines += ["", "**Cost notes**", ""]
    for r in reports.values():
        batch_cost = cost(r.model, r.batch_usage) * BATCH_DISCOUNT
        lines.append(
            f"- `{r.model}`: this batch (first call only, 50% batch price) ${batch_cost:.4f}; "
            f"live sample {r.live_messages} full bot turns ${cost(r.model, r.live_usage):.4f} at standard prices; "
            f"live tokens {dict(r.live_usage)}."
        )
    lines += ["- $/1k messages = live-sample cost per full bot turn (all tool rounds, caching as observed) x 1000.",
              "- Haiku 5.5 cache prices are assumed (0.1x / 1.25x input); see `PRICES` in `evals/run_eval.py`.",
              "", "**Failures**", ""]
    for r in reports.values():
        fails = [x for x in r.results if not x.passed or x.preference_ok is False]
        lines.append(f"- `{r.model}`: " + ("none" if not fails else ""))
        fails.sort(key=lambda x: x.case_id)
        lines += [f"  - `{x.case_id}` {x.category} {x.input!r}: {x.outcome}" for x in fails]
    RESULTS_MD.write_text("\n".join(lines) + "\n")
    RESULTS_JSON.write_text(json.dumps(
        {k: {"model": r.model, "results": [asdict(x) for x in sorted(r.results, key=lambda x: x.case_id)],
             "batch_usage": r.batch_usage, "live_usage": r.live_usage, "live_seconds": r.live_seconds}
         for k, r in reports.items()}, indent=1, ensure_ascii=False))
    print(f"wrote {RESULTS_MD.relative_to(HERE.parent)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--live", type=int, default=10, help="live end-to-end turns per model for latency/cost (0 = skip)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    cases = load_cases()
    if args.dry_run:
        print(f"{len(cases)} cases x {len(MODELS)} models = {len(cases) * len(MODELS)} batch requests; "
              f"live sample {args.live} turns per model; models {list(MODELS.values())}")
        return
    reports = {k: ModelReport(model=m) for k, m in MODELS.items()}
    batch_id = run_batch(anthropic.Anthropic(api_key=settings().anthropic_api_key), cases, reports)
    if args.live:
        asyncio.run(run_live(args.live, cases, reports))
    write_report(reports, batch_id, len(cases))


if __name__ == "__main__":
    main()
