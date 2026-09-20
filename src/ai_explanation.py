"""Validate Nemotron-generated relevance explanations.

AI explanations are inferences, not verified code dependencies.
"""

from __future__ import annotations

import json


MAX_EXPLANATION_CHARS = 400


class ExplanationRejected(ValueError):
    """The model did not return a usable explanation."""


def parse_explanation_response(body: dict) -> dict:
    """Validate one explanation from a chat-completion response."""
    if not isinstance(body, dict):
        raise ExplanationRejected("response is not an object")

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ExplanationRejected("response has no choices")

    choice = choices[0]
    if not isinstance(choice, dict):
        raise ExplanationRejected("choice is not an object")

    if choice.get("finish_reason") == "length":
        raise ExplanationRejected("model response was truncated")

    message = choice.get("message")
    if not isinstance(message, dict):
        raise ExplanationRejected("response has no message")

    content = message.get("content")
    if not isinstance(content, str):
        raise ExplanationRejected("response has no text content")

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ExplanationRejected("response is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ExplanationRejected("explanation payload is not an object")

    explanation = payload.get("explanation")
    if not isinstance(explanation, str):
        raise ExplanationRejected("explanation must be a string")

    explanation = " ".join(explanation.split())
    if not explanation or len(explanation) > MAX_EXPLANATION_CHARS:
        raise ExplanationRejected("explanation is empty or too long")

    return {
        "type": "ai_inferred_relevance",
        "source": "nemotron",
        "explanation": explanation,
        "execution_verified": False,
    }


def attach_explanation(
    report: dict,
    nodeid: str,
    explanation: dict,
) -> dict:
    """Return a report copy with an AI explanation attached to one test."""
    from copy import deepcopy

    if (
        explanation.get("type") != "ai_inferred_relevance"
        or explanation.get("source") != "nemotron"
        or explanation.get("execution_verified") is not False
        or not isinstance(explanation.get("explanation"), str)
    ):
        raise ExplanationRejected("invalid AI explanation")

    updated = deepcopy(report)

    for record in updated.get("selection_evidence", []):
        if record.get("nodeid") == nodeid:
            record["ai_explanation"] = explanation
            return updated

    raise ValueError(f"test not found in report: {nodeid}")
