"""pytest plugin that exports collection and result data as JSON.

Loaded with `-p src.pytest_tb_plugin`. Writing exact `report.nodeid` values
here is what lets the scheduler validate every id it later passes back to
pytest, instead of reconstructing ids from junit-xml class names.

The plugin stays inert unless TB_COLLECT_OUT or TB_RESULT_OUT is set, so it is
safe to leave on any pytest invocation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

COLLECT_ENV = "TB_COLLECT_OUT"
RESULT_ENV = "TB_RESULT_OUT"

MAX_MESSAGE_CHARS = 1500

_results: dict[str, dict] = {}


def _write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _first_doc_line(item) -> str:
    try:
        doc = item.obj.__doc__
    except Exception:  # fixtures or non-python items have no callable object
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
    if isinstance(longrepr, tuple):  # skip reports carry (path, lineno, reason)
        text = str(longrepr[-1])
    else:
        text = str(longrepr)
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


def pytest_runtest_logreport(report) -> None:
    if not os.environ.get(RESULT_ENV):
        return

    record = _results.setdefault(
        report.nodeid,
        {"nodeid": report.nodeid, "outcome": "passed", "duration_s": 0.0, "message": ""},
    )
    record["duration_s"] += float(getattr(report, "duration", 0.0) or 0.0)

    if report.failed:
        # A failure outside the call phase is an error in the harness, not in
        # the assertion, and the report should keep them apart.
        outcome = "failed" if report.when == "call" else "error"
        record["outcome"] = outcome
        if not record["message"]:
            record["message"] = _short_message(report)
    elif report.skipped and record["outcome"] == "passed":
        record["outcome"] = "skipped"
        record["message"] = _short_message(report)


def pytest_sessionfinish(session, exitstatus) -> None:
    out = os.environ.get(RESULT_ENV)
    if not out:
        return
    _write_json(
        out,
        {"exit_status": int(exitstatus), "results": list(_results.values())},
    )
