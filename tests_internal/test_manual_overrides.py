"""Tests for manual test-selection overrides."""

from src.models import TestCandidate
from src.prioritizer import RankedTest
from src.scheduler import build_plan


def make_inputs():
    names = ["test_a", "test_b", "test_c"]
    nodeids = [f"tests/test_demo.py::{name}" for name in names]

    candidates = [
        TestCandidate(
            nodeid=nodeid,
            name=name,
            file="tests/test_demo.py",
            estimated_duration_s=5.0,
        )
        for nodeid, name in zip(nodeids, names)
    ]
    ranked = [
        RankedTest(nodeid, 1.0, "normal ranking", "keyword")
        for nodeid in nodeids
    ]
    return nodeids, candidates, ranked


def test_include_gets_priority_over_normal_ranking():
    nodeids, candidates, ranked = make_inputs()

    plan = build_plan(
        ranked, candidates,
        budget_s=6.0,
        safety_factor=1.0,
        manual_overrides={nodeids[2]: "INCLUDE"},
    )

    assert plan.selected == [nodeids[2]]
    assert plan.decision_records[nodeids[2]].decision_code == "manual_include"


def test_exclude_is_not_selected_and_has_explicit_reason():
    nodeids, candidates, ranked = make_inputs()

    plan = build_plan(
        ranked, candidates,
        budget_s=15.0,
        safety_factor=1.0,
        manual_overrides={nodeids[0]: "EXCLUDE"},
    )

    assert nodeids[0] not in plan.selected
    assert plan.selected == nodeids[1:]
    assert plan.decision_records[nodeids[0]].decision_code == "manual_exclude"


def test_include_does_not_exceed_time_budget():
    nodeids, candidates, ranked = make_inputs()

    plan = build_plan(
        ranked, candidates,
        budget_s=4.0,
        safety_factor=1.0,
        manual_overrides={nodeids[2]: "INCLUDE"},
    )

    assert plan.selected == []
    assert plan.decision_records[nodeids[2]].decision_code == (
        "manual_include_insufficient_budget"
    )
    assert plan.estimated_selected_s <= plan.available_s


def test_cannot_exclude_mandatory_test():
    import pytest

    nodeids, candidates, ranked = make_inputs()

    with pytest.raises(ValueError, match="Cannot exclude mandatory"):
        build_plan(
            ranked, candidates,
            budget_s=20.0,
            must_run=[nodeids[0]],
            manual_overrides={nodeids[0]: "EXCLUDE"},
        )


def test_rejects_unknown_test():
    import pytest

    _, candidates, ranked = make_inputs()

    with pytest.raises(ValueError, match="Unknown test"):
        build_plan(
            ranked, candidates,
            budget_s=20.0,
            manual_overrides={"tests/test_missing.py::test_unknown": "INCLUDE"},
        )


def test_rejects_invalid_override_mode():
    import pytest

    nodeids, candidates, ranked = make_inputs()

    with pytest.raises(ValueError, match="Invalid manual override"):
        build_plan(
            ranked, candidates,
            budget_s=20.0,
            manual_overrides={nodeids[0]: "ALWAYS"},
        )


def test_zero_budget_records_manual_include_reason():
    nodeids, candidates, ranked = make_inputs()

    plan = build_plan(
        ranked, candidates,
        budget_s=0.0,
        manual_overrides={nodeids[0]: "INCLUDE"},
    )

    assert plan.selected == []
    assert plan.decision_records[nodeids[0]].decision_code == (
        "manual_include_insufficient_budget"
    )


def test_zero_budget_records_manual_exclude_reason():
    nodeids, candidates, ranked = make_inputs()

    plan = build_plan(
        ranked, candidates,
        budget_s=0.0,
        manual_overrides={nodeids[0]: "EXCLUDE"},
    )

    assert plan.selected == []
    assert plan.decision_records[nodeids[0]].decision_code == (
        "manual_exclude"
    )


def test_manual_decisions_appear_in_json_and_markdown():
    from src.models import RunOutcome
    from src.reporter import build_report
    from src.selection_report import render_markdown

    nodeids, candidates, ranked = make_inputs()

    plan = build_plan(
        ranked,
        candidates,
        budget_s=10.0,
        safety_factor=1.0,
        manual_overrides={
            nodeids[2]: "INCLUDE",
            nodeids[0]: "EXCLUDE",
        },
    )

    report = build_report(
        RunOutcome(selected=list(plan.selected)),
        candidates,
        plan,
    )

    records = {
        record["nodeid"]: record
        for record in report["selection_evidence"]
    }

    assert records[nodeids[2]]["status"] == "SELECTED"
    assert records[nodeids[2]]["decision_code"] == "manual_include"

    assert records[nodeids[0]]["status"] == "NOT_SELECTED"
    assert records[nodeids[0]]["decision_code"] == "manual_exclude"

    markdown = render_markdown(report)

    assert "Selected with priority because the developer manually included" in markdown
    assert "Not selected because the developer manually excluded" in markdown
