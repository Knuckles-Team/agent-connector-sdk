"""Action tables written as dict literals inside the tool body."""

from __future__ import annotations

import ast
from collections.abc import Callable, Mapping
from typing import Any

from scion_sdk.mcp._action_dataflow import _operation_refs
from scion_sdk.mcp._action_enumerate import _function_body
from scion_sdk.mcp._action_tables import _delegates


def _string_dict_entries(node: ast.AST) -> list[tuple[str, ast.AST]]:
    """The entries of a dict literal whose keys are all strings."""
    if not isinstance(node, ast.Dict) or not node.keys:
        return []
    keys = [k.value if isinstance(k, ast.Constant) else None for k in node.keys]
    if not all(isinstance(k, str) for k in keys):
        return []
    return [(str(k), v) for k, v in zip(keys, node.values, strict=True)]


def _literal_tables(fn: Callable[..., Any]) -> dict[str, ast.AST]:
    """``{action: entry}`` from dict literals in ``fn`` or a function it delegates to.

    A dict literal whose keys are all strings, such as
    ``{"get_settings": client.get_org_settings, ...}``, is an action table.
    """
    tree = _function_body(fn)
    if tree is None:
        return {}
    trees = [tree] + [t for d in _delegates(fn, tree) if (t := _function_body(d))]
    out: dict[str, ast.AST] = {}
    for node in (n for t in trees for n in ast.walk(t)):
        for key, value in _string_dict_entries(node):
            out.setdefault(key, value)
    return out


def _literal_operation(
    entries: dict[str, ast.AST], action: str, operations: Mapping[str, str]
) -> str | None:
    """The one served operation a literal table entry references."""
    entry = entries.get(action)
    refs = _operation_refs(entry, operations) if entry is not None else set()
    return refs.pop() if len(refs) == 1 else None
