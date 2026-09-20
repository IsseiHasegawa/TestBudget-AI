"""Tests for validating AI-generated explanations."""

import json

import pytest

from src.ai_explanation import (
    ExplanationRejected,
    parse_explanation_response,
)


def response(content, finish_reason="stop"):
    return {
        "choices": [{
            "finish_reason": finish_reason,
            "message": {"content": content},
        }]
    }


def test_accepts_valid_explanation():
    body = response(json.dumps({
        "explanation": "The rounding change may affect the checkout total."
    }))

    result = parse_explanation_response(body)

    assert result["type"] == "ai_inferred_relevance"
    assert result["source"] == "nemotron"
    assert result["execution_verified"] is False
    assert "rounding change" in result["explanation"]


def test_rejects_invalid_json():
    with pytest.raises(ExplanationRejected, match="valid JSON"):
        parse_explanation_response(response("not JSON"))


def test_rejects_missing_explanation():
    with pytest.raises(ExplanationRejected, match="must be a string"):
        parse_explanation_response(response('{"reason": "related"}'))


def test_rejects_truncated_response():
    with pytest.raises(ExplanationRejected, match="truncated"):
        parse_explanation_response(
            response('{"explanation": "incomplete"}', "length")
        )


def test_rejects_overly_long_explanation():
    body = response(json.dumps({"explanation": "x" * 401}))

    with pytest.raises(ExplanationRejected, match="too long"):
        parse_explanation_response(body)


from src.ai_explanation import attach_explanation


def sample_report():
    return {
        "selected_tests": ["tests/test_coupon.py::test_rounding"],
        "selection_evidence": [
            {
                "nodeid": "tests/test_coupon.py::test_rounding",
                "ranking_reason": "Related to the changed function.",
                "code_evidence": [{"type": "static_call_path"}],
            },
            {
                "nodeid": "tests/test_profile.py::test_name",
                "ranking_reason": "Lower relevance.",
                "code_evidence": [],
            },
        ],
    }


def sample_explanation():
    return {
        "type": "ai_inferred_relevance",
        "source": "nemotron",
        "explanation": "The rounding change may affect this test.",
        "execution_verified": False,
    }


def test_attach_adds_only_ai_explanation():
    original = sample_report()
    updated = attach_explanation(
        original,
        "tests/test_coupon.py::test_rounding",
        sample_explanation(),
    )

    assert "ai_explanation" not in original["selection_evidence"][0]
    assert updated["selected_tests"] == original["selected_tests"]
    assert updated["selection_evidence"][0]["ranking_reason"] == (
        original["selection_evidence"][0]["ranking_reason"]
    )
    assert updated["selection_evidence"][0]["code_evidence"] == (
        original["selection_evidence"][0]["code_evidence"]
    )
    assert updated["selection_evidence"][0]["ai_explanation"] == (
        sample_explanation()
    )
    assert updated["selection_evidence"][1] == (
        original["selection_evidence"][1]
    )


def test_attach_rejects_unknown_test():
    with pytest.raises(ValueError, match="test not found"):
        attach_explanation(
            sample_report(),
            "tests/test_missing.py::test_unknown",
            sample_explanation(),
        )


def test_attach_rejects_unverified_type_mismatch():
    invalid = sample_explanation()
    invalid["type"] = "static_call_path"

    with pytest.raises(ExplanationRejected, match="invalid AI explanation"):
        attach_explanation(
            sample_report(),
            "tests/test_coupon.py::test_rounding",
            invalid,
        )
