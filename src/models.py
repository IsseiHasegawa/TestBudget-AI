"""Data shapes passed between the collector, the scheduler and the runner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

PASSED = "passed"
FAILED = "failed"
ERROR = "error"
SKIPPED = "skipped"
TIMEOUT = "timeout"
NOT_RUN = "not_run"

FAILING_OUTCOMES = {FAILED, ERROR, TIMEOUT}


@dataclass
class TestCandidate:
    """One collected pytest test, plus whatever history we have for it."""

    __test__ = False

    nodeid: str
    name: str
    file: str
    summary: str = ""
    markers: list[str] = field(default_factory=list)
    estimated_duration_s: float | None = None
    last_outcome: str | None = None
    run_count: int = 0
    fail_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_model_input(self) -> dict:
        """Minimal shape handed to Nemotron in Phase 2.

        Kept deliberately small: nodeid, a one line summary and the measured
        duration. No source code, no secrets, no repository paths beyond the
        test file itself.
        """
        payload: dict[str, object] = {"nodeid": self.nodeid, "summary": self.summary}
        if self.estimated_duration_s is not None:
            payload["duration_s"] = round(self.estimated_duration_s, 3)
        if self.run_count:
            payload["recent_failures"] = self.fail_count
        return payload


@dataclass
class TestResult:
    """Outcome of a single test in one run."""

    __test__ = False

    nodeid: str
    outcome: str
    duration_s: float = 0.0
    message: str = ""

    @property
    def failed(self) -> bool:
        return self.outcome in FAILING_OUTCOMES

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunOutcome:
    """Everything one pytest invocation produced."""

    results: list[TestResult] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)
    wall_time_s: float = 0.0
    exit_status: int | None = None
    timed_out: bool = False
    stderr_tail: str = ""

    def by_nodeid(self) -> dict[str, TestResult]:
        return {result.nodeid: result for result in self.results}

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for result in self.results:
            tally[result.outcome] = tally.get(result.outcome, 0) + 1
        return tally

    def failures(self) -> list[TestResult]:
        return [result for result in self.results if result.failed]
