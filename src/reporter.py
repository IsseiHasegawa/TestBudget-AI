"""Turn a run into a JSON artifact and a console summary.

The report always names what was *not* run. A green selective run is not a
green suite, and the report has to say so on its face.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.models import FAILING_OUTCOMES, RunOutcome, TestCandidate

SCHEMA_VERSION = 1

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
    selection_mode: str,
    budget_s: float | None = None,
    selection_reasons: dict[str, str] | None = None,
) -> dict:
    selected = set(outcome.selected)
    unselected = [candidate.nodeid for candidate in candidates if candidate.nodeid not in selected]
    reasons = selection_reasons or {}

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selection_mode": selection_mode,
        "budget_s": budget_s,
        "totals": {
            "collected": len(candidates),
            "selected": len(outcome.selected),
            "unselected": len(unselected),
            "wall_time_s": outcome.wall_time_s,
            **outcome.counts(),
        },
        "exit_status": outcome.exit_status,
        "timed_out": outcome.timed_out,
        "results": [
            {**result.to_dict(), "reason": reasons.get(result.nodeid, "")}
            for result in outcome.results
        ],
        "unselected": unselected,
        "coverage_caveat": (
            "A green selective run does not certify the full suite. "
            f"{len(unselected)} collected test(s) were not executed."
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


def render_console(report: dict) -> str:
    totals = report["totals"]
    lines = [
        "",
        f"selection mode : {report['selection_mode']}",
        f"collected      : {totals['collected']}",
        f"selected       : {totals['selected']}",
        f"not executed   : {totals['unselected']}",
        f"wall time      : {totals['wall_time_s']:.2f}s"
        + (f" (budget {report['budget_s']:.2f}s)" if report.get("budget_s") else ""),
        "",
    ]

    width = max((len(item["nodeid"]) for item in report["results"]), default=0)
    for item in report["results"]:
        glyph = _OUTCOME_GLYPH.get(item["outcome"], item["outcome"].upper())
        lines.append(f"  {glyph:<8} {item['nodeid']:<{width}}  {item['duration_s']:.3f}s")

    failures = [item for item in report["results"] if item["outcome"] in FAILING_OUTCOMES]
    if failures:
        lines.append("")
        lines.append(f"failures ({len(failures)}):")
        for item in failures:
            first_line = (item.get("message") or "").strip().splitlines()
            lines.append(f"  {item['nodeid']}")
            if first_line:
                lines.append(f"    {first_line[-1]}")

    if report["unselected"]:
        lines.append("")
        lines.append(f"not executed ({len(report['unselected'])}):")
        for nodeid in report["unselected"]:
            lines.append(f"  {nodeid}")

    lines.append("")
    lines.append(report["coverage_caveat"])
    lines.append("")
    return "\n".join(lines)
