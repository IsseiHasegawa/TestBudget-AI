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

    collected = totals["collected"]
    selected_count = len(selected)
    not_selected_count = len(not_selected)

    selection_rate = (
        selected_count / collected * 100 if collected else 0.0
    )
    filled = round(selection_rate / 100 * 12)
    selection_bar = "█" * filled + "░" * (12 - filled)

    manual_includes = [
        r for r in selected
        if r["decision_code"] == "manual_include"
    ]
    manual_excludes = [
        r for r in not_selected
        if r["decision_code"] == "manual_exclude"
    ]

    lines = [
        "# Test Selection Report",
        "",
        "> **TestBudget-AI** · Explainable test selection under a time budget",
        "",
        "## 📊 Run at a glance",
        "",
        "| 🧪 Selected | ⏱️ Actual test time | 📦 Estimated cost | ⏭️ Not selected |",
        "| ---: | ---: | ---: | ---: |",
        f"| **{selected_count}/{collected}** "
        f"| **{seconds(budget['actual_run_s'])}** "
        f"| **{seconds(budget['estimated_selected_s'])}** "
        f"| **{not_selected_count}** |",
        "",
        f"**Selection rate:** `{selection_bar}` "
        f"**{selection_rate:.0f}%**",
        "",
        f"**Ranking source:** {safe(ranking['source'])}  ",
        f"**Time budget:** {seconds(budget['budget_s'])}  ",
        f"**Selected:** {selected_count}/{collected}  ",
        f"**Estimated selected cost:** "
        f"{seconds(budget['estimated_selected_s'])}  ",
        f"**Actual test time:** {seconds(budget['actual_run_s'])}",
        "",
        "> **Scope:** This is a selective run. "
        "A green result does not certify the full test suite.",
        "",
    ]

    if manual_includes or manual_excludes:
        lines.extend([
            "## 🎛️ Developer overrides",
            "",
            f"**Manually included:** {len(manual_includes)}  ",
            f"**Manually excluded:** {len(manual_excludes)}",
            "",
        ])

        for record in manual_includes:
            lines.append(
                f"- **INCLUDE** · `{safe(record['nodeid'])}`"
            )

        for record in manual_excludes:
            lines.append(
                f"- **EXCLUDE** · `{safe(record['nodeid'])}`"
            )

        lines.append("")

    if report.get("demo_only") is True:
        lines.extend([
            "**DEMO ONLY — NOT AN ACTUAL TEST RUN.**",
            "",
            safe(report.get("demo_note") or (
                "This report uses synthetic data; no test execution "
                "is demonstrated."
            )),
            "",
        ])

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
        is_manual = record["decision_code"] == "manual_include"
        label = "🎛️ MANUAL INCLUDE" if is_manual else "✅ SELECTED"

        lines.extend([
            "<details open>" if is_manual else "<details>",
            f"<summary><strong>{label}</strong> · "
            f"<code>{safe(record['nodeid'])}</code></summary>",
            "",
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

        for evidence in record.get("code_evidence", []):
            if evidence.get("type") != "static_call_path":
                continue

            lines.extend([
                "**Static call path (execution not verified):**",
                "",
                "- " + " → ".join(
                    f"`{safe(symbol)}`"
                    for symbol in evidence["call_path"]
                ),
                "- **Changed function:** "
                f"`{safe(evidence['changed_file'])}` / "
                f"`{safe(evidence['changed_function'])}`",
                "- **Source snapshot:** "
                f"{safe(evidence['source_snapshot'])}",
                "",
            ])

        ai = record.get("ai_explanation")
        if (
            isinstance(ai, dict)
            and ai.get("type") == "ai_inferred_relevance"
            and ai.get("source") == "nemotron"
            and isinstance(ai.get("explanation"), str)
        ):
            lines.extend([
                "**AI-inferred relevance (not verified):**",
                "",
                safe(ai["explanation"]),
                "",
            ])

        lines.extend(["</details>", ""])

    lines.extend(["## Not selected", ""])

    groups = [
        ("🎛️ Manually excluded", []),
        ("⏱️ Budget-limited", []),
        ("🔎 Relevance-filtered", []),
        ("📋 Other decisions", []),
    ]

    for record in not_selected:
        code = record["decision_code"]
        reason = record["decision_reason"]

        if code == "manual_exclude":
            group_index = 0
        elif code in {
            "insufficient_budget",
            "manual_include_insufficient_budget",
            "no_budget_after_ranking",
        }:
            group_index = 1
        elif "relevan" in code.lower() or (
            "relevance policy" in reason.lower()
        ):
            group_index = 2
        else:
            group_index = 3

        groups[group_index][1].append(record)

    if not not_selected:
        lines.extend(["All collected tests were selected.", ""])

    for title, group_records in groups:
        if not group_records:
            continue

        # Show manual exclusions immediately; fold away longer lists.
        opening = "<details open>" if title.startswith("🎛️") else "<details>"
        lines.extend([
            opening,
            f"<summary><strong>{title} "
            f"({len(group_records)})</strong></summary>",
            "",
            "| Test | Decision type | Reason | Estimated cost |",
            "| --- | --- | --- | ---: |",
        ])

        for record in group_records:
            lines.append(
                f"| `{safe(record['nodeid'])}` "
                f"| {safe(record['decision_code'])} "
                f"| {safe(record['decision_reason'])} "
                f"| {seconds(record['estimated_cost_s'])} |"
            )

        lines.extend(["", "</details>", ""])

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
