"""TestBudget AI command line entry point.

Phase 1 covers collection, explicit selection and reporting. The Nemotron
ranking (Phase 2) and the budget scheduler (Phase 3) plug into the same
collect -> select -> run -> report pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import config
from src.history import DurationHistory
from src.models import TestCandidate
from src.reporter import build_report, render_console, write_report
from src.test_collector import CollectionError, collect_tests, validate_nodeids
from src.test_runner import run_tests


def _load_history(path: str | None) -> DurationHistory:
    return DurationHistory.load(Path(path) if path else None)


def _collect(args: argparse.Namespace) -> list[TestCandidate]:
    return collect_tests(target=args.target, history=_load_history(args.history))


def cmd_collect(args: argparse.Namespace) -> int:
    candidates = _collect(args)
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

    print(
        f"\n{known}/{len(candidates)} test(s) have measured durations "
        f"(estimated suite time {total:.2f}s)"
    )
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


def _requested_nodeids(args: argparse.Namespace) -> list[str]:
    requested = list(args.nodeid or [])
    if args.from_file:
        text = Path(args.from_file).read_text(encoding="utf-8")
        requested.extend(line.strip() for line in text.splitlines() if line.strip())
    return requested


def cmd_run(args: argparse.Namespace) -> int:
    history = _load_history(args.history)
    candidates = collect_tests(target=args.target, history=history)
    if not candidates:
        print(f"no tests collected under {args.target}", file=sys.stderr)
        return 1

    if args.all:
        selected = [candidate.nodeid for candidate in candidates]
        mode = "all"
    else:
        requested = _requested_nodeids(args)
        if not requested:
            print("nothing selected: pass --nodeid, --from-file or --all", file=sys.stderr)
            return 2
        selected, unknown = validate_nodeids(requested, candidates)
        mode = "manual"
        for nodeid in unknown:
            print(f"discarded unknown nodeid: {nodeid}", file=sys.stderr)
        if not selected:
            print("no valid nodeid left after validation", file=sys.stderr)
            return 2

    outcome = run_tests(selected, timeout_s=args.timeout)
    report = build_report(outcome, candidates, selection_mode=mode, budget_s=args.timeout)
    print(render_console(report))

    if not args.no_history:
        history.record(outcome.results)
        print(f"history updated: {history.save()}")

    path = write_report(report, Path(args.json) if args.json else None)
    print(f"report written: {path}")

    return 1 if outcome.failures() else 0


def cmd_history(args: argparse.Namespace) -> int:
    history = _load_history(args.history)
    if not history.tests:
        print("no history recorded yet; run `python main.py run --all`")
        return 0

    rows = sorted(
        history.tests.items(),
        key=lambda item: item[1].estimate() or 0.0,
        reverse=True,
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

    collect = sub.add_parser("collect", parents=[common], help="list collected nodeids with durations")
    collect.add_argument("--json", default=None, help="also write the candidates to this path")
    collect.set_defaults(func=cmd_collect)

    run = sub.add_parser("run", parents=[common], help="run a specific set of nodeids")
    run.add_argument("--nodeid", action="append", help="repeatable; a nodeid to run")
    run.add_argument("--from-file", default=None, help="file with one nodeid per line")
    run.add_argument("--all", action="store_true", help="run every collected test")
    run.add_argument("--timeout", type=float, default=None, help="wall clock ceiling in seconds")
    run.add_argument("--json", default=None, help="report path (default artifacts/run-<ts>.json)")
    run.add_argument("--no-history", action="store_true", help="do not update the duration history")
    run.set_defaults(func=cmd_run)

    hist = sub.add_parser("history", parents=[common], help="show recorded durations")
    hist.add_argument("--top", type=int, default=20, help="how many slowest tests to show")
    hist.set_defaults(func=cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CollectionError as exc:
        print(f"collection failed:\n{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
