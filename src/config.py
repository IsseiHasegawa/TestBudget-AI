"""Shared paths and defaults."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEMO_TARGET = "demo_project/tests"
HISTORY_PATH = ROOT / "data" / "duration_history.json"
ARTIFACT_DIR = ROOT / "artifacts"

PLUGIN_MODULE = "src.pytest_tb_plugin"

# Phase 3 turns this into a real scheduling budget. Phase 1 only uses it as the
# default wall-clock ceiling for a manual run.
DEFAULT_BUDGET_SECONDS = 3.0

# Duration estimates come from measurements, so they are predictions rather
# than guarantees. The scheduler keeps this much headroom per test.
DURATION_SAFETY_FACTOR = 1.3


def default_python() -> str:
    """Interpreter used to spawn pytest, defaulting to the current one."""
    return sys.executable


def subprocess_env(root: Path) -> dict[str, str]:
    """Environment for a spawned pytest.

    `-p src.pytest_tb_plugin` is resolved before any conftest runs, so the
    repository root has to be importable from the environment itself.
    """
    env = os.environ.copy()
    # ROOT makes the plugin importable; root makes the project under test importable.
    existing = env.get("PYTHONPATH", "")
    entries = dict.fromkeys(filter(None, [str(ROOT), str(root), existing]))
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env
