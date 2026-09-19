"""Extract what a diff actually changed.

Produces changed file paths plus the enclosing function and class names, which
is what both the non-AI file rule and the later model prompt need. Diffs are
capped so an enormous PR cannot blow up the prompt or the runtime.
"""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from src import config

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

MAX_FILES = 40
MAX_SYMBOLS_PER_FILE = 12
MAX_DIFF_CHARS = 2000


class ChangeAnalysisError(RuntimeError):
    """Raised when git could not describe the change."""


@dataclass
class ChangedFile:
    path: str
    status: str
    added_lines: int = 0
    removed_lines: int = 0
    symbols: list[str] = field(default_factory=list)

    @property
    def stem(self) -> str:
        return Path(self.path).stem

    @property
    def is_python(self) -> bool:
        return self.path.endswith(".py")

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "status": self.status,
            "added_lines": self.added_lines,
            "removed_lines": self.removed_lines,
            "symbols": self.symbols,
        }


@dataclass
class ChangeSet:
    base: str
    head: str
    files: list[ChangedFile] = field(default_factory=list)
    truncated: bool = False
    diff_text: str = ""

    def is_empty(self) -> bool:
        return not self.files

    def paths(self) -> list[str]:
        return [changed.path for changed in self.files]

    def all_symbols(self) -> list[str]:
        seen: dict[str, None] = {}
        for changed in self.files:
            for symbol in changed.symbols:
                seen.setdefault(symbol, None)
        return list(seen)

    def to_dict(self) -> dict:
        return {
            "base": self.base,
            "head": self.head,
            "truncated": self.truncated,
            "files": [changed.to_dict() for changed in self.files],
        }

    def diff_excerpt(self, max_chars: int = MAX_DIFF_CHARS) -> str:
        if len(self.diff_text) <= max_chars:
            return self.diff_text
        return self.diff_text[:max_chars] + "\n... (diff truncated)"

    def summary(self) -> str:
        parts = []
        for changed in self.files:
            symbols = f" ({', '.join(changed.symbols)})" if changed.symbols else ""
            parts.append(f"{changed.path} [{changed.status}]{symbols}")
        return "; ".join(parts)


def _git(args: list[str], root: Path) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ChangeAnalysisError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def _changed_line_numbers(base: str, head: str, path: str, root: Path) -> set[int]:
    """Line numbers touched on the head side, from a zero context diff."""
    try:
        diff = _git(["diff", "--unified=0", f"{base}..{head}", "--", path], root)
    except ChangeAnalysisError:
        return set()

    lines: set[int] = set()
    for row in diff.splitlines():
        match = HUNK_HEADER.match(row)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or 1)
        lines.update(range(start, start + count))
    return lines


def _enclosing_symbols(source: str, changed_lines: set[int]) -> list[str]:
    """Names of functions and classes whose body overlaps the changed lines."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    found: list[str] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            start = child.lineno
            end = getattr(child, "end_lineno", start)
            name = f"{prefix}{child.name}"
            if any(start <= line <= end for line in changed_lines):
                if name not in found:
                    found.append(name)
            walk(child, f"{name}.")

    walk(tree, "")
    return found[:MAX_SYMBOLS_PER_FILE]


def collect_changes(
    base: str,
    head: str = "HEAD",
    root: Path | None = None,
    max_files: int = MAX_FILES,
) -> ChangeSet:
    root = Path(root) if root else config.ROOT

    raw = _git(["diff", "--numstat", f"{base}..{head}"], root)
    statuses = {}
    for row in _git(["diff", "--name-status", f"{base}..{head}"], root).splitlines():
        parts = row.split("\t")
        if len(parts) >= 2:
            statuses[parts[-1]] = parts[0][0].lower()

    files: list[ChangedFile] = []
    rows = [row for row in raw.splitlines() if row.strip()]
    truncated = len(rows) > max_files

    for row in rows[:max_files]:
        added, removed, path = (row.split("\t") + ["", "", ""])[:3]
        changed = ChangedFile(
            path=path,
            status=statuses.get(path, "m"),
            added_lines=int(added) if added.isdigit() else 0,
            removed_lines=int(removed) if removed.isdigit() else 0,
        )
        if changed.is_python and changed.status != "d":
            changed_lines = _changed_line_numbers(base, head, path, root)
            try:
                source = _git(["show", f"{head}:{path}"], root)
            except ChangeAnalysisError:
                source = ""
            if source and changed_lines:
                changed.symbols = _enclosing_symbols(source, changed_lines)
        files.append(changed)

    try:
        diff_text = _git(["diff", "--unified=3", f"{base}..{head}"], root)
    except ChangeAnalysisError:
        diff_text = ""

    return ChangeSet(
        base=base, head=head, files=files, truncated=truncated, diff_text=diff_text
    )


def collect_working_tree_changes(root: Path | None = None) -> ChangeSet:
    """Uncommitted changes, so the tool is usable before a PR exists."""
    root = Path(root) if root else config.ROOT
    raw = _git(["diff", "--numstat", "HEAD"], root)
    statuses = {}
    for row in _git(["diff", "--name-status", "HEAD"], root).splitlines():
        parts = row.split("\t")
        if len(parts) >= 2:
            statuses[parts[-1]] = parts[0][0].lower()

    files = []
    for row in raw.splitlines():
        if not row.strip():
            continue
        added, removed, path = (row.split("\t") + ["", "", ""])[:3]
        changed = ChangedFile(
            path=path,
            status=statuses.get(path, "m"),
            added_lines=int(added) if added.isdigit() else 0,
            removed_lines=int(removed) if removed.isdigit() else 0,
        )
        if changed.is_python and changed.status != "d":
            diff = _git(["diff", "--unified=0", "HEAD", "--", path], root)
            changed_lines: set[int] = set()
            for line in diff.splitlines():
                match = HUNK_HEADER.match(line)
                if match:
                    start = int(match.group(1))
                    count = int(match.group(2) or 1)
                    changed_lines.update(range(start, start + count))
            source_path = root / path
            if source_path.exists() and changed_lines:
                changed.symbols = _enclosing_symbols(
                    source_path.read_text(encoding="utf-8"), changed_lines
                )
        files.append(changed)

    try:
        diff_text = _git(["diff", "--unified=3", "HEAD"], root)
    except ChangeAnalysisError:
        diff_text = ""

    return ChangeSet(base="HEAD", head="working-tree", files=files, diff_text=diff_text)
