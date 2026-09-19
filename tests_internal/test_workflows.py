"""Tests for the CI workflow definitions.

These files carry security properties that are easy to break by accident: a
read-only token, no model call on untrusted code, and a full-suite gate that a
selective run cannot stand in for. A typo in YAML would otherwise surface only
once it was already running against a real pull request.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
SELECTIVE = WORKFLOWS / "testbudget.yml"
FULL = WORKFLOWS / "full-suite.yml"


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", [SELECTIVE, FULL], ids=lambda p: p.name)
def test_workflow_parses(path):
    assert load(path)["jobs"]


@pytest.mark.parametrize("path", [SELECTIVE, FULL], ids=lambda p: p.name)
def test_token_is_read_only(path):
    """Neither workflow writes anything, so neither gets a writable token."""
    assert load(path)["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("path", [SELECTIVE, FULL], ids=lambda p: p.name)
def test_untrusted_pull_request_code_never_runs_with_a_privileged_trigger(path):
    """pull_request_target runs fork code with secrets in scope. Never use it."""
    # `on` parses as the boolean True in YAML 1.1, hence the lookup by both.
    triggers = load(path).get("on") or load(path).get(True)
    assert "pull_request_target" not in triggers


def test_selective_job_refuses_the_model_for_fork_pull_requests():
    steps = load(SELECTIVE)["jobs"]["selective"]["steps"]
    plan = next(step for step in steps if step.get("id") == "plan")
    run = next(step for step in steps if step.get("id") == "run")

    assert "IS_FORK" in plan["env"]
    assert 'IS_FORK" = "true"' in plan["run"]
    # The key reaches the run step only when the plan step allowed it.
    assert "steps.plan.outputs.use_model == 'true'" in run["env"]["NVIDIA_API_KEY"]


def test_selective_job_does_not_write_back_the_duration_history():
    """Recording durations would need a writable token for a disposable number."""
    steps = load(SELECTIVE)["jobs"]["selective"]["steps"]
    run = next(step for step in steps if step.get("id") == "run")

    assert "--no-history" in run["run"]


def test_selective_job_needs_history_for_the_diff():
    checkout = load(SELECTIVE)["jobs"]["selective"]["steps"][0]

    assert checkout["with"]["fetch-depth"] == 0


def test_full_suite_takes_no_budget_and_no_ranking():
    """The gate has to run everything, or it is not a gate."""
    steps = load(FULL)["jobs"]["full"]["steps"]
    commands = " ".join(step.get("run", "") for step in steps)

    assert "pytest" in commands
    assert "--budget" not in commands
    assert "--strategy" not in commands


def test_full_suite_also_runs_outside_pull_requests():
    triggers = load(FULL).get("on") or load(FULL).get(True)

    assert "push" in triggers
    assert "schedule" in triggers
