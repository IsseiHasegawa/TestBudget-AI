"""Tests for the non-AI ranking and the budget scheduler."""

import argparse
import pytest

from src.change_analyzer import ChangedFile, ChangeSet
from src.models import TestCandidate
from src.prioritizer import FILE_RULE, KEYWORD, rank
from main import _ranking_allowance
from src.scheduler import ai_time_allowance, build_plan


def candidate(nodeid, file, summary="", duration=0.1, last_outcome=None):
    return TestCandidate(
        nodeid=nodeid,
        name=nodeid.split("::")[-1],
        file=file,
        summary=summary,
        estimated_duration_s=duration,
        last_outcome=last_outcome,
        run_count=1 if last_outcome else 0,
    )


@pytest.fixture
def coupon_change():
    """A change confined to coupon.py, touching the rounding helper."""
    return ChangeSet(
        base="a",
        head="b",
        files=[
            ChangedFile(
                path="demo_project/app/coupon.py",
                status="m",
                added_lines=3,
                removed_lines=1,
                symbols=["_round_percent", "discount_for"],
            )
        ],
    )


@pytest.fixture
def suite():
    return [
        candidate(
            "demo_project/tests/test_coupon.py::test_percent_rounding",
            "demo_project/tests/test_coupon.py",
            "ten percent of 999 truncates to 99",
            duration=0.25,
        ),
        candidate(
            "demo_project/tests/test_checkout.py::test_percent_coupon_changes_total",
            "demo_project/tests/test_checkout.py",
            "a discount computed in coupon.py flows into the total",
            duration=0.30,
        ),
        candidate(
            "demo_project/tests/test_profile.py::test_avatar_upload",
            "demo_project/tests/test_profile.py",
            "avatar upload round trip",
            duration=1.50,
        ),
        candidate(
            "demo_project/tests/test_cart.py::test_add_item",
            "demo_project/tests/test_cart.py",
            "a product not yet in the cart becomes a new line",
            duration=0.01,
        ),
    ]


def test_file_rule_only_sees_the_matching_test_file(suite, coupon_change):
    """The baseline is meant to miss indirect coupling, and must keep missing it."""
    ranked = rank(FILE_RULE, suite, coupon_change)
    scored = {item.nodeid: item.score for item in ranked}

    assert scored["demo_project/tests/test_coupon.py::test_percent_rounding"] == 1.0
    assert scored["demo_project/tests/test_checkout.py::test_percent_coupon_changes_total"] == 0.0
    assert ranked[0].nodeid.endswith("test_coupon.py::test_percent_rounding")


def test_keyword_fallback_reaches_the_indirectly_affected_test(suite, coupon_change):
    ranked = rank(KEYWORD, suite, coupon_change)
    order = [item.nodeid for item in ranked]

    assert order[0].endswith("test_coupon.py::test_percent_rounding")
    assert order[1].endswith("test_checkout.py::test_percent_coupon_changes_total")


def test_keyword_fallback_has_a_known_false_positive(suite, coupon_change):
    """Token overlap cannot tell "round trip" apart from "_round_percent".

    This is the weakness the model is supposed to beat, so it is pinned here
    rather than tuned away. If the ranking ever stops making this mistake, the
    evaluation needs to know.
    """
    ranked = {item.nodeid: item for item in rank(KEYWORD, suite, coupon_change)}

    avatar = ranked["demo_project/tests/test_profile.py::test_avatar_upload"]
    cart = ranked["demo_project/tests/test_cart.py::test_add_item"]

    assert "round" in avatar.reason
    assert avatar.score > cart.score
    # It is still nowhere near the genuinely related tests.
    assert avatar.score < ranked["demo_project/tests/test_coupon.py::test_percent_rounding"].score


def test_ranking_is_deterministic(suite, coupon_change):
    first = [item.nodeid for item in rank(KEYWORD, suite, coupon_change)]
    second = [item.nodeid for item in rank(KEYWORD, suite, coupon_change)]

    assert first == second


def test_unknown_strategy_is_rejected(suite, coupon_change):
    with pytest.raises(ValueError):
        rank("vibes", suite, coupon_change)


