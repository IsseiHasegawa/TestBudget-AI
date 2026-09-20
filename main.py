"""TestBudget AI command line entry point.

The pipeline is collect -> analyse the change -> rank -> plan -> run -> report.
Only the ranking step is ever delegated to a model, and its output is advice
that the planner is free to discard. Everything after ranking is deterministic.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src import config
from src.change_analyzer import ChangeAnalysisError, ChangeSet, collect_changes, collect_working_tree_changes
from src.history import DurationHistory
from src.models import TestCandidate
from src.model_response import ResponseRejected
from src.nemotron_client import is_configured, model_name, rank_with_model
from src.prioritizer import NEMOTRON, STRATEGIES, KEYWORD, from_model_order, rank
from src.reporter import build_report, render_console, render_markdown, render_plan, write_report
from src.scheduler import ExecutionPlan, SkippedTest, ai_time_allowance, build_plan
from src.test_collector import CollectionError, collect_tests, validate_nodeids
from src.test_runner import run_tests


def _history(args: argparse.Namespace) -> DurationHistory:
    return DurationHistory.load(Path(args.history) if args.history else None)


def _changes(args: argparse.Namespace) -> ChangeSet:
    if args.base:
        return collect_changes(args.base, args.head)
    return collect_working_tree_changes()


def _must_run(args: argparse.Namespace) -> list[str]:
    values = list(getattr(args, "must_run", None) or [])
    if getattr(args, "must_run_file", None):
        text = Path(args.must_run_file).read_text(encoding="utf-8")
        values.extend(line.strip() for line in text.splitlines() if line.strip())
    return values


def cmd_collect(args: argparse.Namespace) -> int:
    candidates = collect_tests(target=args.target, history=_history(args))
    if not candidates:
        print(f"no tests collected under {args.target}", file=sys.stderr)
        return 1

    known = sum(1 for c in candidates if c.estimated_duration_s is not None)
    total = sum(c.estimated_duration_s or 0.0 for c in candidates)
    width = max(len(c.nodeid) for c in candidates)

    print(f"collected {len(candidates)} test(s) from {args.target}\n")
    for candidate in candidates:
        estimate = (
            f"{candidate.estimated_duration_s:6.3f}s"
            if candidate.estimated_duration_s is not None
            else "     ?s"
        )
        marks = f" [{','.join(candidate.markers)}]" if candidate.markers else ""
        print(f"  {candidate.nodeid:<{width}}  {estimate}  {candidate.summary}{marks}")

    print(f"\n{known}/{len(candidates)} measured (estimated suite time {total:.2f}s)")
    if known < len(candidates):
        print("run `python main.py run --all` once to fill in the missing measurements")

    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([c.to_dict() for c in candidates], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"wrote {path}")
    return 0


def cmd_changes(args: argparse.Namespace) -> int:
    changes = _changes(args)
    if changes.is_empty():
        print("no changes detected")
        return 0

    print(f"{changes.base}..{changes.head}: {len(changes.files)} file(s)")
    if changes.truncated:
        print("warning: the file list was truncated")
    for changed in changes.files:
        symbols = f"  symbols: {', '.join(changed.symbols)}" if changed.symbols else ""
        print(f"  {changed.status}  +{changed.added_lines:<5} -{changed.removed_lines:<5} {changed.path}{symbols}")
    return 0


def _rank(args, candidates, changes):
    """Produce an ordering plus the metadata the report needs.

    The deterministic ranking is computed first and unconditionally, so the
    model call has something to degrade to. A failure here is ordinary control
    flow, not an error path.
    """
    fallback = rank(args.fallback_strategy, candidates, changes)
    if args.strategy != NEMOTRON:
        return rank(args.strategy, candidates, changes), args.strategy, None, 0.0, {}

    allowance = ai_time_allowance(args.budget)
    started = time.perf_counter()
    try:
        result = rank_with_model(
            candidates, changes, allowance, [item.nodeid for item in fallback]
        )
    except ResponseRejected as exc:
        elapsed = round(time.perf_counter() - started, 3)
        info = {"attempted": True, "model": model_name(), "allowance_s": allowance, "detail": exc.detail}
        return fallback, args.fallback_strategy, exc.reason, elapsed, info

    info = {
        "attempted": True,
        "model": result.model,
        "allowance_s": allowance,
        "attempts": result.attempts,
        "latency_s": result.latency_s,
        "discarded": result.discarded,
        "completed_by_fallback": result.completed_by_fallback,
    }
    ranked = from_model_order(result.order, result.reasons, result.completed_by_fallback)
    return ranked, NEMOTRON, None, result.latency_s, info


def _plan_for(args: argparse.Namespace, candidates: list[TestCandidate]) -> tuple[ExecutionPlan, ChangeSet]:
    changes = _changes(args)
    ranked, source, fallback_reason, ai_elapsed, info = _rank(args, candidates, changes)

    excluded = []
    relevant_found = True

    if getattr(args, "selection_policy", "fill") == "relevant":
        # Weak signals, such as "same package" alone, are insufficient.
        # This is a general heuristic: no demo-specific test names.
        keyword_scores = {
            item.nodeid: item.score
            for item in rank(KEYWORD, candidates, changes)
        }
        eligible = {
            nodeid for nodeid, score in keyword_scores.items()
            if score >= 1.0
        }
        eligible.update(_must_run(args))
        relevant_found = bool(eligible)

        if relevant_found:
            excluded = [item for item in ranked if item.nodeid not in eligible]
            ranked = [item for item in ranked if item.nodeid in eligible]

    plan = build_plan(
        ranked,
        candidates,
        budget_s=args.budget,
        ai_elapsed_s=ai_elapsed,
        must_run=_must_run(args),
        ranking_source=source,
        fallback_reason=fallback_reason,
        model_info=info,
    )
    if getattr(args, "selection_policy", "fill") == "relevant":
        if relevant_found:
            plan.skipped.extend(
                SkippedTest(
                    item.nodeid,
                    "excluded by experimental relevance policy",
                )
                for item in excluded
            )
            plan.warnings.append(
                "experimental relevance policy: only tests with a "
                "keyword relevance score >= 1.0 were eligible"
            )
        else:
            plan.warnings.append(
                "experimental relevance policy found no strong matches; "
                "used the original budget-filling behavior"
            )

    return plan, changes


def cmd_select(args: argparse.Namespace) -> int:
    candidates = collect_tests(target=args.target, history=_history(args))
    if not candidates:
        print(f"no tests collected under {args.target}", file=sys.stderr)
        return 1

    plan, changes = _plan_for(args, candidates)
    if changes.is_empty():
        print("warning: no changes detected; the ranking has nothing to work from\n")
    else:
        print(f"\nchange: {changes.summary()}")
    print(render_plan(plan, candidates, limit=args.limit))
    print(f"model time allowance at this budget: {ai_time_allowance(args.budget):.2f}s")
    if not is_configured():
        print("NVIDIA_API_KEY is not set; --strategy nemotron would fall back immediately")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    history = _history(args)
    candidates = collect_tests(target=args.target, history=history)
    if not candidates:
        print(f"no tests collected under {args.target}", file=sys.stderr)
        return 1

    changes: ChangeSet | None = None
    if args.all:
        selected = [candidate.nodeid for candidate in candidates]
        plan = ExecutionPlan(selected=selected, budget_s=args.budget or 0.0, ranking_source="all")
    elif args.nodeid or args.from_file:
        requested = list(args.nodeid or [])
        if args.from_file:
            text = Path(args.from_file).read_text(encoding="utf-8")
            requested.extend(line.strip() for line in text.splitlines() if line.strip())
        selected, unknown = validate_nodeids(requested, candidates)
        for nodeid in unknown:
            print(f"discarded unknown nodeid: {nodeid}", file=sys.stderr)
        if not selected:
            print("no valid nodeid left after validation", file=sys.stderr)
            return 2
        plan = ExecutionPlan(selected=selected, budget_s=args.budget or 0.0, ranking_source="manual")
    else:
        if args.budget is None:
            print("budget mode needs --budget (or use --all / --nodeid)", file=sys.stderr)
            return 2
        plan, changes = _plan_for(args, candidates)
        if changes.is_empty():
            print("warning: no changes detected; the ranking has nothing to work from")

    outcome = run_tests(
        plan.selected,
        timeout_s=plan.available_s if plan.budget_s else None,
        per_test_timeout_s=args.per_test_timeout,
    )
    report = build_report(outcome, candidates, plan, changes)
    print(render_console(report))

    if not args.no_history:
        history.record(outcome.results)
        print(f"history updated: {history.save()}")

    path = write_report(report, Path(args.json) if args.json else None)
    print(f"report written: {path}")

    if args.markdown:
        markdown_path = Path(args.markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        # Appended, because GITHUB_STEP_SUMMARY may already hold earlier output.
        with markdown_path.open("a", encoding="utf-8") as handle:
            handle.write(render_markdown(report))
        print(f"markdown written: {markdown_path}")

    return 1 if outcome.failures() else 0


def cmd_history(args: argparse.Namespace) -> int:
    history = _history(args)
    if not history.tests:
        print("no history recorded yet; run `python main.py run --all`")
        return 0

    rows = sorted(
        history.tests.items(), key=lambda item: item[1].estimate() or 0.0, reverse=True
    )[: args.top]
    width = max(len(nodeid) for nodeid, _ in rows)

    print(f"{len(history.tests)} test(s) recorded in {history.path}\n")
    for nodeid, entry in rows:
        print(
            f"  {nodeid:<{width}}  {entry.estimate():6.3f}s  "
            f"runs={entry.run_count} fails={entry.fail_count} last={entry.last_outcome}"
        )
    print(f"\nestimated full suite: {history.total_estimate(list(history.tests)):.2f}s")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="testbudget", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--target", default=config.DEMO_TARGET, help="pytest path to collect from")
    common.add_argument("--history", default=None, help="path to the duration history file")

    diff = argparse.ArgumentParser(add_help=False)
    diff.add_argument("--base", default=None, help="base ref; omit to use uncommitted changes")
    diff.add_argument("--head", default="HEAD", help="head ref (default HEAD)")

    ranking = argparse.ArgumentParser(add_help=False)
    ranking.add_argument(
        "--strategy", default=KEYWORD, choices=sorted({*STRATEGIES, NEMOTRON})
    )
    ranking.add_argument(
        "--fallback-strategy",
        default=KEYWORD,
        choices=sorted(STRATEGIES),
        help="ordering used when the model is unavailable or rejected",
    )
    ranking.add_argument(
        "--selection-policy",
        choices=("fill", "relevant"),
        default="fill",
        help="fill: existing budget-packing behavior; relevant: experimental relevance filter",
    )
    ranking.add_argument("--must-run", action="append", help="repeatable; always runs first")
    ranking.add_argument("--must-run-file", default=None, help="file with one nodeid per line")

    collect = sub.add_parser("collect", parents=[common], help="list collected nodeids")
    collect.add_argument("--json", default=None, help="also write the candidates here")
    collect.set_defaults(func=cmd_collect)

    changes = sub.add_parser("changes", parents=[diff], help="show what the diff touched")
    changes.set_defaults(func=cmd_changes)

    select = sub.add_parser(
        "select", parents=[common, diff, ranking], help="build a plan without running it"
    )
    select.add_argument("--budget", type=float, required=True, help="seconds available")
    select.add_argument("--limit", type=int, default=0, help="truncate the printed lists")
    select.set_defaults(func=cmd_select)

    run = sub.add_parser("run", parents=[common, diff, ranking], help="plan and run")
    run.add_argument("--budget", type=float, default=None, help="seconds available")
    run.add_argument("--nodeid", action="append", help="repeatable; bypass ranking")
    run.add_argument("--from-file", default=None, help="file with one nodeid per line")
    run.add_argument("--all", action="store_true", help="run every collected test")
    run.add_argument("--per-test-timeout", type=float, default=None, help="per test ceiling")
    run.add_argument("--json", default=None, help="report path")
    run.add_argument("--markdown", default=None, help="append a markdown summary here")
    run.add_argument("--no-history", action="store_true", help="do not update the history")
    run.set_defaults(func=cmd_run)

    hist = sub.add_parser("history", parents=[common], help="show recorded durations")
    hist.add_argument("--top", type=int, default=20)
    hist.set_defaults(func=cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CollectionError as exc:
        print(f"collection failed:\n{exc}", file=sys.stderr)
        return 3
    except ChangeAnalysisError as exc:
        print(f"change analysis failed: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
