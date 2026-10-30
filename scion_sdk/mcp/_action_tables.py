"""Find the action tables an action-routed tool dispatches through."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from scion_sdk.mcp._action_dataflow import _branch_operation, _lambda_operation
from scion_sdk.mcp._action_enumerate import _function_body


def _closure_values(value: Any) -> Iterator[Any]:
    """The contents of ``value``'s closure cells that are filled."""
    for cell in getattr(value, "__closure__", None) or ():
        try:
            yield cell.cell_contents
        except ValueError:
            continue


def _cell_strings(value: Any) -> Iterator[str]:
    """String constants an action-table entry names (directly or in a closure)."""
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, tuple | list):
        children: Any = value
    elif callable(value):
        children = [*_closure_values(value), *getattr(value, "args", ())]
    else:
        return
    for child in children:
        yield from _cell_strings(child)


def _action_call_args(call: ast.Call) -> list[ast.expr]:
    """The callee and arguments of a call that passes ``action`` along."""
    args = [call.func, *call.args, *(k.value for k in call.keywords)]
    return (
        args if any(isinstance(a, ast.Name) and a.id == "action" for a in args) else []
    )


def _delegates(fn: Callable[..., Any], tree: ast.AST) -> list[Any]:
    """Module functions ``fn`` hands its ``action`` to (``h(..., action, ...)``)."""
    scope = getattr(inspect.unwrap(fn), "__globals__", {})
    found: list[Any] = []
    for call in ast.walk(tree):
        args = _action_call_args(call) if isinstance(call, ast.Call) else []
        for arg in args:
            target = scope.get(arg.id) if isinstance(arg, ast.Name) else None
            if inspect.isfunction(target) and target is not fn:
                found.append(target)
    return found


def _global_candidates(owners: list[Any]) -> list[Any]:
    return [
        getattr(owner, "__globals__", {}).get(name)
        for owner in owners
        for name in getattr(getattr(owner, "__code__", None), "co_names", ())
    ]


def _is_action_table(table: Any, actions: list[str]) -> bool:
    return (
        isinstance(table, dict)
        and bool(table)
        and all(isinstance(key, str) for key in table)
        and bool(set(actions) & set(table))
    )


def _action_tables(fn: Callable[..., Any], actions: list[str]) -> list[dict[str, Any]]:
    """``{action: method}`` tables the tool body refers to (globals or closure)."""
    target = inspect.unwrap(fn)
    tree = _function_body(target)
    owners = [target] + (_delegates(target, tree) if tree is not None else [])
    candidates = [*_global_candidates(owners), *_closure_values(target)]
    return [table for table in candidates if _is_action_table(table, actions)]


def _entry_operations(entry: Any, operations: Mapping[str, str]) -> list[str] | None:
    """Served operations one table entry dispatches to, or ``None`` if unknown."""
    handler = _branch_operation(_function_body(entry), operations)
    if handler is None:
        handler = _lambda_operation(entry, operations)
    if handler is not None:
        return [handler]
    if not hasattr(entry, "__code__") or getattr(entry, "__closure__", None):
        return [m for m in _cell_strings(entry) if m in operations]
    return None


def _table_operations(
    tables: list[dict[str, Any]], action: str, operations: Mapping[str, str]
) -> list[str]:
    """Served operations a table entry dispatches ``action`` to.

    An entry is a method name, a selector closing over method names, or a
    handler function whose body returns one served operation unchanged.
    """
    for table in tables:
        if action not in table:
            continue
        found = _entry_operations(table[action], operations)
        if found is not None:
            return found
    return []
