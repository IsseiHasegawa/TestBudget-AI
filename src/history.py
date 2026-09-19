"""Measured duration and failure history for collected tests."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.models import FAILING_OUTCOMES, TestResult

SCHEMA_VERSION = 1
MAX_SAMPLES = 5


@dataclass
class TestHistory:
    __test__ = False

    durations: list[float]
    run_count: int = 0
    fail_count: int = 0
    last_outcome: str | None = None
    last_run_at: str | None = None

    def estimate(self) -> float | None:
        """Median of recent runs, which ignores a single slow outlier."""
        if not self.durations:
            return None
        return round(statistics.median(self.durations), 4)


class DurationHistory:
    def __init__(self, path: Path | None = None, tests: dict[str, TestHistory] | None = None):
        self.path = Path(path) if path else config.HISTORY_PATH
        self.tests: dict[str, TestHistory] = tests or {}

    @classmethod
    def load(cls, path: Path | None = None) -> "DurationHistory":
        target = Path(path) if path else config.HISTORY_PATH
        if not target.exists():
            return cls(target)
        raw = json.loads(target.read_text(encoding="utf-8"))
        tests = {
            nodeid: TestHistory(
                durations=[float(value) for value in entry.get("durations", [])],
                run_count=int(entry.get("run_count", 0)),
                fail_count=int(entry.get("fail_count", 0)),
                last_outcome=entry.get("last_outcome"),
                last_run_at=entry.get("last_run_at"),
            )
            for nodeid, entry in raw.get("tests", {}).items()
        }
        return cls(target, tests)

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tests": {
                nodeid: {
                    "durations": entry.durations,
                    "run_count": entry.run_count,
                    "fail_count": entry.fail_count,
                    "last_outcome": entry.last_outcome,
                    "last_run_at": entry.last_run_at,
                }
                for nodeid, entry in sorted(self.tests.items())
            },
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.path

    def record(self, results: list[TestResult]) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for result in results:
            if result.outcome in {"not_run", "timeout"}:
                # A test that never finished tells us nothing about its duration.
                continue
            entry = self.tests.setdefault(result.nodeid, TestHistory(durations=[]))
            entry.durations.append(round(result.duration_s, 4))
            del entry.durations[:-MAX_SAMPLES]
            entry.run_count += 1
            if result.outcome in FAILING_OUTCOMES:
                entry.fail_count += 1
            entry.last_outcome = result.outcome
            entry.last_run_at = now

    def estimate(self, nodeid: str) -> float | None:
        entry = self.tests.get(nodeid)
        return entry.estimate() if entry else None

    def stats(self, nodeid: str) -> TestHistory | None:
        return self.tests.get(nodeid)

    def total_estimate(self, nodeids: list[str]) -> float:
        return sum(self.estimate(nodeid) or 0.0 for nodeid in nodeids)
