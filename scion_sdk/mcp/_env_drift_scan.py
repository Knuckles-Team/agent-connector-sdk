"""Source walking and literal-extraction primitives for :mod:`scion_sdk.mcp.env_drift`."""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterator
from pathlib import Path

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")

_WALK_SKIP_DIRS = frozenset(
    {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".venv",
     "__pycache__", "build", "dist", "node_modules"}
)  # fmt: skip
_NON_RUNTIME_SOURCE_DIRS = frozenset(
    {"docs", "examples", "reports", "scripts", "test", "tests"}
)
#: These modules spell reader calls in prose; never scan them as readers.
_SELF_DOC_FILES = frozenset(
    {
        "env_drift.py",
        "check_env_var_drift.py",
        "_env_drift_scan.py",
        "_env_drift_reads.py",
        "_env_drift_families.py",
        "_env_drift_declared.py",
    }
)


def _walk_files(root: Path, *, suffix: str) -> list[Path]:
    """Source files under ``root``, pruning dependency and cache trees."""
    found: list[Path] = []
    for directory, names, files in os.walk(root):
        names[:] = sorted(
            n for n in names if n not in _WALK_SKIP_DIRS and not n.startswith(".")
        )
        found.extend(Path(directory) / n for n in files if n.endswith(suffix))
    return sorted(found)


def _skip_runtime_file(root: Path, py: Path) -> bool:
    try:
        parts = py.relative_to(root).parts
    except ValueError:
        parts = py.parts
    if any(part in _NON_RUNTIME_SOURCE_DIRS for part in parts[:-1]):
        return True
    return py.name in _SELF_DOC_FILES


def _parse(py: Path) -> ast.AST | None:
    try:
        return ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return None


def _runtime_trees(root: Path) -> Iterator[ast.AST]:
    """The parsed runtime ``*.py`` modules under ``root``."""
    for py in _walk_files(root, suffix=".py"):
        if _skip_runtime_file(root, py):
            continue
        tree = _parse(py)
        if tree is not None:
            yield tree


def _literal_str(node: ast.AST | None) -> str | None:
    """The string value of a string-constant node, else ``None``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_env_name(node: ast.AST | None) -> str | None:
    """The string value of ``node`` when it looks like an env var name."""
    value = _literal_str(node)
    return value if value and _ENV_NAME.fullmatch(value) else None


def _assign_pairs(node: ast.AST) -> tuple[list[ast.expr], ast.expr] | None:
    """``(targets, value)`` of a valued assignment node, else ``None``."""
    if isinstance(node, ast.Assign):
        return node.targets, node.value
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return [node.target], node.value
    return None


def _target_name(target: ast.AST) -> str | None:
    """The bare name of a ``Name`` or ``Attribute`` assignment target."""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _function_params(tree: ast.AST) -> dict[str, list[str]]:
    return {
        node.name: [a.arg for a in node.args.posonlyargs]
        + [a.arg for a in node.args.args]
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _attr_assignments(node: ast.AST, attr: str) -> list[tuple[str, ast.expr]]:
    """``(function, value)`` per ``function.<attr> = value`` target."""
    if not isinstance(node, ast.Assign):
        return []
    return [
        (t.value.id, node.value)
        for t in node.targets
        if isinstance(t, ast.Attribute)
        and isinstance(t.value, ast.Name)
        and t.attr == attr
    ]
