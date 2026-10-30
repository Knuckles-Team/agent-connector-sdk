"""Decide whether an action branch only forwards one served operation."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any

from scion_sdk.mcp._action_enumerate import _names

#: Calls that adapt how an operation runs or is returned, never what it computes.
_ADAPTERS = frozenset(
    {
        "run_blocking",
        "partial",
        "to_thread",
        "_invoke",
        "invoke",
        "dict",
        "list",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "len",
        "min",
        "max",
        "sorted",
        "isinstance",
        "jsonable_result",
        "dumps",
        "loads",
    }
)


def _assigned(statement: ast.stmt) -> set[str]:
    targets: list[ast.AST] = []
    if isinstance(statement, ast.Assign):
        targets = list(statement.targets)
    elif isinstance(statement, ast.AnnAssign | ast.AugAssign):
        targets = [statement.target]
    return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}


def _operation_refs(node: ast.AST, operations: Mapping[str, str]) -> set[str]:
    """Served operation names referenced as ``<obj>.<operation>`` in ``node``."""
    return {
        n.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Attribute) and n.attr in operations
    }


def _transforms(
    node: ast.AST, tainted: set[str], operations: Mapping[str, str]
) -> bool:
    """Whether ``node`` feeds operation data through a computing function call."""
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        if call.func.id in _ADAPTERS:
            continue
        args = [*call.args, *(k.value for k in call.keywords)]
        if any(_operation_refs(a, operations) or _names(a) & tainted for a in args):
            return True
    return False


def _taint(statements: list[ast.stmt], operations: Mapping[str, str]) -> set[str]:
    """Names that hold operation data, propagated to a fixed point."""
    tainted: set[str] = set()
    while True:
        grown = set(tainted)
        for statement in statements:
            value = getattr(statement, "value", None)
            if value is not None and (
                _operation_refs(value, operations) or _names(value) & grown
            ):
                grown |= _assigned(statement)
        if grown == tainted:
            return tainted
        tainted = grown


def _branch_operation(
    branch: ast.AST | None, operations: Mapping[str, str]
) -> str | None:
    """The one served operation a branch returns unchanged, if it does.

    The branch references exactly one served operation, and the value it
    returns is that operation's result, possibly wrapped by adapters,
    attribute calls (``.model_dump()``) or a literal envelope. A statement
    whose value is not returned (a progress note, a mirror write) is a side
    effect, not a computation. A branch that passes operation data through a
    computing function is a capability of its own.
    """
    if branch is None:
        return None
    refs = _operation_refs(branch, operations)
    if len(refs) != 1:
        return None
    statements = [n for n in ast.walk(branch) if isinstance(n, ast.stmt)]
    tainted = _taint(statements, operations)
    for statement in statements:
        value = getattr(statement, "value", None)
        flows = isinstance(statement, ast.Return) or bool(_assigned(statement))
        if value is not None and flows and _transforms(value, tainted, operations):
            return None
    return refs.pop()


def _lambda_operation(fn: Any, operations: Mapping[str, str]) -> str | None:
    """The one served operation a handler lambda calls, when it calls nothing else.

    A lambda's source cannot be parsed on its own, so its code object is read:
    it names exactly one served operation and no other module function.
    """
    code = getattr(fn, "__code__", None)
    if code is None or getattr(fn, "__name__", "") != "<lambda>":
        return None
    names = set(code.co_names)
    served = names & set(operations)
    scope = getattr(fn, "__globals__", {})
    computing = {
        name
        for name in names - served
        if callable(scope.get(name)) and name not in _ADAPTERS
    }
    return served.pop() if len(served) == 1 and not computing else None
