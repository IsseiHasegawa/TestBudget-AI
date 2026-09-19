"""Run a specific list of pytest nodeids and record what happened.

Nodeids are passed as separate argv entries and never joined into a shell
string, so nothing a model produced can be interpreted as a command.

Two independent stops guard the budget. The plugin holds a wall-clock deadline
and refuses to start a test past it, which produces a clean `not_run` record.
The subprocess timeout is only a backstop for a test that ignores its signal,
so it sits a few seconds later.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

from src import config
from src.models import NOT_RUN, TIMEOUT, RunOutcome, TestResult

# Headroom between the plugin deadline and the hard process kill.
BACKSTOP_GRACE_S = 5.0


class RunnerError(RuntimeError):
    """Raised when pytest could not be started at all."""


def _read_jsonl(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    records: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue  # a partially flushed final line is not worth failing over
        records[entry["nodeid"]] = entry
    return records


def run_tests(
    nodeids: list[str],
    root: Path | None = None,
    python: str | None = None,
    timeout_s: float | None = None,
    per_test_timeout_s: float | None = None,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> RunOutcome:
    root = Path(root) if root else config.ROOT
    python = python or config.default_python()

    if not isinstance(nodeids, list) or any(not isinstance(item, str) for item in nodeids):
        raise RunnerError("nodeids must be a list of strings")
    if not nodeids:
        return RunOutcome(results=[], selected=[], wall_time_s=0.0, exit_status=None)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "results.jsonl"
        env = config.subprocess_env(root)
        env["TB_RESULT_OUT"] = str(out_path)
        env.pop("TB_COLLECT_OUT", None)

        if timeout_s is not None:
            env["TB_DEADLINE_TS"] = str(time.time() + timeout_s)
        if per_test_timeout_s is not None:
            env["TB_TEST_TIMEOUT_S"] = str(per_test_timeout_s)
        if extra_env:
            env.update(extra_env)

        command = [
            python,
            "-m",
            "pytest",
            *nodeids,
            "-p",
            config.PLUGIN_MODULE,
            "-q",
            "--no-header",
        ]
        if extra_args:
            command.extend(extra_args)

        started = time.perf_counter()
        timed_out = False
        exit_status: int | None = None
        stderr_tail = ""
        try:
            completed = subprocess.run(
                command,
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                timeout=(timeout_s + BACKSTOP_GRACE_S) if timeout_s is not None else None,
            )
            exit_status = completed.returncode
            stderr_tail = completed.stderr[-2000:]
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            raw = exc.stderr or b""
            stderr_tail = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)[-2000:]
        wall_time_s = time.perf_counter() - started

        recorded = _read_jsonl(out_path)

    results = []
    for nodeid in nodeids:
        entry = recorded.get(nodeid)
        if entry is None:
            # The process was killed before this test produced a record.
            results.append(TestResult(nodeid=nodeid, outcome=TIMEOUT if timed_out else NOT_RUN))
            continue
        results.append(
            TestResult(
                nodeid=nodeid,
                outcome=entry.get("outcome", NOT_RUN),
                duration_s=round(float(entry.get("duration_s", 0.0)), 4),
                message=entry.get("message", ""),
            )
        )

    return RunOutcome(
        results=results,
        selected=list(nodeids),
        wall_time_s=round(wall_time_s, 4),
        exit_status=exit_status,
        timed_out=timed_out,
        stderr_tail=stderr_tail,
    )
