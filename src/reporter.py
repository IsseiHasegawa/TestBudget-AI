"""Turn a run into a JSON artifact and a console summary.

The report always names what was not run and why. A green selective run is not
a green suite, and the report has to say so on its face. It also records
whether the ranking came from the model or from a fallback, so a silently
degraded run cannot pass for an AI-assisted one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.change_analyzer import ChangeSet
from src.models import FAILING_OUTCOMES, RunOutcome, TestCandidate
from src.scheduler import ExecutionPlan

SCHEMA_VERSION = 2

_OUTCOME_GLYPH = {
    "passed": "PASS",
    "failed": "FAIL",
    "error": "ERROR",
    "skipped": "SKIP",
    "timeout": "TIMEOUT",
    "not_run": "NOT RUN",
}


def build_report(
    outcome: RunOutcome,
    candidates: list[TestCandidate],
    plan: ExecutionPlan,
    changes: ChangeSet | None = None,
) -> dict:
    rank_of = {nodeid: index + 1 for index, nodeid in enumerate(plan.selected)}
    executed = set(outcome.selected)
    skipped_reasons = {item.nodeid: item.reason for item in plan.skipped}

    not_executed = []
    for candidate in candidates:
        if candidate.nodeid in executed:
            continue
        not_executed.append(
            {
                "nodeid": candidate.nodeid,
                "reason": skipped_reasons.get(candidate.nodeid, "not selected"),
            }
        )

    overrun = plan.budget_s > 0 and outcome.wall_time_s + plan.ai_elapsed_s > plan.budget_s

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "change": changes.to_dict() if changes else None,
        "ranking": {
            "source": plan.ranking_source,
            "fallback_reason": plan.fallback_reason,
            "ai_elapsed_s": plan.ai_elapsed_s,
            "model": plan.model_info,
        },
        "budget": {
            "budget_s": plan.budget_s,
            "ai_elapsed_s": plan.ai_elapsed_s,
            "available_s": round(plan.available_s, 3),
            "estimated_selected_s": round(plan.estimated_selected_s, 3),
            "actual_run_s": outcome.wall_time_s,
            "total_s": round(outcome.wall_time_s + plan.ai_elapsed_s, 3),
            "overrun": overrun,
            "safety_factor": plan.safety_factor,
        },
        "totals": {
            "collected": len(candidates),
            "selected": len(outcome.selected),
            "not_executed": len(not_executed),
            **outcome.counts(),
        },
        "exit_status": outcome.exit_status,
        "hard_killed": outcome.timed_out,
        "results": [
            {
                **result.to_dict(),
                "rank": rank_of.get(result.nodeid),
                "reason": plan.reasons.get(result.nodeid, ""),
            }
            for result in outcome.results
        ],
        "not_executed": not_executed,
        "warnings": plan.warnings,
        "coverage_caveat": (
            "A green selective run does not certify the full suite. "
            f"{len(not_executed)} of {len(candidates)} collected test(s) were not executed."
        ),
    }


def write_report(report: dict, path: Path | None = None) -> Path:
    if path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = config.ARTIFACT_DIR / f"run-{stamp}.json"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def render_plan(plan: ExecutionPlan, candidates: list[TestCandidate], limit: int = 0) -> str:
    """Console view of a plan that has not been executed yet."""
    estimates = {c.nodeid: c.estimated_duration_s for c in candidates}
    lines = [
        "",
        f"ranking source : {plan.ranking_source}"
        + (f" (fallback: {plan.fallback_reason})" if plan.fallback_reason else ""),
        f"budget         : {plan.budget_s:.2f}s"
        + (f", {plan.ai_elapsed_s:.2f}s spent ranking" if plan.ai_elapsed_s else ""),
        f"available      : {plan.available_s:.2f}s",
        f"estimated cost : {plan.estimated_selected_s:.2f}s "
        f"(durations x{plan.safety_factor} safety factor)",
        f"selected       : {len(plan.selected)}",
        f"skipped        : {len(plan.skipped)}",
        "",
    ]

    rows = plan.selected if limit <= 0 else plan.selected[:limit]
    width = max((len(nodeid) for nodeid in rows), default=0)
    for index, nodeid in enumerate(rows, start=1):
        estimate = estimates.get(nodeid)
        shown = f"{estimate:6.3f}s" if estimate is not None else "     ?s"
        lines.append(f"  {index:>3}. {nodeid:<{width}}  {shown}  {plan.reasons.get(nodeid, '')}")
    if limit > 0 and len(plan.selected) > limit:
        lines.append(f"  ... and {len(plan.selected) - limit} more")

    if plan.skipped:
        lines.append("")
        lines.append(f"skipped for budget ({len(plan.skipped)}):")
        for item in plan.skipped[:limit or len(plan.skipped)]:
            lines.append(f"  {item.nodeid}  [{item.reason}]")
        if limit > 0 and len(plan.skipped) > limit:
            lines.append(f"  ... and {len(plan.skipped) - limit} more")

    for warning in plan.warnings:
        lines.append(f"\nwarning: {warning}")
    lines.append("")
    return "\n".join(lines)


def render_console(report: dict) -> str:
    budget = report["budget"]
    ranking = report["ranking"]
    totals = report["totals"]

    lines = ["", f"ranking source : {ranking['source']}"]
    if ranking["fallback_reason"]:
        lines.append(f"fallback       : {ranking['fallback_reason']}")
    model = ranking.get("model") or {}
    if model.get("attempted"):
        detail = f" ({model['detail']})" if model.get("detail") else ""
        lines.append(
            f"model          : {model.get('model', '?')} "
            f"allowance {model.get('allowance_s', 0):.2f}s"
            + (f", {model['latency_s']:.2f}s in {model.get('attempts', 1)} attempt(s)" if model.get("latency_s") else "")
            + detail
        )
        if model.get("discarded"):
            lines.append(f"discarded ids  : {len(model['discarded'])}")
        if model.get("completed_by_fallback"):
            lines.append(f"model omitted  : {len(model['completed_by_fallback'])} test(s), appended deterministically")
    if report.get("change"):
        paths = [entry["path"] for entry in report["change"]["files"]]
        lines.append(f"changed files  : {len(paths)} ({', '.join(paths[:3])}{'...' if len(paths) > 3 else ''})")
    lines += [
        f"collected      : {totals['collected']}",
        f"selected       : {totals['selected']}",
        f"not executed   : {totals['not_executed']}",
        f"budget         : {budget['budget_s']:.2f}s"
        if budget["budget_s"]
        else "budget         : none",
        f"  ranking      : {budget['ai_elapsed_s']:.2f}s",
        f"  estimated    : {budget['estimated_selected_s']:.2f}s",
        f"  actual       : {budget['actual_run_s']:.2f}s",
        f"  total        : {budget['total_s']:.2f}s"
        + ("  OVER BUDGET" if budget["overrun"] else ""),
        "",
    ]

    width = max((len(item["nodeid"]) for item in report["results"]), default=0)
    for item in report["results"]:
        glyph = _OUTCOME_GLYPH.get(item["outcome"], item["outcome"].upper())
        rank = f"{item['rank']:>3}." if item.get("rank") else "   ."
        lines.append(f"  {rank} {glyph:<8} {item['nodeid']:<{width}}  {item['duration_s']:.3f}s")

    failures = [item for item in report["results"] if item["outcome"] in FAILING_OUTCOMES]
    if failures:
        lines.append("")
        lines.append(f"failures ({len(failures)}):")
        for item in failures:
            lines.append(f"  {item['nodeid']}")
            message = (item.get("message") or "").strip().splitlines()
            if message:
                lines.append(f"    {message[-1]}")
            if item.get("reason"):
                lines.append(f"    selected because: {item['reason']}")

    if report["not_executed"]:
        lines.append("")
        lines.append(f"not executed ({len(report['not_executed'])}):")
        for entry in report["not_executed"]:
            lines.append(f"  {entry['nodeid']}  [{entry['reason']}]")

    for warning in report["warnings"]:
        lines.append(f"\nwarning: {warning}")

    lines.append("")
    lines.append(report["coverage_caveat"])
    lines.append("")
    return "\n".join(lines)


def render_markdown(report: dict) -> str:
    """Report as markdown, for a GitHub Actions job summary.

    Writing to the step summary needs no repository permission at all, unlike
    posting a pull request comment, so the workflow can stay on contents:read.
    """
    budget = report["budget"]
    ranking = report["ranking"]
    totals = report["totals"]
    model = ranking.get("model") or {}

    source = ranking["source"]
    if ranking["fallback_reason"]:
        source = f"{source} (fell back: `{ranking['fallback_reason']}`)"

    failures = [item for item in report["results"] if item["outcome"] in FAILING_OUTCOMES]
    headline = f"{len(failures)} failing" if failures else "no failures"

    lines = [
        "## TestBudget AI",
        "",
        f"**{totals['selected']} of {totals['collected']} tests run in "
        f"{budget['total_s']:.1f}s, {headline}.**",
        "",
        "| | |",
        "|---|---|",
        f"| Ranking | {source} |",
    ]
    if model.get("attempted"):
        detail = model.get("detail") or (
            f"{model.get('latency_s', 0):.2f}s in {model.get('attempts', 1)} attempt(s)"
        )
        lines.append(f"| Model | `{model.get('model', '?')}` {detail} |")
    if report.get("change"):
        paths = [entry["path"] for entry in report["change"]["files"]]
        lines.append(f"| Changed files | {len(paths)}: {', '.join(f'`{p}`' for p in paths[:5])} |")
    lines += [
        f"| Budget | {budget['budget_s']:.1f}s "
        f"({budget['ai_elapsed_s']:.1f}s ranking, {budget['actual_run_s']:.1f}s tests) |",
        f"| Not executed | {totals['not_executed']} |",
        "",
    ]

    if budget["overrun"]:
        lines += ["> Budget exceeded.", ""]
    for warning in report["warnings"]:
        lines += [f"> {warning}", ""]

    if failures:
        lines += ["### Failures", ""]
        for item in failures:
            lines.append(f"- `{item['nodeid']}` ({item['outcome']})")
            if item.get("reason"):
                lines.append(f"  - selected because: {item['reason']}")
        lines.append("")

    lines += ["<details><summary>Executed, in the order chosen</summary>", ""]
    for item in report["results"]:
        rank = item.get("rank") or "-"
        lines.append(
            f"{rank}. `{item['nodeid']}` {item['outcome']} ({item['duration_s']:.3f}s)"
        )
    lines += ["", "</details>", ""]

    if report["not_executed"]:
        lines += [
            f"<details><summary>Not executed ({len(report['not_executed'])})</summary>",
            "",
        ]
        for entry in report["not_executed"]:
            lines.append(f"- `{entry['nodeid']}` ({entry['reason']})")
        lines += ["", "</details>", ""]

    lines += ["", f"_{report['coverage_caveat']}_", ""]
    return "\n".join(lines)
