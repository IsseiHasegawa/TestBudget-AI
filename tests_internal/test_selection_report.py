"""Tests for the Markdown selection report."""

import pytest

from src.selection_report import render_markdown


def make_record(
    nodeid,
    *,
    status="SELECTED",
    decision_code="fits_budget",
    decision_reason="Fits the remaining budget.",
    rank=1,
    ranking_score=4.0,
    remaining_budget=20.0,
    cumulative_cost=2.0,
):
    return {
        "nodeid": nodeid,
        "status": status,
        "decision_code": decision_code,
        "decision_reason": decision_reason,
        "rank": rank,
        "ranking_score": ranking_score,
        "ranking_source": "keyword",
        "ranking_reason": "matches changed function",
        "estimated_duration_s": 2.0,
        "estimated_cost_s": 2.6,
        "remaining_budget_before_s": remaining_budget,
        "cumulative_cost_before_s": 0.0,
        "cumulative_cost_after_s": cumulative_cost,
    }


def make_report():
    first = make_record("tests/test_coupon.py::test_first", rank=1)
    second = make_record("tests/test_coupon.py::test_second", rank=2)
    excluded = make_record(
        "tests/test_profile.py::test_unrelated",
        status="NOT_SELECTED",
        decision_code="relevance_filter",
        decision_reason="Keyword score 0.250 is below 1.0.",
        rank=3,
        ranking_score=0.25,
        remaining_budget=None,
        cumulative_cost=None,
    )

    return {
        "totals": {"collected": 3, "selected": 2},
        "budget": {
            "budget_s": 20.0,
            "estimated_selected_s": 5.2,
            "actual_run_s": 4.0,
        },
        "ranking": {"source": "keyword", "fallback_reason": None},
        "change": {
            "files": [{"path": "demo_project/app/coupon.py"}],
        },
        # Deliberately different from execution order.
        "selection_evidence": [excluded, second, first],
        "results": [
            {"nodeid": first["nodeid"]},
            {"nodeid": second["nodeid"]},
        ],
        "coverage_caveat": (
            "A selective run does not certify the full suite."
        ),
    }


def test_markdown_shows_execution_order_and_selection_evidence():
    markdown = render_markdown(make_report())

    assert markdown.index("### `tests/test_coupon.py::test_first`") < (
        markdown.index("### `tests/test_coupon.py::test_second`")
    )
    assert "**Selected:** 2/3" in markdown
    assert "**Ranking reason:** matches changed function" in markdown
    assert "**Remaining budget before decision:** 20.00s" in markdown
    assert "**Cumulative cost after decision:** 2.00s" in markdown
    assert "demo_project/app/coupon.py" in markdown


def test_markdown_distinguishes_relevance_exclusion_from_budget():
    markdown = render_markdown(make_report())

    assert (
        "| `tests/test_profile.py::test_unrelated` "
        "| relevance_filter | Keyword score 0.250 is below 1.0. "
        "| 2.60s |"
    ) in markdown
    assert (
        "A relevance-filter exclusion is not a budget rejection."
        in markdown
    )


def test_markdown_rejects_missing_or_incomplete_evidence():
    report = make_report()
    report["selection_evidence"] = []

    with pytest.raises(ValueError, match="no selection_evidence"):
        render_markdown(report)

    report = make_report()
    report["selection_evidence"].pop()

    with pytest.raises(ValueError, match="does not match collected tests"):
        render_markdown(report)


def test_markdown_displays_static_call_path_without_claiming_execution():
    report = make_report()
    report["selection_evidence"][2]["code_evidence"] = [{
        "type": "static_call_path",
        "changed_file": "demo_project/app/coupon.py",
        "changed_function": "_round_percent",
        "call_path": [
            "tests.test_coupon.test_first",
            "app.coupon.discount_for",
            "app.coupon._round_percent",
        ],
        "execution_verified": False,
        "source_snapshot": "working_tree",
    }]

    markdown = render_markdown(report)

    assert "Static call path (execution not verified)" in markdown
    assert (
        "`tests.test_coupon.test_first` → "
        "`app.coupon.discount_for` → "
        "`app.coupon._round_percent`"
    ) in markdown
    assert "demo_project/app/coupon.py" in markdown
    assert "working_tree" in markdown


def test_markdown_displays_ai_explanation_separately():
    report = make_report()
    report["selection_evidence"][2]["ai_explanation"] = {
        "type": "ai_inferred_relevance",
        "source": "nemotron",
        "explanation": "The rounding change may affect the checkout total.",
        "execution_verified": False,
    }

    markdown = render_markdown(report)

    assert "**AI-inferred relevance (not verified):**" in markdown
    assert "The rounding change may affect the checkout total." in markdown
    assert "**Static call path (execution not verified):**" not in markdown


def test_markdown_labels_synthetic_demo_report():
    report = make_report()
    report["demo_only"] = True
    report["demo_note"] = "Synthetic selection plan. No tests were executed."

    markdown = render_markdown(report)

    assert "**DEMO ONLY — NOT AN ACTUAL TEST RUN.**" in markdown
    assert "Synthetic selection plan. No tests were executed." in markdown
