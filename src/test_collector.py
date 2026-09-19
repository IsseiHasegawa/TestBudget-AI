"""Collect the real pytest nodeids that a run is allowed to touch.

Everything downstream validates against this list, so an id the collector never
produced can never reach a pytest command line.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from src import config
from src.history import DurationHistory
from src.models import TestCandidate

# pytest exits with 5 when it collected nothing, which is an empty result
# rather than a tooling failure.
EXIT_NO_TESTS_COLLECTED = 5


class CollectionError(RuntimeError):
    """Raised when pytest could not enumerate the test suite."""


def collect_tests(
    target: str = config.DEMO_TARGET,
    root: Path | None = None,
    history: DurationHistory | None = None,
    python: str | None = None,
) -> list[TestCandidate]:
    root = Path(root) if root else config.ROOT
    python = python or config.default_python()

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "collected.json"
        env = config.subprocess_env(root)
        env["TB_COLLECT_OUT"] = str(out_path)
        env.pop("TB_RESULT_OUT", None)

        command = [
            python,
            "-m",
            "pytest",
            target,
            "--collect-only",
            "-q",
            "-p",
            config.PLUGIN_MODULE,
        ]
        completed = subprocess.run(
            command,
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
        )

        if completed.returncode == EXIT_NO_TESTS_COLLECTED:
            return []
        if completed.returncode != 0 or not out_path.exists():
            raise CollectionError(
                f"pytest collection failed (exit {completed.returncode}).\n"
                f"{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
            )
        payload = json.loads(out_path.read_text(encoding="utf-8"))

    history = history if history is not None else DurationHistory.load()
    candidates = []
    for entry in payload.get("tests", []):
        stats = history.stats(entry["nodeid"])
        candidates.append(
            TestCandidate(
                nodeid=entry["nodeid"],
                name=entry.get("name", ""),
                file=entry.get("file", ""),
                summary=entry.get("summary", ""),
                markers=entry.get("markers", []),
                estimated_duration_s=stats.estimate() if stats else None,
                last_outcome=stats.last_outcome if stats else None,
                run_count=stats.run_count if stats else 0,
                fail_count=stats.fail_count if stats else 0,
            )
        )
    return candidates


def validate_nodeids(requested: list[str], candidates: list[TestCandidate]) -> tuple[list[str], list[str]]:
    """Split `requested` into ids that exist and ids that do not.

    Order is preserved and duplicates are dropped, because this is the gate a
    model supplied ranking has to pass before it becomes a pytest argv.
    """
    known = {candidate.nodeid for candidate in candidates}
    valid: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for nodeid in requested:
        if nodeid in seen:
            continue
        seen.add(nodeid)
        (valid if nodeid in known else unknown).append(nodeid)
    return valid, unknown
