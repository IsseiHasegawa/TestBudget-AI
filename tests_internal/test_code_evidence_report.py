"""Verify that static call paths are saved in the selection report."""

import json

from src import code_explanation

from src.change_analyzer import ChangeSet, ChangedFile
from src.models import RunOutcome, TestCandidate
from src.prioritizer import RankedTest
from src.reporter import build_report
from src.scheduler import build_plan


def test_report_saves_static_call_paths_without_inventing_links(monkeypatch):
    original = code_explanation._build_call_graph
    graph_builds = []

    def counted_build(source_root):
        graph_builds.append(source_root)
        return original(source_root)

    monkeypatch.setattr(
        code_explanation, "_build_call_graph", counted_build
    )

    nodeids = [
        "demo_project/tests/test_coupon.py::test_percent_discount_truncates_partial_cent",
        "demo_project/tests/test_checkout.py::test_percent_coupon_changes_total",
        "demo_project/tests/test_profile.py::test_avatar_upload_accepts_png",
    ]

    candidates = [
        TestCandidate(
            nodeid=nodeid,
            name=nodeid.split("::")[-1],
            file=nodeid.split("::")[0],
            estimated_duration_s=1.0,
        )
        for nodeid in nodeids
    ]

    ranked = [
        RankedTest(nodeid, 1.0, "test ranking reason", "keyword")
        for nodeid in nodeids
    ]

    changes = ChangeSet(
        base="HEAD~1",
        head="HEAD",
        files=[
            ChangedFile(
                path="demo_project/app/coupon.py",
                status="m",
                symbols=["_round_percent"],
            )
        ],
    )

    plan = build_plan(
        ranked,
        candidates,
        budget_s=30.0,
        ranking_source="keyword",
    )

    outcome = RunOutcome(selected=list(plan.selected))
    report = build_report(outcome, candidates, plan, changes)

    assert len(graph_builds) == 1

    evidence_by_test = {
        record["nodeid"]: record["code_evidence"]
        for record in report["selection_evidence"]
    }

    assert evidence_by_test[nodeids[0]][0]["call_path"] == [
        "tests.test_coupon.test_percent_discount_truncates_partial_cent",
        "app.coupon.discount_for",
        "app.coupon._round_percent",
    ]

    assert evidence_by_test[nodeids[1]][0]["call_path"] == [
        "tests.test_checkout.test_percent_coupon_changes_total",
        "app.checkout.build_order",
        "app.coupon.apply_coupon",
        "app.coupon.discount_for",
        "app.coupon._round_percent",
    ]

    assert evidence_by_test[nodeids[2]] == []

    for nodeid in nodeids[:2]:
        record = evidence_by_test[nodeid][0]
        assert record["type"] == "static_call_path"
        assert record["execution_verified"] is False
        assert record["source_snapshot"] == "working_tree"

    # The new evidence must be serializable in the JSON report.
    json.dumps(report)
