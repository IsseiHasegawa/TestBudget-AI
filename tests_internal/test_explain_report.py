"""Tests for the optional explanation CLI without network requests."""

import json
import sys

from src import explain_report


def setup_files(tmp_path):
    report_path = tmp_path / "report.json"
    diff_path = tmp_path / "reviewed.diff"
    output_path = tmp_path / "explained.json"
    nodeid = "tests/test_coupon.py::test_rounding"

    report = {
        "selected_tests": [nodeid],
        "selection_evidence": [{
            "nodeid": nodeid,
            "ranking_reason": "Related to coupon rounding.",
            "code_evidence": [{
                "type": "static_call_path",
                "changed_file": "app/coupon.py",
                "changed_function": "_round_percent",
                "call_path": [
                    "tests.test_coupon.test_rounding",
                    "app.coupon._round_percent",
                ],
                "execution_verified": False,
            }],
        }],
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    diff_path.write_text(
        "- return subtotal // 100\n+ return round(subtotal / 100)\n",
        encoding="utf-8",
    )

    args = [
        "explain_report",
        str(report_path),
        "--nodeid", nodeid,
        "--diff-file", str(diff_path),
        "--output", str(output_path),
    ]
    return report_path, output_path, args


def test_preview_does_not_call_api_or_write_output(
    tmp_path, monkeypatch, capsys
):
    report_path, output_path, args = setup_files(tmp_path)
    original = report_path.read_text(encoding="utf-8")

    def unexpected_api_call(**kwargs):
        raise AssertionError("Preview must not call Nemotron")

    monkeypatch.setattr(
        explain_report, "explain_test_relevance", unexpected_api_call
    )
    monkeypatch.setattr(sys, "argv", args)

    explain_report.main()

    assert "Preview only" in capsys.readouterr().out
    assert not output_path.exists()
    assert report_path.read_text(encoding="utf-8") == original


def test_confirmed_send_saves_separate_report(
    tmp_path, monkeypatch
):
    report_path, output_path, args = setup_files(tmp_path)
    original = report_path.read_text(encoding="utf-8")
    calls = []

    def fake_api_call(**kwargs):
        calls.append(kwargs)
        return {
            "type": "ai_inferred_relevance",
            "source": "nemotron",
            "explanation": "The rounding change may affect this test.",
            "execution_verified": False,
        }

    monkeypatch.setattr(
        explain_report, "explain_test_relevance", fake_api_call
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "SEND")
    monkeypatch.setattr(sys, "argv", args + ["--send"])

    explain_report.main()

    assert len(calls) == 1
    assert "return round" in calls[0]["changed_diff"]
    assert report_path.read_text(encoding="utf-8") == original

    updated = json.loads(output_path.read_text(encoding="utf-8"))
    record = updated["selection_evidence"][0]
    assert record["ranking_reason"] == "Related to coupon rounding."
    assert record["code_evidence"][0]["type"] == "static_call_path"
    assert record["ai_explanation"]["type"] == "ai_inferred_relevance"


def test_cancelled_send_does_not_call_api(
    tmp_path, monkeypatch
):
    _, output_path, args = setup_files(tmp_path)

    def unexpected_api_call(**kwargs):
        raise AssertionError("Cancelled request must not call Nemotron")

    monkeypatch.setattr(
        explain_report, "explain_test_relevance", unexpected_api_call
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "NO")
    monkeypatch.setattr(sys, "argv", args + ["--send"])

    explain_report.main()

    assert not output_path.exists()
