"""Tests for the Nemotron explanation client without network calls."""

import json

import pytest

from src import ai_explanation_client as client
from src.model_response import NOT_CONFIGURED, TIMEOUT, ResponseRejected


def request_explanation():
    return client.explain_test_relevance(
        nodeid="tests/test_checkout.py::test_total",
        test_summary="Checks the order total after applying a coupon.",
        changed_file="app/coupon.py",
        changed_function="_round_percent",
        call_path=[
            "tests.test_checkout.test_total",
            "app.checkout.build_order",
            "app.coupon._round_percent",
        ],
        timeout_s=5.0,
    )


def test_returns_ai_inferred_explanation(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "dummy-test-key")
    monkeypatch.setattr(client.config, "load_env_file", lambda: None)

    captured = {}

    def fake_post(payload, timeout_s):
        captured["payload"] = payload
        captured["timeout_s"] = timeout_s
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({
                        "explanation": (
                            "Changing percentage rounding may affect "
                            "the order total checked by this test."
                        )
                    })
                },
            }]
        }

    monkeypatch.setattr(client, "_post", fake_post)

    result = request_explanation()

    assert result["type"] == "ai_inferred_relevance"
    assert result["execution_verified"] is False
    assert "rounding" in result["explanation"]
    assert captured["timeout_s"] == 5.0
    assert "app.coupon._round_percent" in (
        captured["payload"]["messages"][0]["content"]
    )


def test_timeout_is_reported_without_inventing_an_explanation(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "dummy-test-key")
    monkeypatch.setattr(client.config, "load_env_file", lambda: None)

    def fake_post(payload, timeout_s):
        raise ResponseRejected(TIMEOUT, "simulated timeout")

    monkeypatch.setattr(client, "_post", fake_post)

    with pytest.raises(ResponseRejected) as error:
        request_explanation()

    assert error.value.reason == TIMEOUT


def test_missing_api_key_does_not_send_a_request(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(client.config, "load_env_file", lambda: None)

    def unexpected_post(payload, timeout_s):
        pytest.fail("The API must not be called without a key.")

    monkeypatch.setattr(client, "_post", unexpected_post)

    with pytest.raises(ResponseRejected) as error:
        request_explanation()

    assert error.value.reason == NOT_CONFIGURED


def test_request_includes_changed_diff(monkeypatch):
    """The reviewed diff is included in the explanation request."""
    monkeypatch.setenv("NVIDIA_API_KEY", "dummy-test-key")
    monkeypatch.setattr(client.config, "load_env_file", lambda: None)

    captured = {}

    def fake_post(payload, timeout_s):
        captured["prompt"] = payload["messages"][0]["content"]
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({
                        "explanation": "The rounding change may affect the test."
                    })
                },
            }]
        }

    monkeypatch.setattr(client, "_post", fake_post)

    diff = (
        "-    return (subtotal * percent) // 100\n"
        "+    return round(subtotal * percent / 100)"
    )

    result = client.explain_test_relevance(
        nodeid="tests/test_coupon.py::test_rounding",
        test_summary="Checks percentage discount rounding.",
        changed_file="app/coupon.py",
        changed_function="_round_percent",
        changed_diff=diff,
        timeout_s=5.0,
    )

    payload_text = captured["prompt"].partition(
        "UNTRUSTED REPOSITORY DATA:"
    )[2].strip()
    assert payload_text, "Repository data was not found in the prompt"
    evidence = json.loads(payload_text)
    assert evidence["change_excerpt"] == diff
    assert result["type"] == "ai_inferred_relevance"
    assert result["execution_verified"] is False
