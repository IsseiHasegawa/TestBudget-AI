"""Turn a ranking into a decision about what actually runs.

The ranking is advice. This module owns the decision, and it is deterministic:
given the same ranking, the same measured durations and the same budget, it
always produces the same list. That separation is what keeps a model out of the
execution path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src import config
from src.models import TestCandidate
from src.prioritizer import UNKNOWN_DURATION_S, RankedTest

# Share of the budget the model is allowed to consume before the scheduler
# gives up on it. Measured latency has a long tail, so this is a ceiling rather
# than an expectation.
#
# The defaults are tuned for fast feedback, and at a 60s budget they leave the
# first attempt about 6s against a measured median near 6s. That is why roughly
# half of CI calls fall back. Both are overridable from the environment so a
# run that would rather buy the ranking than the speed can say so without a
# code edit; see TESTBUDGET_AI_MAX_SECONDS in .env.example.
AI_BUDGET_FRACTION = 0.15
AI_MAX_SECONDS = 10.0

# How far down the ranking a skipped test is still worth warning about.
HIGH_PRIORITY_DEPTH = 5


@dataclass
class SkippedTest:
    nodeid: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SelectionEvidence:
    """Facts recorded when the scheduler decides whether to run a test."""

    nodeid: str
    status: str
    decision_code: str
    decision_reason: str
    rank: int | None
    ranking_score: float | None
    ranking_source: str
    ranking_reason: str
    estimated_duration_s: float | None
    estimated_cost_s: float
    remaining_budget_before_s: float | None
    cumulative_cost_before_s: float | None
    cumulative_cost_after_s: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExecutionPlan:
    selected: list[str] = field(default_factory=list)
    skipped: list[SkippedTest] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    decision_records: dict[str, SelectionEvidence] = field(default_factory=dict)
    budget_s: float = 0.0
    ai_elapsed_s: float = 0.0
    available_s: float = 0.0
    estimated_selected_s: float = 0.0
    safety_factor: float = config.DURATION_SAFETY_FACTOR
    ranking_source: str = "unknown"
    fallback_reason: str | None = None
    model_info: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "selected": self.selected,
            "skipped": [item.to_dict() for item in self.skipped],
            "decision_records": {
                nodeid: record.to_dict()
                for nodeid, record in self.decision_records.items()
            },
            "budget_s": self.budget_s,
            "ai_elapsed_s": self.ai_elapsed_s,
            "available_s": round(self.available_s, 3),
            "estimated_selected_s": round(self.estimated_selected_s, 3),
            "safety_factor": self.safety_factor,
            "ranking_source": self.ranking_source,
            "fallback_reason": self.fallback_reason,
            "model": self.model_info,
            "warnings": self.warnings,
        }


def ai_time_allowance(
    budget_s: float,
    fraction: float | None = None,
    cap: float | None = None,
) -> float:
    """How long the model may take before the scheduler stops waiting.

    Tied to the budget rather than fixed, because waiting ten seconds inside a
    five second budget is a contradiction. Resolved per call rather than at
    import, so a .env file loaded later still takes effect.
    """
    config.load_env_file()
    if fraction is None:
        fraction = config.env_float("TESTBUDGET_AI_BUDGET_FRACTION", AI_BUDGET_FRACTION)
    if cap is None:
        cap = config.env_float("TESTBUDGET_AI_MAX_SECONDS", AI_MAX_SECONDS)
    return round(max(0.0, min(cap, budget_s * fraction)), 3)


def _estimate(candidate: TestCandidate | None) -> float:
    if candidate is None or candidate.estimated_duration_s is None:
        return UNKNOWN_DURATION_S
    return candidate.estimated_duration_s


def build_plan(
    ranked: list[RankedTest],
    candidates: list[TestCandidate],
    budget_s: float,
    ai_elapsed_s: float = 0.0,
    must_run: list[str] | None = None,
    safety_factor: float = config.DURATION_SAFETY_FACTOR,
    ranking_source: str = "keyword",
    fallback_reason: str | None = None,
    model_info: dict | None = None,
) -> ExecutionPlan:
    by_nodeid = {candidate.nodeid: candidate for candidate in candidates}
    must_run = [nodeid for nodeid in (must_run or []) if nodeid in by_nodeid]

    plan = ExecutionPlan(
        budget_s=budget_s,
        ai_elapsed_s=round(ai_elapsed_s, 3),
        available_s=budget_s - ai_elapsed_s,
        safety_factor=safety_factor,
        ranking_source=ranking_source,
        fallback_reason=fallback_reason,
        model_info=model_info or {},
    )
    plan.reasons = {item.nodeid: item.reason for item in ranked}

    ranking_positions = {
        item.nodeid: position
        for position, item in enumerate(ranked, start=1)
    }
    ranking_items = {item.nodeid: item for item in ranked}

    def record_decision(
        nodeid: str,
        status: str,
        decision_code: str,
        decision_reason: str,
        cumulative_before: float,
        cumulative_after: float,
    ) -> None:
        item = ranking_items.get(nodeid)
        candidate = by_nodeid.get(nodeid)
        estimated_duration = (
            candidate.estimated_duration_s
            if candidate is not None
            else None
        )

        plan.decision_records[nodeid] = SelectionEvidence(
            nodeid=nodeid,
            status=status,
            decision_code=decision_code,
            decision_reason=decision_reason,
            rank=ranking_positions.get(nodeid),
            ranking_score=item.score if item is not None else None,
            ranking_source=plan.ranking_source,
            ranking_reason=item.reason if item is not None else "",
            estimated_duration_s=estimated_duration,
                 estimated_cost_s=round(
                _estimate(candidate) * safety_factor, 3
            ),
            remaining_budget_before_s=round(
                plan.available_s - cumulative_before, 3
            ),
            cumulative_cost_before_s=round(cumulative_before, 3),
            cumulative_cost_after_s=round(cumulative_after, 3),
        )

    if plan.available_s <= 0:
        plan.warnings.append(
            f"the ranking step consumed the whole budget "
            f"({ai_elapsed_s:.2f}s of {budget_s:.2f}s); no test was started"
        )
        plan.skipped = [SkippedTest(item.nodeid, "no budget left after ranking") for item in ranked]
        for item in ranked:
            record_decision(
                item.nodeid,
                "NOT_SELECTED",
                "no_budget_after_ranking",
                "No test budget remains after ranking.",
                0.0,
                0.0,
            )
        return plan

    # Mandatory tests are reserved before anything competes for the budget.
    ordered = [nodeid for nodeid in must_run]
    ordered.extend(item.nodeid for item in ranked if item.nodeid not in set(must_run))

    mandatory = set(must_run)
    spent = 0.0
    for position, nodeid in enumerate(ordered):
        cost = _estimate(by_nodeid.get(nodeid)) * safety_factor

        if nodeid in mandatory:
            before = spent
            plan.selected.append(nodeid)
            spent += cost
            record_decision(
                nodeid,
                "SELECTED",
                "mandatory",
                "Selected because this test was marked as mandatory.",
                before,
                spent,
            )
            continue

        if spent + cost <= plan.available_s:
            before = spent
            plan.selected.append(nodeid)
            spent += cost
            record_decision(
                nodeid,
                "SELECTED",
                "fits_budget",
                "Selected because its estimated cost fits the remaining budget.",
                before,
                spent,
            )
            continue

        plan.skipped.append(
            SkippedTest(
                nodeid,
                f"needs {cost:.2f}s but only {max(0.0, plan.available_s - spent):.2f}s remain",
            )
        )
        record_decision(
            nodeid,
            "NOT_SELECTED",
            "insufficient_budget",
            "Not selected because its estimated cost exceeds the remaining budget.",
            spent,
            spent,
        )
        rank_position = next(
            (index for index, item in enumerate(ranked) if item.nodeid == nodeid), position
        )
        score = next((item.score for item in ranked if item.nodeid == nodeid), 0.0)
        if rank_position < HIGH_PRIORITY_DEPTH and score > 0:
            plan.warnings.append(
                f"rank {rank_position + 1} test skipped for budget: {nodeid}"
            )

    plan.estimated_selected_s = spent

    if mandatory and spent > plan.available_s:
        plan.warnings.append(
            f"mandatory tests alone need {spent:.2f}s, over the {plan.available_s:.2f}s available"
        )

    if not plan.selected:
        plan.warnings.append("no test fits the budget")

    return plan
