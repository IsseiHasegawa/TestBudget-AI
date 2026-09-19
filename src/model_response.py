"""Validate whatever the model returned before it can influence a test run.

Measured behaviour this has to survive, all observed against
nemotron-3.5-lightning with response_format set to json_object:

* a response that is not valid JSON at all, from a generation loop that ran
  into the token ceiling
* `ranked_tests` returned as a list of bare strings rather than objects
* the API failing outright, which the client handles before reaching here

So `response_format` buys a tendency toward JSON, not a guarantee of it, and
certainly not a guarantee of shape. Every stage below assumes the response is
hostile input and rejects rather than repairs anything it does not recognise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_REASON_CHARS = 200

# Reasons the scheduler records when it falls back. Kept as constants because
# they end up in reports the evaluation aggregates.
NOT_CONFIGURED = "not_configured"
BUDGET_TOO_SMALL = "budget_too_small"
TIMEOUT = "timeout"
SERVER_ERROR = "server_error"
RATE_LIMITED = "rate_limited"
AUTH_FAILED = "auth_failed"
EMPTY_RESPONSE = "empty_response"
TRUNCATED = "truncated"
INVALID_JSON = "invalid_json"
SCHEMA_MISMATCH = "schema_mismatch"
NO_VALID_IDS = "no_valid_ids"


class ResponseRejected(Exception):
    """Raised when a model response cannot be trusted to order tests."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass
class ValidatedRanking:
    order: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    discarded: list[str] = field(default_factory=list)
    completed_by_fallback: list[str] = field(default_factory=list)


def extract_json_object(text: str) -> str:
    """Return the first balanced JSON object in `text`.

    Models wrap JSON in prose or fences often enough that failing on the first
    stray character would throw away usable answers.
    """
    start = text.find("{")
    if start == -1:
        raise ResponseRejected(INVALID_JSON, "no opening brace in the response")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ResponseRejected(INVALID_JSON, "braces never balanced; response looks truncated")


def _clean_reason(value: object) -> str:
    if not isinstance(value, str):
        return ""
    collapsed = " ".join(value.split())
    return collapsed[:MAX_REASON_CHARS]


def _pairs_from_payload(payload: object) -> list[tuple[object, str]]:
    """Normalise the shapes we are willing to accept into (key, reason) pairs.

    Exactly three shapes are recognised. Anything else is rejected rather than
    guessed at, because a response we cannot read is not the same as a response
    that ranked nothing.
    """
    if not isinstance(payload, dict):
        raise ResponseRejected(SCHEMA_MISMATCH, f"top level is {type(payload).__name__}, not an object")

    if isinstance(payload.get("order"), list):
        reasons = payload.get("reasons")
        reasons = reasons if isinstance(reasons, dict) else {}
        return [(key, _clean_reason(reasons.get(str(key)))) for key in payload["order"]]

    ranked = payload.get("ranked_tests")
    if isinstance(ranked, list):
        pairs: list[tuple[object, str]] = []
        for item in ranked:
            if isinstance(item, dict):
                pairs.append((item.get("nodeid"), _clean_reason(item.get("reason"))))
            elif isinstance(item, (str, int)):
                # Observed drift: the list arrives as bare ids with no reasons.
                pairs.append((item, ""))
            else:
                raise ResponseRejected(
                    SCHEMA_MISMATCH, f"ranked_tests contains a {type(item).__name__}"
                )
        return pairs

    raise ResponseRejected(
        SCHEMA_MISMATCH, f"expected 'order' or 'ranked_tests', got keys {sorted(payload)[:5]}"
    )


def validate(
    content: str,
    finish_reason: str | None,
    nodeids: list[str],
    fallback_order: list[str],
) -> ValidatedRanking:
    """Turn raw model output into an order of real nodeids, or reject it.

    `nodeids` is the collected candidate list, indexed from 1 in the prompt.
    `fallback_order` supplies the deterministic tail for anything the model
    left out, so the returned order always covers every candidate.
    """
    if not content or not content.strip():
        raise ResponseRejected(EMPTY_RESPONSE, "model returned no content")
    if finish_reason == "length":
        raise ResponseRejected(TRUNCATED, "generation hit the token ceiling")

    import json  # local: keeps the module importable in restricted contexts

    try:
        payload = json.loads(extract_json_object(content))
    except json.JSONDecodeError as exc:
        raise ResponseRejected(INVALID_JSON, str(exc)) from exc

    known = set(nodeids)
    result = ValidatedRanking()
    seen: set[str] = set()

    for key, reason in _pairs_from_payload(payload):
        nodeid = _resolve(key, nodeids, known)
        if nodeid is None:
            result.discarded.append(str(key))
            continue
        if nodeid in seen:
            continue
        seen.add(nodeid)
        result.order.append(nodeid)
        if reason:
            result.reasons[nodeid] = reason

    if not result.order:
        raise ResponseRejected(NO_VALID_IDS, f"discarded every entry ({len(result.discarded)})")

    # The plan requires the model's omissions to be filled deterministically
    # rather than silently dropped from the run.
    for nodeid in fallback_order:
        if nodeid not in seen:
            seen.add(nodeid)
            result.order.append(nodeid)
            result.completed_by_fallback.append(nodeid)

    return result


def _resolve(key: object, nodeids: list[str], known: set[str]) -> str | None:
    """Map a model-supplied index or id onto a real nodeid, or None."""
    if isinstance(key, bool):
        return None
    if isinstance(key, int):
        return nodeids[key - 1] if 1 <= key <= len(nodeids) else None
    if isinstance(key, str):
        stripped = key.strip()
        if stripped in known:
            return stripped
        if stripped.isdigit():
            index = int(stripped)
            return nodeids[index - 1] if 1 <= index <= len(nodeids) else None
    return None
