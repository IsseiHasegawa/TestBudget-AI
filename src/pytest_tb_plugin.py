"""pytest plugin that exports collection and result data for TestBudget AI.

Loaded with `-p src.pytest_tb_plugin`. Writing exact `report.nodeid` values
here is what lets the scheduler validate every id it later passes back to
pytest, instead of reconstructing ids from junit-xml class names.

Results are appended one JSON object per line and flushed immediately. A
budget-driven run gets killed mid-flight often enough that buffering everything
until session end would throw away the results of tests that did finish.

The plugin stays inert unless TB_COLLECT_OUT or TB_RESULT_OUT is set, so it is
safe to leave on any pytest invocation.

Environment:
    TB_COLLECT_OUT     path for the collected-tests JSON
    TB_RESULT_OUT      path for the per-test JSONL results
    TB_DEADLINE_TS     absolute unix timestamp; tests are not started past it
    TB_TEST_TIMEOUT_S  per-test wall clock ceiling
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

COLLECT_ENV = "TB_COLLECT_OUT"
RESULT_ENV = "TB_RESULT_OUT"
DEADLINE_ENV = "TB_DEADLINE_TS"
TIMEOUT_ENV = "TB_TEST_TIMEOUT_S"

MAX_MESSAGE_CHARS = 1500
TIMEOUT_MARKER = "TestBudgetTimeout"

_pending: dict[str, dict] = {}
_written: set[str] = set()


class TestBudgetTimeout(Exception):
    """Raised inside a test that outlived its individual timeout."""


def _result_path() -> str | None:
    return os.environ.get(RESULT_ENV) or None


def _deadline() -> float | None:
    raw = os.environ.get(DEADLINE_ENV)
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _per_test_timeout() -> float | None:
    raw = os.environ.get(TIMEOUT_ENV)
    try:
        value = float(raw) if raw else None
    except ValueError:
        return None
    return value if value and value > 0 else None


def _write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _append_record(record: dict) -> None:
    path = _result_path()
    if not path or record["nodeid"] in _written:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    _written.add(record["nodeid"])


def _first_doc_line(item) -> str:
    try:
        doc = item.obj.__doc__
    except Exception:  # fixtures and non-python items have no callable object
        return ""
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _relative_file(item, rootdir: Path) -> str:
    try:
        return str(Path(str(item.path)).relative_to(rootdir))
    except Exception:
        return str(getattr(item, "path", ""))


def _short_message(report) -> str:
    longrepr = getattr(report, "longrepr", None)
    if longrepr is None:
        return ""
    text = str(longrepr[-1]) if isinstance(longrepr, tuple) else str(longrepr)
    text = text.strip()
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS] + "\n... (truncated)"
    return text


def pytest_collection_finish(session) -> None:
    out = os.environ.get(COLLECT_ENV)
    if not out:
        return
    rootdir = Path(str(session.config.rootpath))
    tests = [
        {
            "nodeid": item.nodeid,
            "name": item.name,
            "file": _relative_file(item, rootdir),
            "summary": _first_doc_line(item),
            "markers": sorted({mark.name for mark in item.iter_markers()}),
        }
        for item in session.items
    ]
    _write_json(out, {"rootdir": str(rootdir), "tests": tests})


def pytest_runtest_protocol(item, nextitem):
    """Refuse to start a test that cannot finish inside the budget."""
    deadline = _deadline()
    if deadline is None or not _result_path():
        return None
    if time.time() < deadline:
        return None
    _append_record(
        {
            "nodeid": item.nodeid,
            "outcome": "not_run",
            "duration_s": 0.0,
            "message": "not started: run budget already exhausted",
        }
    )
    return True  # claim the protocol so pytest skips this item entirely


def pytest_runtest_setup(item) -> None:
    if not hasattr(signal, "SIGALRM"):
        return

    timeout = _per_test_timeout()
    deadline = _deadline()
    if deadline is not None:
        # The deadline bounds each test as well as the decision to start one,
        # otherwise a single long test walks straight through the budget.
        remaining = deadline - time.time()
        timeout = remaining if timeout is None else min(timeout, remaining)
    if timeout is None or timeout <= 0:
        return

    def _fire(signum, frame):
        raise TestBudgetTimeout(f"test exceeded its {timeout:.2f}s timeout")

    signal.signal(signal.SIGALRM, _fire)
    signal.setitimer(signal.ITIMER_REAL, timeout)


def pytest_runtest_teardown(item, nextitem) -> None:
    if hasattr(signal, "SIGALRM"):
        signal.setitimer(signal.ITIMER_REAL, 0)


def pytest_runtest_logreport(report) -> None:
    if not _result_path():
        return

    record = _pending.setdefault(
        report.nodeid,
        {"nodeid": report.nodeid, "outcome": "passed", "duration_s": 0.0, "message": ""},
    )
    record["duration_s"] += float(getattr(report, "duration", 0.0) or 0.0)

    if report.failed:
        message = _short_message(report)
        if TIMEOUT_MARKER in message:
            record["outcome"] = "timeout"
        else:
            # A failure outside the call phase is a harness error, not a failed
            # assertion, and the report should keep the two apart.
            record["outcome"] = "failed" if report.when == "call" else "error"
        if not record["message"]:
            record["message"] = message
    elif report.skipped and record["outcome"] == "passed":
        record["outcome"] = "skipped"
        record["message"] = _short_message(report)

    if report.when == "teardown":
        record["duration_s"] = round(record["duration_s"], 4)
        _append_record(record)
        _pending.pop(report.nodeid, None)


def pytest_sessionfinish(session, exitstatus) -> None:
    # Anything still pending never reached teardown, which means the run was
    # interrupted. Record what is known rather than losing it.
    for record in list(_pending.values()):
        record["duration_s"] = round(record["duration_s"], 4)
        _append_record(record)
    _pending.clear()
