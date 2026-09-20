"""Add an optional Nemotron explanation to a saved report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.ai_explanation import ExplanationRejected, attach_explanation
from src.ai_explanation_client import explain_test_relevance
from src.model_response import ResponseRejected


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview or request an AI explanation for one reported test."
    )
    parser.add_argument("report_json", type=Path)
    parser.add_argument("--nodeid", required=True)
    parser.add_argument("--diff-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()

    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    if args.output.resolve() == args.report_json.resolve():
        parser.error("Output must be different from the original report")

    report = json.loads(args.report_json.read_text(encoding="utf-8"))

    records = [
        record for record in report.get("selection_evidence", [])
        if record.get("nodeid") == args.nodeid
    ]
    if len(records) != 1:
        parser.error("Exactly one matching test must exist in the report")

    paths = [
        item for item in records[0].get("code_evidence", [])
        if item.get("type") == "static_call_path"
    ]
    if len(paths) != 1:
        parser.error(
            "This version requires exactly one static call path "
            "for the selected test"
        )

    evidence = paths[0]
    diff = args.diff_file.read_text(encoding="utf-8")

    if not diff.strip() or len(diff) > 1500:
        parser.error("The reviewed diff must contain 1–1500 characters")

    print("\n=== NEMOTRON REQUEST PREVIEW ===")
    print(f"Test: {args.nodeid}")
    print(f"Changed file: {evidence['changed_file']}")
    print(f"Changed function: {evidence['changed_function']}")
    print(f"Static path: {' -> '.join(evidence['call_path'])}")
    print("\nDiff to be sent:\n")
    print(diff)
    print("\n=== END PREVIEW ===")

    if not args.send:
        print("\nPreview only. No API request was sent.")
        print("Review the diff, then rerun with --send to request an explanation.")
        return

    if args.output.exists():
        parser.error("Output already exists; choose a new output filename")

    if input("\nType SEND to submit this data to Nemotron: ") != "SEND":
        print("Cancelled. No API request was sent.")
        return

    try:
        explanation = explain_test_relevance(
            nodeid=args.nodeid,
            test_summary="",
            changed_file=evidence["changed_file"],
            changed_function=evidence["changed_function"],
            call_path=evidence["call_path"],
            changed_diff=diff,
            timeout_s=args.timeout,
        )
    except (ResponseRejected, ExplanationRejected) as exc:
        parser.exit(1, f"Explanation unavailable: {exc}\n")

    updated = attach_explanation(report, args.nodeid, explanation)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("x", encoding="utf-8") as file:
        json.dump(updated, file, indent=2, ensure_ascii=False)
        file.write("\n")

    print(f"\nExplanation saved to: {args.output}")


if __name__ == "__main__":
    main()
