"""Tests for the model response validator.

Every rejection case here was observed against the live API, not invented. The
validator runs offline so these stay fast and deterministic.
"""

import json

import pytest

from src.model_response import (
    EMPTY_RESPONSE,
    INVALID_JSON,
    NO_VALID_IDS,
    SCHEMA_MISMATCH,
    TRUNCATED,
    ResponseRejected,
    extract_json_object,
    validate,
)

NODEIDS = [
    "tests/test_coupon.py::test_rounding",
    "tests/test_checkout.py::test_total",
    "tests/test_profile.py::test_avatar",
]
FALLBACK = list(NODEIDS)


def run(content, finish_reason=None, nodeids=None, fallback=None):
    return validate(content, finish_reason, nodeids or NODEIDS, fallback or FALLBACK)


def test_index_form_is_accepted_and_ordered():
    result = run(json.dumps({"order": [2, 1, 3], "reasons": {"2": "totals move"}}))

    assert result.order == [NODEIDS[1], NODEIDS[0], NODEIDS[2]]
    assert result.reasons[NODEIDS[1]] == "totals move"
    assert result.completed_by_fallback == []


def test_object_form_is_accepted():
    payload = {"ranked_tests": [{"nodeid": NODEIDS[2], "reason": "unrelated"}]}

    result = run(json.dumps(payload))

    assert result.order[0] == NODEIDS[2]
    assert result.reasons[NODEIDS[2]] == "unrelated"


def test_bare_string_list_is_accepted_without_reasons():
    """Observed drift: ranked_tests arrived as plain ids rather than objects."""
    result = run(json.dumps({"ranked_tests": [NODEIDS[1], NODEIDS[0]]}))

    assert result.order[:2] == [NODEIDS[1], NODEIDS[0]]
    assert result.reasons == {}


def test_prose_around_the_json_is_tolerated():
    content = 'Sure, here you go:\n```json\n{"order":[1]}\n```\nHope that helps.'

    result = run(content)

    assert result.order[0] == NODEIDS[0]


def test_missing_tests_are_appended_in_fallback_order():
    result = run(json.dumps({"order": [3]}))

    assert result.order[0] == NODEIDS[2]
    assert set(result.order) == set(NODEIDS)
    assert result.completed_by_fallback == [NODEIDS[0], NODEIDS[1]]


def test_out_of_range_indices_are_discarded():
    result = run(json.dumps({"order": [99, 0, -1, 2]}))

    assert result.order[0] == NODEIDS[1]
    assert sorted(result.discarded) == ["-1", "0", "99"]


def test_invented_nodeids_are_discarded():
    payload = {"ranked_tests": [{"nodeid": "tests/test_made_up.py::test_x"}, {"nodeid": NODEIDS[0]}]}

    result = run(json.dumps(payload))

    assert result.order[0] == NODEIDS[0]
    assert result.discarded == ["tests/test_made_up.py::test_x"]


def test_duplicates_keep_only_the_first_position():
    result = run(json.dumps({"order": [3, 3, 1]}))

    assert result.order[:2] == [NODEIDS[2], NODEIDS[0]]
    assert len(result.order) == len(NODEIDS)


def test_empty_content_is_rejected():
    with pytest.raises(ResponseRejected) as exc:
        run("   ")
    assert exc.value.reason == EMPTY_RESPONSE


def test_token_ceiling_is_rejected_before_parsing():
    """A length finish means the JSON is cut off even if it looks plausible."""
    with pytest.raises(ResponseRejected) as exc:
        run('{"order":[1,2', finish_reason="length")
    assert exc.value.reason == TRUNCATED


def test_unbalanced_braces_are_rejected():
    with pytest.raises(ResponseRejected) as exc:
        run('{"order":[1,2')
    assert exc.value.reason == INVALID_JSON


def test_malformed_json_is_rejected():
    with pytest.raises(ResponseRejected) as exc:
        run('{"order": [1,, 2]}')
    assert exc.value.reason == INVALID_JSON


def test_unrecognised_shape_is_rejected_rather_than_guessed():
    with pytest.raises(ResponseRejected) as exc:
        run(json.dumps({"tests": ["a", "b"]}))
    assert exc.value.reason == SCHEMA_MISMATCH


def test_nested_junk_in_the_list_is_rejected():
    with pytest.raises(ResponseRejected) as exc:
        run(json.dumps({"ranked_tests": [["nested"]]}))
    assert exc.value.reason == SCHEMA_MISMATCH


def test_all_ids_invalid_is_rejected():
    with pytest.raises(ResponseRejected) as exc:
        run(json.dumps({"order": [40, 50]}))
    assert exc.value.reason == NO_VALID_IDS


def test_booleans_do_not_sneak_through_as_indices():
    """True is an int in Python, and would otherwise resolve to index 1."""
    with pytest.raises(ResponseRejected) as exc:
        run(json.dumps({"order": [True, False]}))
    assert exc.value.reason == NO_VALID_IDS


def test_reasons_are_trimmed():
    result = run(json.dumps({"order": [1], "reasons": {"1": "x" * 500}}))

    assert len(result.reasons[NODEIDS[0]]) == 200


def test_extract_json_object_ignores_braces_inside_strings():
    content = '{"order":[1],"reasons":{"1":"a } brace in text"}}'

    assert json.loads(extract_json_object(content))["reasons"]["1"] == "a } brace in text"
