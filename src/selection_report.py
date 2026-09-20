"""Generate a Markdown test-selection report from a saved JSON run."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


def safe(value: object) -> str:
    """Keep report data from being interpreted as Markdown or HTML."""
    return (
        html.escape(str(value), quote=True)
        .replace("|", "&#124;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def seconds(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}s"


def render_markdown(report: dict) -> str:
    records = report.get("selection_evidence")
    if not records:
        raise ValueError(
            "This JSON has no selection_evidence. "
            "Generate a new report with the updated TestBudget-AI."
        )

    totals = report["totals"]
    budget = report["budget"]
    ranking = report["ranking"]

    if len(records) != totals["collected"]:
        raise ValueError(
            "The number of evidence records does not match collected tests."
        )

    selected = [r for r in records if r["status"] == "SELECTED"]
    not_selected = [
        r for r in records if r["status"] == "NOT_SELECTED"
    ]

    # Display executed tests in their actual run order.
    result_order = {
        result["nodeid"]: index
        for index, result in enumerate(report.get("results", []))
    }
    selected.sort(
        key=lambda record: result_order.get(
            record["nodeid"], float("inf")
        )
    )

    if len(selected) != totals["selected"]:
        raise ValueError(
            "The number of selected records does not match the run summary."
        )

    lines = [
        "# Test Selection Report",
        "",
        f"**Ranking source:** {safe(ranking['source'])}  ",
        f"**Time budget:** {seconds(budget['budget_s'])}  ",
        f"**Selected:** {len(selected)}/{totals['collected']}  ",
        f"**Estimated selected cost:** "
        f"{seconds(budget['estimated_selected_s'])}  ",
        f"**Actual test time:** {seconds(budget['actual_run_s'])}",
        "",
    ]

    if ranking.get("fallback_reason"):
        lines.extend([
            f"**Ranking fallback:** "
            f"{safe(ranking['fallback_reason'])}",
            "",
        ])

    change = report.get("change") or {}
    changed_files = [
        entry["path"]
        for entry in change.get("files", [])
    ]
    if changed_files:
        lines.extend([
            "## Changed files",
            "",
            *[f"- `{safe(path)}`" for path in changed_files],
            "",
        ])

    lines.extend([
        "## Selected tests",
        "",
        "These tests were included in the execution plan.",
        "",
    ])

    if not selected:
        lines.extend(["No tests were selected.", ""])

    for record in selected:
        lines.extend([
            f"### `{safe(record['nodeid'])}`",
            "",
            f"- **Decision:** {safe(record['decision_reason'])}",
            f"- **Ranking reason:** "
            f"{safe(record['ranking_reason']) or 'Not recorded'}",
            f"- **Ranking source:** "
            f"{safe(record['ranking_source'])}",
            f"- **Ranking score:** "
            f"{safe(record['ranking_score'])}",
            f"- **Estimated runtime:** "
            f"{seconds(record['estimated_duration_s'])}",
            f"- **Budgeted cost (with safety factor):** "
            f"{seconds(record['estimated_cost_s'])}",
            f"- **Remaining budget before decision:** "
            f"{seconds(record['remaining_budget_before_s'])}",
            f"- **Cumulative cost after decision:** "
            f"{seconds(record['cumulative_cost_after_s'])}",
            "",
        ])

    lines.extend([
        "## Not selected",
        "",
        "| Test | Decision type | Reason | Estimated cost |",
        "| --- | --- | --- | ---: |",
    ])

    for record in not_selected:
        lines.append(
            f"| `{safe(record['nodeid'])}` "
            f"| {safe(record['decision_code'])} "
            f"| {safe(record['decision_reason'])} "
            f"| {seconds(record['estimated_cost_s'])} |"
        )

    lines.extend([
        "",
        "## Interpretation notes",
        "",
        "- Ranking reasons are recorded algorithm outputs, "
        "not independently verified code dependencies.",
        "- A relevance-filter exclusion is not a budget rejection. "
        "No remaining-budget value is recorded for that decision.",
        "- Ranking positions may refer to different stages of filtering; "
        "they should not yet be compared as one global order.",
        f"- {safe(report['coverage_caveat'])}",
        "",
    ])

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a Markdown report from TestBudget-AI JSON."
    )
    parser.add_argument("report_json", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/test-selection-report.md"),
    )
    args = parser.parse_args()

    report = json.loads(
        args.report_json.read_text(encoding="utf-8")
    )
    markdown = render_markdown(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    print(f"Markdown report written: {args.output}")


if __name__ == "__main__":
    main()
