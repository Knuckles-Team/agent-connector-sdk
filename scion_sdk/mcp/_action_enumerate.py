"""Enumerate the actions of an action-routed tool and locate their branches."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
import typing
from collections.abc import Callable
from typing import Any, Literal, get_args, get_origin

_COMPARE = re.compile(r"""\baction\s*==\s*["']([a-z][a-z0-9_]*)["']""")
_QUOTED = re.compile(r"'([a-z][a-z0-9_]*)'")
_LISTED = re.compile(
    r"one of:\s*([a-z][a-z0-9_]*(?:\s*,\s*(?:or\s+)?[a-z][a-z0-9_]*)+)", re.IGNORECASE
)
_LISTED_NAME = re.compile(r"[a-z][a-z0-9_]*")
_DISCOVERY = frozenset({"list_actions", "help", "actions"})


def _source(fn: Callable[..., Any]) -> str:
    try:
        return textwrap.dedent(inspect.getsource(inspect.unwrap(fn)))
    except (OSError, TypeError):
        return ""


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _function_body(fn: Any) -> ast.AST | None:
    source = _source(fn) if callable(fn) and hasattr(fn, "__code__") else ""
    try:
        return ast.parse(source) if source else None
    except SyntaxError:
        return None


def _type_hints(fn: Any) -> dict[str, Any]:
    try:
        return typing.get_type_hints(fn, include_extras=True)
    except Exception:
        return {}


def _declared_actions(fn: Any, prop: dict[str, Any]) -> list[str]:
    """Actions named by the ``action`` Literal annotation and the schema enum."""
    found: list[str] = []
    annotation = _type_hints(fn).get("action") if fn is not None else None
    if get_origin(annotation) is typing.Annotated:
        annotation = get_args(annotation)[0]
    if get_origin(annotation) is Literal:
        found += [str(item) for item in get_args(annotation)]
    return found + [str(item) for item in prop.get("enum") or []]


def tool_actions(tool: Any) -> list[str]:
    """Every action an action-routed tool implements, in declaration order."""
    fn = getattr(tool, "fn", None)
    prop = (
        (getattr(tool, "parameters", None) or {})
        .get("properties", {})
        .get("action", {})
    )
    found = _declared_actions(fn, prop)
    if fn is not None:
        found += _COMPARE.findall(_source(fn))
    found += _described_actions(str(prop.get("description", "")))
    seen: list[str] = []
    for name in found:
        if name not in seen and name not in _DISCOVERY:
            seen.append(name)
    return seen


def _described_actions(description: str) -> list[str]:
    """Actions an ``action`` description lists: quoted names, else ``One of: a, b``."""
    quoted = _QUOTED.findall(description)
    if quoted:
        return list(quoted)
    match = _LISTED.search(description)
    if match is None:
        return []
    return [name for name in _LISTED_NAME.findall(match.group(1)) if name != "or"]


def _compared_action(test: ast.expr) -> str | None:
    """The string ``x`` of an ``action == "x"`` test, else ``None``."""
    if not (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "action"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and isinstance(test.comparators[0], ast.Constant)
    ):
        return None
    value = test.comparators[0].value
    return value if isinstance(value, str) else None


def _branches(fn: Callable[..., Any]) -> dict[str, ast.AST]:
    """Map each ``action == "x"`` test in ``fn`` to the branch it guards."""
    try:
        tree = ast.parse(_source(fn))
    except SyntaxError:
        return {}
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        action = _compared_action(node.test) if isinstance(node, ast.If) else None
        if action is not None and isinstance(node, ast.If):
            out.setdefault(action, ast.Module(body=node.body, type_ignores=[]))
    return out
