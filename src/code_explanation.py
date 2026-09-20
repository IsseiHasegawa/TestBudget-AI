"""Find statically visible Python call paths for test explanations.

A path proves that call expressions and imports were found in the source.
It does NOT prove that the path is executed in a particular test run.
"""

from __future__ import annotations

import ast
import os
from collections import deque
from pathlib import Path


EXCLUDED_DIRECTORIES = {
    ".git", ".venv", "venv", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", "site-packages",
}


def _project_python_files(source_root: Path):
    """Skip dependency directories when finding project Python files."""
    for directory, subdirectories, filenames in os.walk(source_root):
        subdirectories[:] = [
            name for name in subdirectories
            if name not in EXCLUDED_DIRECTORIES
        ]
        for filename in filenames:
            if filename.endswith(".py"):
                yield Path(directory) / filename


def _module_name(path: Path, source_root: Path) -> str:
    parts = path.relative_to(source_root).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(tree: ast.Module) -> dict[str, str]:
    """Resolve supported absolute imports to their qualified names."""
    result = {}

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                qualified = alias.name if alias.asname else local_name
                result[local_name] = qualified

        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module is None:
                continue

            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                result[local_name] = f"{node.module}.{alias.name}"

    return result


def _call_name(expression: ast.expr) -> str | None:
    """Extract a dotted name such as payment.processing_fee."""
    parts = []
    current = expression

    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value

    if not isinstance(current, ast.Name):
        return None

    parts.append(current.id)
    return ".".join(reversed(parts))


class _Calls(ast.NodeVisitor):
    def __init__(self, module: str, imports: dict[str, str]):
        self.module = module
        self.imports = imports
        self.callees: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name:
            first, *rest = name.split(".")
            if first in self.imports:
                qualified = ".".join([self.imports[first], *rest])
            else:
                qualified = f"{self.module}.{name}"
            self.callees.add(qualified)

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Do not treat calls inside a nested function as calls made
        # by the enclosing function.
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _build_call_graph(source_root: Path) -> tuple[dict, dict]:
    """Build the static graph once for the given source root."""
    # First collect function definitions and their module-level imports.
    functions = {}
    module_imports = {}

    for path in _project_python_files(source_root):
        if not path.is_file():
            continue

        module = _module_name(path, source_root)

        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
        except (SyntaxError, UnicodeError):
            continue

        module_imports[module] = _imports(tree)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[f"{module}.{node.name}"] = (module, node)

    # Resolve direct calls and supported cross-module imports.
    graph = {}

    for symbol, (module, function) in functions.items():
        visitor = _Calls(module, module_imports[module])

        for statement in function.body:
            visitor.visit(statement)

        graph[symbol] = {
            callee
            for callee in visitor.callees
            if callee in functions
        }

    return functions, graph


def find_static_call_path(
    source_root: Path,
    test_nodeid: str,
    changed_file: Path,
    changed_function: str,
    graph_cache: dict | None = None,
) -> list[str] | None:
    """Return a supported static path from a test to a changed function.

    None means no path was found by this limited analysis, NOT that
    the test is unrelated to the changed function.
    """
    source_root = source_root.resolve()
    test_path_text, separator, test_name = test_nodeid.partition("::")
    if not separator or not test_name.isidentifier():
        return None

    test_path = Path(test_path_text).resolve()
    changed_path = Path(changed_file).resolve()

    if not test_path.is_relative_to(source_root):
        return None
    if not changed_path.is_relative_to(source_root):
        return None

    test_symbol = f"{_module_name(test_path, source_root)}.{test_name}"
    changed_symbol = (
        f"{_module_name(changed_path, source_root)}.{changed_function}"
    )

    if graph_cache is None:
        functions, graph = _build_call_graph(source_root)
    else:
        if source_root not in graph_cache:
            graph_cache[source_root] = _build_call_graph(source_root)
        functions, graph = graph_cache[source_root]
    if test_symbol not in functions or changed_symbol not in functions:
        return None

    # Find a path through the static call graph.
    queue = deque([(test_symbol, [test_symbol])])
    visited = {test_symbol}

    while queue:
        current, path = queue.popleft()

        if current == changed_symbol:
            return path

        for callee in sorted(graph[current]):
            if callee not in visited:
                visited.add(callee)
                queue.append((callee, [*path, callee]))

    return None
