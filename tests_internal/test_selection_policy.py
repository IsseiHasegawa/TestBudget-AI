"""Tests for the experimental relevance selection policy."""

from types import SimpleNamespace

import main
from src.prioritizer import KEYWORD, RankedTest


def make_candidate(nodeid):
    return SimpleNamespace(
        nodeid=nodeid,
        estimated_duration_s=1.0,
    )


def make_args(policy="relevant", must_run=None):
    return SimpleNamespace(
        budget=30.0,
        selection_policy=policy,
        must_run=must_run or [],
        must_run_file=None,
    )


def make_plan(monkeypatch, policy, keyword_scores, model_order, must_run=None):
    """Test the policy without calling Nemotron or running pytest tests."""
    candidates = [make_candidate(nodeid) for nodeid in model_order]

    model_ranking = [
        RankedTest(nodeid, float(len(model_order) - index),
                   "model ranking", "nemotron")
        for index, nodeid in enumerate(model_order)
    ]

    keyword_ranking = [
        RankedTest(nodeid, keyword_scores[nodeid],
                   "keyword relevance", KEYWORD)
        for nodeid in model_order
    ]

    monkeypatch.setattr(main, "_changes", lambda args: object())

    monkeypatch.setattr(
        main,
        "_rank",
        lambda args, candidates, changes:
            (model_ranking, "nemotron", None, 0.0, {}),
    )

    monkeypatch.setattr(
        main,
        "rank",
        lambda strategy, candidates, changes: keyword_ranking,
    )

    plan, _ = main._plan_for(
        make_args(policy=policy, must_run=must_run),
        candidates,
    )
    return plan


def test_relevant_policy_excludes_weak_matches(monkeypatch):
    """Weak matches must not be selected merely because budget remains."""
    unrelated = "tests/test_profile.py::test_avatar"
    indirect = "tests/test_order.py::test_total"
    direct = "tests/test_discount.py::test_rounding"

    plan = make_plan(
        monkeypatch,
        policy="relevant",
        keyword_scores={
            unrelated: 0.25,
            indirect: 1.25,
            direct: 4.0,
        },
        model_order=[unrelated, indirect, direct],
    )

    assert plan.selected == [indirect, direct]
    assert unrelated not in plan.selected
    assert any(
        item.nodeid == unrelated
        and "excluded by experimental relevance policy" in item.reason
        for item in plan.skipped
    )


def test_relevant_policy_preserves_must_run(monkeypatch):
    """A mandatory test must survive the relevance filter."""
    mandatory = "tests/test_profile.py::test_avatar"
    related = "tests/test_discount.py::test_rounding"

    plan = make_plan(
        monkeypatch,
        policy="relevant",
        keyword_scores={mandatory: 0.25, related: 4.0},
        model_order=[related, mandatory],
        must_run=[mandatory],
    )

    assert plan.selected == [mandatory, related]


def test_relevant_policy_uses_original_plan_if_no_strong_match(monkeypatch):
    """If nothing qualifies, retain the previous budget-filling behavior."""
    first = "tests/test_a.py::test_a"
    second = "tests/test_b.py::test_b"

    plan = make_plan(
        monkeypatch,
        policy="relevant",
        keyword_scores={first: 0.25, second: 0.0},
        model_order=[first, second],
    )

    assert plan.selected == [first, second]
    assert any(
        "found no strong matches" in warning
        for warning in plan.warnings
    )
