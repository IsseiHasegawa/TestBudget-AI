"""Tests for the TestBudget AI tooling itself.

They run against a throwaway pytest project so that the failure, error and
skip paths are covered without making the demo suite red.
"""

import pytest

from src.history import DurationHistory
from src.models import TestResult
from src.reporter import build_report
from src.test_collector import collect_tests, validate_nodeids
from src.test_runner import RunnerError, run_tests

MINI_SUITE = '''
import pytest


def test_ok():
    """passes every time"""
    assert True


def test_fails():
    """fails every time"""
    assert 1 == 2


@pytest.fixture
def broken():
    raise RuntimeError("setup boom")


def test_errors(broken):
    """errors during setup"""
    assert True


@pytest.mark.skip(reason="not today")
def test_skipped():
    """always skipped"""
    assert True
'''


@pytest.fixture
def mini_project(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_mini.py").write_text(MINI_SUITE, encoding="utf-8")
    return tmp_path


def test_collect_reads_nodeids_summaries_and_markers():
    candidates = collect_tests()
    by_nodeid = {candidate.nodeid: candidate for candidate in candidates}

    coupon = by_nodeid["demo_project/tests/test_coupon.py::test_percent_discount_truncates_partial_cent"]
    assert coupon.summary.startswith("Ten percent of 999")
    assert coupon.file == "demo_project/tests/test_coupon.py"

    slow = by_nodeid["demo_project/tests/test_profile.py::test_avatar_upload_accepts_png"]
    assert "slow" in slow.markers


def test_validate_nodeids_drops_unknown_ids_and_duplicates():
    candidates = collect_tests()
    real = candidates[0].nodeid

    valid, unknown = validate_nodeids([real, real, "nope.py::test_x", "; rm -rf /"], candidates)

    assert valid == [real]
    assert unknown == ["nope.py::test_x", "; rm -rf /"]


def test_runner_records_each_outcome_kind(mini_project):
    nodeids = [
        "suite/test_mini.py::test_ok",
        "suite/test_mini.py::test_fails",
        "suite/test_mini.py::test_errors",
        "suite/test_mini.py::test_skipped",
    ]

    outcome = run_tests(nodeids, root=mini_project)

    assert [result.outcome for result in outcome.results] == ["passed", "failed", "error", "skipped"]
    assert len(outcome.failures()) == 2
    assert "setup boom" in outcome.by_nodeid()["suite/test_mini.py::test_errors"].message


def test_runner_preserves_requested_order(mini_project):
    nodeids = ["suite/test_mini.py::test_skipped", "suite/test_mini.py::test_ok"]

    outcome = run_tests(nodeids, root=mini_project)

    assert [result.nodeid for result in outcome.results] == nodeids


def test_runner_marks_everything_timed_out_when_the_budget_expires(mini_project):
    outcome = run_tests(["suite/test_mini.py::test_ok"], root=mini_project, timeout_s=0.001)

    assert outcome.timed_out is True
    assert outcome.results[0].outcome == "timeout"


def test_runner_refuses_a_non_list_of_strings():
    with pytest.raises(RunnerError):
        run_tests(["ok", 3])


def test_empty_selection_runs_nothing():
    outcome = run_tests([])

    assert outcome.results == []
    assert outcome.wall_time_s == 0.0


def test_history_uses_the_median_and_counts_failures(tmp_path):
    history = DurationHistory(tmp_path / "history.json")

    history.record([TestResult("a::b", "passed", 1.0)])
    history.record([TestResult("a::b", "passed", 9.0)])
    history.record([TestResult("a::b", "failed", 1.2)])

    entry = history.stats("a::b")
    assert entry.estimate() == 1.2
    assert entry.run_count == 3
    assert entry.fail_count == 1

    history.save()
    assert DurationHistory.load(tmp_path / "history.json").estimate("a::b") == 1.2


def test_history_ignores_tests_that_never_finished(tmp_path):
    history = DurationHistory(tmp_path / "history.json")

    history.record([TestResult("a::b", "timeout", 0.0), TestResult("a::c", "not_run", 0.0)])

    assert history.tests == {}


def test_report_names_the_tests_that_were_not_run():
    candidates = collect_tests()
    selected = [candidates[0].nodeid]
    outcome = run_tests(selected)

    report = build_report(outcome, candidates, selection_mode="manual", budget_s=3.0)

    assert report["totals"]["selected"] == 1
    assert report["totals"]["unselected"] == len(candidates) - 1
    assert candidates[1].nodeid in report["unselected"]
    assert "does not certify" in report["coverage_caveat"]
