"""Tests for selection evidence recorded by the scheduler."""

import json
from types import SimpleNamespace

from src.prioritizer import RankedTest
from src.scheduler import build_plan


def make_inputs():
    candidates = [
        SimpleNamespace(nodeid="tests/test_a.py::test_fast", estimated_duration_s=2.0),
        SimpleNamespace(nodeid="tests/test_b.py::test_slow", estimated_duration_s=8.0),
    ]
    ranked = [
        RankedTest(candidates[0].nodeid, 4.0, "matches changed function", "keyword"),
        RankedTest(candidates[1].nodeid, 1.0, "weak relevance signal", "keyword"),
    ]
    return candidates, ranked


def test_records_selected_and_budget_excluded_tests():
    candidates, ranked = make_inputs()

    plan = build_plan(
        ranked,
        candidates,
        budget_s=5.0,
        safety_factor=1.0,
        ranking_source="keyword",
    )

    fast = plan.decision_records[candidates[0].nodeid]
    slow = plan.decision_records[candidates[1].nodeid]

    assert plan.selected == [candidates[0].nodeid]

    assert fast.status == "SELECTED"
    assert fast.decision_code == "fits_budget"
    assert fast.rank == 1
    assert fast.ranking_score == 4.0
    assert fast.ranking_source == "keyword"
    assert fast.ranking_reason == "matches changed function"
    assert fast.estimated_duration_s == 2.0
    assert fast.estimated_cost_s == 2.0
    assert fast.remaining_budget_before_s == 5.0
    assert fast.cumulative_cost_before_s == 0.0
    assert fast.cumulative_cost_after_s == 2.0

    assert slow.status == "NOT_SELECTED"
    assert slow.decision_code == "insufficient_budget"
    assert slow.rank == 2
    assert slow.estimated_cost_s == 8.0
    assert slow.remaining_budget_before_s == 3.0
    assert slow.cumulative_cost_before_s == 2.0
    assert slow.cumulative_cost_after_s == 2.0


def test_records_mandatory_selection():
    candidates, ranked = make_inputs()

    plan = build_plan(
        ranked,
        candidates,
        budget_s=5.0,
        safety_factor=1.0,
        must_run=[candidates[1].nodeid],
    )

    mandatory = plan.decision_records[candidates[1].nodeid]

    assert plan.selected == [candidates[1].nodeid]
    assert mandatory.status == "SELECTED"
    assert mandatory.decision_code == "mandatory"
    assert mandatory.remaining_budget_before_s == 5.0
    assert mandatory.cumulative_cost_after_s == 8.0
    assert any("mandatory tests alone" in warning for warning in plan.warnings)


def test_records_when_ranking_consumes_the_budget():
    candidates, ranked = make_inputs()

    plan = build_plan(
        ranked,
        candidates,
        budget_s=5.0,
        ai_elapsed_s=5.5,
        safety_factor=1.0,
    )

    assert plan.selected == []
    assert len(plan.decision_records) == 2
    assert all(
        record.status == "NOT_SELECTED"
        and record.decision_code == "no_budget_after_ranking"
        for record in plan.decision_records.values()
    )

    # The evidence must be serializable for the future JSON report.
    json.dumps(plan.to_dict())
