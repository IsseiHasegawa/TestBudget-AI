"""Aggregate benchmark measurements into a table.

    python -m evaluation.report
    python -m evaluation.report --markdown evaluation/results/benchmark.md
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from evaluation.scenarios import BY_NAME
from src import config

RESULTS = config.ROOT / "evaluation" / "results" / "benchmark.json"


def _by_strategy(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["strategy"], []).append(row)
    return grouped


def summarise(rows: list[dict]) -> list[dict]:
    summary = []
    for strategy, group in _by_strategy(rows).items():
        breaking = [row for row in group if row["faults_total"]]
        benign = [row for row in group if not row["faults_total"]]
        found = sum(row["faults_found"] for row in breaking)
        total = sum(row["faults_total"] for row in breaking)
        ttff = [
            row["estimated_time_to_first_failure_s"]
            for row in breaking
            if row["estimated_time_to_first_failure_s"] is not None
        ]
        summary.append(
            {
                "strategy": strategy,
                "scenarios": len(group),
                "recall": found / total if total else None,
                "faults_found": found,
                "faults_total": total,
                "full_recall_scenarios": sum(
                    1 for row in breaking if row["faults_found"] == row["faults_total"]
                ),
                "blind_scenarios": sum(1 for row in breaking if row["faults_found"] == 0),
                "breaking_scenarios": len(breaking),
                "mean_selected": statistics.mean(row["selected"] for row in group),
                "mean_ttff_s": statistics.mean(ttff) if ttff else None,
                "mean_ai_s": statistics.mean(row["ai_elapsed_s"] for row in group),
                "benign_mean_selected": (
                    statistics.mean(row["selected"] for row in benign) if benign else None
                ),
                "answered": sum(row["model_calls_that_answered"] for row in group),
                "attempts": sum(row["model_attempts"] for row in group),
                "fallbacks": sum(1 for row in group if row["fallback_reason"]),
            }
        )
    summary.sort(key=lambda item: (-(item["recall"] or 0), item["mean_ttff_s"] or 1e9))
    return summary


def by_reachability(rows: list[dict]) -> dict[str, dict[str, tuple[int, int]]]:
    """Split recall by whether a filename rule could reach the faults at all.

    This is the split that matters. Aggregate recall is dominated by changes
    whose own test file is named after them, where matching on the filename is
    already perfect and no amount of reading the diff can beat it. The question
    the project exists to answer is what happens to the faults that live
    somewhere else.
    """
    buckets: dict[str, dict[str, list[int]]] = {"indirect": {}, "filename_reachable": {}}
    for row in rows:
        if not row["faults_total"]:
            continue
        baseline = next(
            other for other in rows
            if other["scenario"] == row["scenario"]
            and other["strategy"] == "file_rule"
            and other["repeat"] == row["repeat"]
        )
        stem = Path(BY_NAME[row["scenario"]].path).stem
        has_indirect = any(f"test_{stem}.py" not in nodeid for nodeid in baseline["missed"])
        tally = buckets["indirect" if has_indirect else "filename_reachable"].setdefault(
            row["strategy"], [0, 0]
        )
        tally[0] += row["faults_found"]
        tally[1] += row["faults_total"]
    return {
        name: {strategy: tuple(counts) for strategy, counts in group.items()}
        for name, group in buckets.items()
    }


def render(payload: dict, markdown: bool = False) -> str:
    rows = payload["measurements"]
    summary = summarise(rows)
    order = [item["strategy"] for item in summary]
    bar = "**" if markdown else ""

    out = [f"# Evaluation, {payload['budget_s']:.0f}s budget" if markdown else
           f"Evaluation at a {payload['budget_s']:.0f}s budget", ""]
    out.append(payload["note"])
    out.append("")

    out.append("## Per strategy" if markdown else "PER STRATEGY")
    out.append("")
    if markdown:
        out.append("| Strategy | Faults found | Recall | Scenarios fully caught | Scenarios missed entirely | Mean tests run | Mean time to first failure |")
        out.append("|---|---|---|---|---|---|---|")
    for item in summary:
        recall = f"{item['recall']:.0%}" if item["recall"] is not None else "n/a"
        ttff = f"{item['mean_ttff_s']:.1f}s" if item["mean_ttff_s"] is not None else "none found"
        best = bar if item is summary[0] else ""
        cells = [
            f"`{item['strategy']}`" if markdown else item["strategy"],
            f"{item['faults_found']} / {item['faults_total']}",
            f"{best}{recall}{best}",
            f"{item['full_recall_scenarios']} / {item['breaking_scenarios']}",
            f"{item['blind_scenarios']} / {item['breaking_scenarios']}",
            f"{item['mean_selected']:.1f}",
            ttff,
        ]
        out.append("| " + " | ".join(cells) + " |" if markdown
                   else f"  {cells[0]:<12} {cells[1]:>9}  {recall:>5}  full {cells[3]:>7}  blind {cells[4]:>7}  run {cells[5]:>5}  ttff {ttff:>10}")
    out.append("")

    split = by_reachability(rows)
    labels = {
        "indirect": "Faults a filename rule cannot reach",
        "filename_reachable": "Faults in the test file named after the change",
    }
    out.append("## Recall, split by what a filename rule can reach" if markdown
               else "RECALL BY REACHABILITY")
    out.append("")
    if markdown:
        out.append("| Faults | " + " | ".join(f"`{s}`" for s in order) + " |")
        out.append("|---|" + "---|" * len(order))
    for key, group in split.items():
        cells = []
        for strategy in order:
            found, total = group.get(strategy, (0, 0))
            cells.append(f"{found}/{total} ({found / total:.0%})" if total else "n/a")
        if markdown:
            out.append(f"| {labels[key]} | " + " | ".join(cells) + " |")
        else:
            out.append(f"  {labels[key]:<48} " + "  ".join(f"{c:>14}" for c in cells))
    out.append("")

    model = [item for item in summary if item["attempts"]]
    if model:
        out.append("## Model reliability" if markdown else "MODEL RELIABILITY")
        out.append("")
        for item in model:
            rate = item["answered"] / item["attempts"] if item["attempts"] else 0
            line = (
                f"{item['answered']} of {item['attempts']} calls answered ({rate:.0%}); "
                f"{item['fallbacks']} scenario(s) fell back; "
                f"mean {item['mean_ai_s']:.2f}s spent ranking per scenario"
            )
            out.append(f"- `{item['strategy']}`: {line}" if markdown else f"  {item['strategy']}: {line}")
        out.append("")
        out.append(
            "CI gets one allowance and falls back. The retries above exist to "
            "characterise the ranking, not to describe production behaviour."
        )
        out.append("")

    out.append("## Per scenario" if markdown else "PER SCENARIO")
    out.append("")
    scenarios: dict[str, dict] = {}
    for row in rows:
        scenarios.setdefault(row["scenario"], {"shape": row["shape"], "faults": row["faults_total"]})
    if markdown:
        out.append("| Scenario | Shape | Faults | " + " | ".join(f"`{s}`" for s in order) + " |")
        out.append("|---|---|---|" + "---|" * len(order))
    for name, meta in scenarios.items():
        cells = []
        for strategy in order:
            row = next(r for r in rows if r["scenario"] == name and r["strategy"] == strategy)
            if not meta["faults"]:
                cells.append(f"{row['selected']} run")
            else:
                mark = "" if row["faults_found"] == row["faults_total"] else " miss"
                cells.append(f"{row['faults_found']}/{row['faults_total']}{mark}")
        if markdown:
            out.append(f"| `{name}` | {meta['shape']} | {meta['faults']} | " + " | ".join(cells) + " |")
        else:
            out.append(f"  {name:<30} {meta['faults']:>2}  " + "  ".join(f"{c:>9}" for c in cells))
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report", description=__doc__)
    parser.add_argument("--results", default=str(RESULTS))
    parser.add_argument("--markdown", default=None, help="also write markdown here")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.results).read_text(encoding="utf-8"))
    print(render(payload))
    if args.markdown:
        path = Path(args.markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(payload, markdown=True), encoding="utf-8")
        print(f"markdown written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
