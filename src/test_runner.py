"""Run a specific list of pytest nodeids and record what happened.

Nodeids are passed as separate argv entries and never joined into a shell
string, so nothing a model produced can be interpreted as a command.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

from src import config
from src.models import NOT_RUN, TIMEOUT, RunOutcome, TestResult


class RunnerError(RuntimeError):
    """Raised when pytest could not be started at all."""


def run_tests(
    nodeids: list[str],
    root: Path | None = None,
    python: str | None = None,
    timeout_s: float | None = None,
    extra_args: list[str] | None = None,
) -> RunOutcome:
    root = Path(root) if root else config.ROOT
    python = python or config.default_python()

    if not isinstance(nodeids, list) or any(not isinstance(item, str) for item in nodeids):
        raise RunnerError("nodeids must be a list of strings")
    if not nodeids:
        return RunOutcome(results=[], selected=[], wall_time_s=0.0, exit_status=None)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "results.json"
        env = config.subprocess_env(root)
        env["TB_RESULT_OUT"] = str(out_path)
        env.pop("TB_COLLECT_OUT", None)

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
                timeout=timeout_s,
            )
            exit_status = completed.returncode
            stderr_tail = completed.stderr[-2000:]
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stderr_tail = (exc.stderr or b"").decode("utf-8", "replace")[-2000:] if isinstance(exc.stderr, bytes) else (exc.stderr or "")[-2000:]
        wall_time_s = time.perf_counter() - started

        recorded: dict[str, dict] = {}
        if out_path.exists():
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            if exit_status is None:
                exit_status = payload.get("exit_status")
            recorded = {entry["nodeid"]: entry for entry in payload.get("results", [])}

    results = []
    for nodeid in nodeids:
        entry = recorded.get(nodeid)
        if entry is None:
            # The process died or ran out of time before reaching this test.
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
