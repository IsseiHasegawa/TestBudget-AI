"""Run every scenario against every strategy and record what each one caught.

Selection is deterministic given a ranking, a set of measured durations and a
budget, so the plan is computed rather than executed. What each scenario breaks
comes from actually running the suite. Those two facts together decide recall
exactly, with no execution of the selected subset needed.

Time to first failure is therefore an estimate built from measured durations,
and is labelled as one. Everything else in the output is measured.

    python -m evaluation.benchmark --budget 60
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from evaluation.harness import GroundTruth, applied, ground_truth, require_clean_tree
from evaluation.scenarios import SCENARIOS, Scenario
from src import config
from src.change_analyzer import collect_working_tree_changes
from src.history import DurationHistory
from src.model_response import ResponseRejected
from src.nemotron_client import is_configured, rank_with_model
from src.prioritizer import KEYWORD, NEMOTRON, STRATEGIES, from_model_order, rank
from src.scheduler import ai_time_allowance, build_plan
from src.test_collector import collect_tests

DEFAULT_STRATEGIES = ("file_rule", "duration", "history", KEYWORD, NEMOTRON)
RESULTS_DIR = config.ROOT / "evaluation" / "results"


@dataclass
class Measurement:
    scenario: str
    shape: str
    strategy: str
    ranking_source: str
    fallback_reason: str | None = None
    model_attempts: int = 0
    model_calls_that_answered: int = 0
    ai_elapsed_s: float = 0.0
    collected: int = 0
    selected: int = 0
    estimated_cost_s: float = 0.0
    faults_total: int = 0
    faults_found: int = 0
    missed: list[str] = field(default_factory=list)
    first_failure_rank: int | None = None
    estimated_time_to_first_failure_s: float | None = None

    @property
    def recall(self) -> float | None:
        if not self.faults_total:
            return None
        return self.faults_found / self.faults_total


def _measure(plan, candidates, truth: GroundTruth, ai_elapsed_s: float) -> dict:
    estimates = {c.nodeid: (c.estimated_duration_s or 1.0) for c in candidates}
    found, rank_of_first, elapsed_at_first = 0, None, None
    running = ai_elapsed_s

    for position, nodeid in enumerate(plan.selected, start=1):
        running += estimates.get(nodeid, 1.0)
        if nodeid in truth.failing:
            found += 1
            if rank_of_first is None:
                rank_of_first, elapsed_at_first = position, round(running, 2)

    return {
        "faults_total": len(truth.failing),
        "faults_found": found,
        "missed": sorted(truth.failing - set(plan.selected)),
        "first_failure_rank": rank_of_first,
        "estimated_time_to_first_failure_s": elapsed_at_first,
    }


def _rank_with_retries(candidates, changes, allowance, fallback, retries):
    """Call the model, retrying with a fresh allowance each time.

    CI gets one allowance and falls back. Retrying here is how the model's
    ranking quality gets characterised at all, given how often a single call
    does not land. The attempt counts are reported so the two are not confused.
    """
    attempts, elapsed = 0, 0.0
    last: ResponseRejected | None = None
    for _ in range(max(1, retries)):
        attempts += 1
        started = time.perf_counter()
        try:
            result = rank_with_model(candidates, changes, allowance, fallback)
        except ResponseRejected as exc:
            elapsed += time.perf_counter() - started
            last = exc
            continue
        # Charge only the call that answered. CI never pays for the retries
        # below: it spends one allowance and falls back. Billing this arm for
        # time production would not spend makes it look worse than it is.
        return result, attempts, round(result.latency_s, 3), None
    return None, attempts, round(min(elapsed, allowance), 3), last


def run_scenario(scenario: Scenario, strategies, budget_s: float, retries: int) -> list[Measurement]:
    with applied(scenario):
        truth = ground_truth()
        candidates = collect_tests(history=DurationHistory.load())
        changes = collect_working_tree_changes()
        fallback_ranked = rank(KEYWORD, candidates, changes)

        rows = []
        for strategy in strategies:
            if strategy != NEMOTRON:
                ranked = rank(strategy, candidates, changes)
                source, reason, ai_elapsed, attempts, answered = strategy, None, 0.0, 0, 0
            else:
                allowance = ai_time_allowance(budget_s)
                result, attempts, ai_elapsed, failure = _rank_with_retries(
                    candidates, changes, allowance,
                    [item.nodeid for item in fallback_ranked], retries,
                )
                if result is None:
                    ranked, source, reason, answered = fallback_ranked, KEYWORD, failure.reason, 0
                else:
                    ranked = from_model_order(
                        result.order, result.reasons, result.completed_by_fallback
                    )
                    source, reason, answered = NEMOTRON, None, 1

            plan = build_plan(
                ranked, candidates, budget_s=budget_s,
                ai_elapsed_s=ai_elapsed, ranking_source=source, fallback_reason=reason,
            )
            rows.append(
                Measurement(
                    scenario=scenario.name,
                    shape=scenario.shape,
                    strategy=strategy,
                    ranking_source=source,
                    fallback_reason=reason,
                    model_attempts=attempts,
                    model_calls_that_answered=answered,
                    ai_elapsed_s=round(ai_elapsed, 3),
                    collected=len(candidates),
                    selected=len(plan.selected),
                    estimated_cost_s=round(plan.estimated_selected_s, 2),
                    **_measure(plan, candidates, truth, ai_elapsed),
                )
            )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmark", description=__doc__)
    parser.add_argument("--budget", type=float, default=60.0)
    parser.add_argument("--strategies", default=",".join(DEFAULT_STRATEGIES))
    parser.add_argument("--scenario", action="append", help="repeatable; default is all")
    parser.add_argument("--model-retries", type=int, default=3)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    require_clean_tree()

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    unknown = [s for s in strategies if s not in {*STRATEGIES, NEMOTRON}]
    if unknown:
        print(f"unknown strategies: {unknown}", file=sys.stderr)
        return 2
    if NEMOTRON in strategies and not is_configured():
        print("NVIDIA_API_KEY is not set; the nemotron arm will record fallbacks only")

    chosen = [s for s in SCENARIOS if not args.scenario or s.name in args.scenario]
    if not chosen:
        print("no scenario matched", file=sys.stderr)
        return 2

    started = time.perf_counter()
    rows: list[Measurement] = []
    for index, scenario in enumerate(chosen, start=1):
        print(f"[{index}/{len(chosen)}] {scenario.name}", flush=True)
        rows.extend(run_scenario(scenario, strategies, args.budget, args.model_retries))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "budget_s": args.budget,
        "model_retries": args.model_retries,
        "wall_time_s": round(time.perf_counter() - started, 1),
        "note": (
            "Recall and missed faults are exact. Time to first failure is estimated "
            "from measured durations rather than observed, since selection is "
            "deterministic and re-executing adds nothing to it."
        ),
        "measurements": [asdict(row) for row in rows],
    }
    path = Path(args.out) if args.out else RESULTS_DIR / "benchmark.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(rows)} measurements in {payload['wall_time_s']}s -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