def test_plan_stops_adding_tests_once_the_budget_is_full(suite, coupon_change):
    ranked = rank(KEYWORD, suite, coupon_change)

    plan = build_plan(ranked, suite, budget_s=1.0, safety_factor=1.0)

    assert plan.selected
    assert plan.estimated_selected_s <= 1.0
    assert "demo_project/tests/test_profile.py::test_avatar_upload" not in plan.selected
    skipped = {item.nodeid for item in plan.skipped}
    assert "demo_project/tests/test_profile.py::test_avatar_upload" in skipped


def test_plan_reserves_mandatory_tests_before_the_budget_is_spent(suite, coupon_change):
    ranked = rank(KEYWORD, suite, coupon_change)
    smoke = "demo_project/tests/test_profile.py::test_avatar_upload"

    plan = build_plan(ranked, suite, budget_s=1.0, must_run=[smoke], safety_factor=1.0)

    assert plan.selected[0] == smoke
    assert any("mandatory" in warning for warning in plan.warnings)


def test_plan_warns_when_ranking_ate_the_whole_budget(suite, coupon_change):
    ranked = rank(KEYWORD, suite, coupon_change)

    plan = build_plan(ranked, suite, budget_s=2.0, ai_elapsed_s=2.5)

    assert plan.selected == []
    assert len(plan.skipped) == len(suite)
    assert any("whole budget" in warning for warning in plan.warnings)


def test_plan_applies_the_safety_factor(suite, coupon_change):
    ranked = rank(KEYWORD, suite, coupon_change)

    tight = build_plan(ranked, suite, budget_s=0.56, safety_factor=1.0)
    padded = build_plan(ranked, suite, budget_s=0.56, safety_factor=1.3)

    assert len(padded.selected) < len(tight.selected)


def test_model_time_allowance_scales_with_the_budget():
    assert ai_time_allowance(60.0) == 9.0
    assert ai_time_allowance(20.0) == 3.0
    # A large budget still stops at the cap rather than waiting on a long tail.
    assert ai_time_allowance(600.0) == 10.0
    assert ai_time_allowance(0.0) == 0.0


def test_model_time_allowance_honours_the_environment(monkeypatch):
    # Raising the cap is how a run buys a better chance the model answers.
    monkeypatch.setenv("TESTBUDGET_AI_MAX_SECONDS", "25")
    assert ai_time_allowance(600.0) == 25.0
    # The fraction still binds below the cap.
    assert ai_time_allowance(60.0) == 9.0

    monkeypatch.setenv("TESTBUDGET_AI_BUDGET_FRACTION", "0.5")
    assert ai_time_allowance(60.0) == 25.0


def test_model_time_allowance_ignores_an_unusable_override(monkeypatch):
    # A typo in a CI variable falls back to the default instead of raising.
    monkeypatch.setenv("TESTBUDGET_AI_MAX_SECONDS", "twenty")
    assert ai_time_allowance(600.0) == 10.0

    monkeypatch.setenv("TESTBUDGET_AI_MAX_SECONDS", "")
    assert ai_time_allowance(600.0) == 10.0


def test_explicit_ranking_budget_is_taken_literally():
    """The share-of-budget formula must not cap an explicit request.

    At a 90s budget the 15% share is 13.5s, so folding --ranking-budget 20
    through the formula would silently hand back 13.5s: the same trap the flag
    exists to escape.
    """
    args = argparse.Namespace(budget=90.0, ranking_budget=20.0)
    assert _ranking_allowance(args) == 20.0

    # Without the flag the formula still applies.
    assert _ranking_allowance(argparse.Namespace(budget=90.0, ranking_budget=None)) == 10.0


def test_explicit_ranking_budget_cannot_exceed_the_total():
    args = argparse.Namespace(budget=8.0, ranking_budget=20.0)
    assert _ranking_allowance(args) == 8.0

    args = argparse.Namespace(budget=60.0, ranking_budget=-5.0)
    assert _ranking_allowance(args) == 0.0
