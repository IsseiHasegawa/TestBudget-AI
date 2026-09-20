"""CLI checks for manual selection overrides."""

import pytest

import main


@pytest.mark.parametrize(
    "extra_args",
    [
        ["--all"],
        ["--nodeid", "tests/test_demo.py::test_a"],
        ["--from-file", "requested-tests.txt"],
    ],
)
def test_run_rejects_overrides_with_direct_execution(
    extra_args, capsys
):
    exit_code = main.main([
        "run",
        *extra_args,
        "--exclude",
        "tests/test_demo.py::test_a",
    ])

    assert exit_code == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_manual_overrides_work_with_relevant_policy(monkeypatch):
    from src.change_analyzer import ChangeSet
    from src.models import TestCandidate
    from src.prioritizer import RankedTest

    nodeids = [
        f"tests/test_demo.py::test_{name}"
        for name in ("a", "b", "c")
    ]
    candidates = [
        TestCandidate(
            nodeid=nodeid,
            name=nodeid.split("::")[-1],
            file="tests/test_demo.py",
            estimated_duration_s=1.0,
        )
        for nodeid in nodeids
    ]
    ranked = [
        RankedTest(nodeid, 0.0, "no signal", "keyword")
        for nodeid in nodeids
    ]

    monkeypatch.setattr(
        main,
        "_changes",
        lambda args: ChangeSet(base="HEAD", head="HEAD", files=[]),
    )
    monkeypatch.setattr(
        main,
        "_rank",
        lambda args, candidates, changes: (
            ranked, "keyword", None, 0.0, {}
        ),
    )

    args = main.build_parser().parse_args([
        "select",
        "--budget", "10",
        "--selection-policy", "relevant",
        "--include", nodeids[2],
        "--exclude", nodeids[0],
    ])

    plan, _ = main._plan_for(args, candidates)

    assert plan.selected == [nodeids[2]]
    assert plan.decision_records[nodeids[2]].decision_code == (
        "manual_include"
    )
    assert plan.decision_records[nodeids[0]].decision_code == (
        "manual_exclude"
    )
    assert plan.decision_records[nodeids[1]].decision_code == (
        "relevance_filter"
    )


def test_cli_reports_conflicting_manual_overrides(monkeypatch, capsys):
    from src.models import TestCandidate

    nodeid = "tests/test_demo.py::test_a"
    candidate = TestCandidate(
        nodeid=nodeid,
        name="test_a",
        file="tests/test_demo.py",
        estimated_duration_s=1.0,
    )

    monkeypatch.setattr(main, "collect_tests", lambda **kwargs: [candidate])

    exit_code = main.main([
        "select",
        "--budget", "10",
        "--include", nodeid,
        "--exclude", nodeid,
    ])

    assert exit_code == 2
    assert "Cannot both include and exclude" in capsys.readouterr().err


def test_budget_run_applies_manual_overrides(tmp_path, monkeypatch):
    import json

    from src.change_analyzer import ChangeSet
    from src.models import RunOutcome, TestCandidate
    from src.prioritizer import RankedTest

    nodeids = [
        f"tests/test_demo.py::test_{name}"
        for name in ("a", "b", "c")
    ]
    candidates = [
        TestCandidate(
            nodeid=nodeid,
            name=nodeid.split("::")[-1],
            file="tests/test_demo.py",
            estimated_duration_s=1.0,
        )
        for nodeid in nodeids
    ]

    monkeypatch.setattr(main, "_history", lambda args: object())
    monkeypatch.setattr(
        main, "collect_tests", lambda **kwargs: candidates
    )
    monkeypatch.setattr(
        main,
        "_changes",
        lambda args: ChangeSet(base="HEAD", head="HEAD", files=[]),
    )
    monkeypatch.setattr(
        main,
        "_rank",
        lambda args, candidates, changes: (
            [
                RankedTest(nodeid, 1.0, "normal ranking", "keyword")
                for nodeid in nodeids
            ],
            "keyword", None, 0.0, {},
        ),
    )

    executed = []

    def fake_run_tests(selected, **kwargs):
        executed.extend(selected)
        return RunOutcome(selected=list(selected))

    monkeypatch.setattr(main, "run_tests", fake_run_tests)

    output = tmp_path / "manual-run.json"
    exit_code = main.main([
        "run",
        "--budget", "10",
        "--include", nodeids[2],
        "--exclude", nodeids[0],
        "--no-history",
        "--json", str(output),
    ])

    assert exit_code == 0
    assert executed == [nodeids[2], nodeids[1]]

    report = json.loads(output.read_text(encoding="utf-8"))
    decisions = {
        record["nodeid"]: record["decision_code"]
        for record in report["selection_evidence"]
    }
    assert decisions[nodeids[2]] == "manual_include"
    assert decisions[nodeids[0]] == "manual_exclude"
