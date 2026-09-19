"""Apply a scenario, find out what it really breaks, and put the tree back.

Ground truth is measured rather than declared: the whole suite runs against
each scenario and whatever fails is what that scenario broke. Failure is
independent of how long a test sleeps, so ground truth runs with the simulated
waits shrunk. The budget arithmetic still uses the durations measured at full
scale, which live in the history file.
"""

from __future__ import annotations

import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from evaluation.scenarios import Scenario
from src import config
from src.models import FAILING_OUTCOMES
from src.test_collector import collect_tests
from src.test_runner import run_tests

# Failures do not depend on sleep length, so ground truth does not need to
# wait out two and a half minutes per scenario.
GROUND_TRUTH_SCALE = "0.01"


class DirtyTreeError(RuntimeError):
    """Raised when uncommitted changes would contaminate the measurement."""


def require_clean_tree(root: Path | None = None) -> None:
    """Refuse to measure on top of unrelated edits.

    Every ranking reads the working tree diff. An unrelated edit puts extra
    files in that diff and inflates the scores of tests that have nothing to do
    with the scenario, which silently invalidates the whole run.
    """
    root = Path(root) if root else config.ROOT
    completed = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(root), capture_output=True, text=True
    )
    if completed.stdout.strip():
        raise DirtyTreeError(
            "the working tree has uncommitted changes; commit or stash them first:\n"
            + completed.stdout.strip()
        )


@contextmanager
def applied(scenario: Scenario, root: Path | None = None):
    """Apply a scenario for the duration of the block, then restore the file."""
    root = Path(root) if root else config.ROOT
    target = root / scenario.path
    original = target.read_text(encoding="utf-8")
    if scenario.old not in original:
        raise ValueError(f"{scenario.name}: pattern not found in {scenario.path}")
    try:
        target.write_text(original.replace(scenario.old, scenario.new, 1), encoding="utf-8")
        yield
    finally:
        target.write_text(original, encoding="utf-8")


@dataclass
class GroundTruth:
    failing: set[str]
    total_collected: int

    def is_benign(self) -> bool:
        return not self.failing


def ground_truth(root: Path | None = None) -> GroundTruth:
    """Run everything and report what fails. Call inside `applied`."""
    candidates = collect_tests(root=root)
    nodeids = [candidate.nodeid for candidate in candidates]
    outcome = run_tests(
        nodeids,
        root=root,
        extra_env={"TB_LATENCY_SCALE": GROUND_TRUTH_SCALE},
    )
    return GroundTruth(
        failing={result.nodeid for result in outcome.results if result.outcome in FAILING_OUTCOMES},
        total_collected=len(nodeids),
    )
