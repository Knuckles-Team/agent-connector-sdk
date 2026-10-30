"""Decide whether a served operation already covers an action."""

from __future__ import annotations

import ast
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from scion_sdk.mcp._action_dataflow import _branch_operation
from scion_sdk.mcp._action_literals import _literal_operation
from scion_sdk.mcp._action_tables import _table_operations


@dataclass(frozen=True)
class _Context:
    name: str
    prefix: str
    operations: Mapping[str, str]
    taken: Collection[str]
    branches: dict[str, ast.AST]
    tables: list[dict[str, Any]]
    literals: dict[str, ast.AST]


def _operation_cover(action: str, ctx: _Context) -> tuple[str, str] | None:
    if action in ctx.operations:
        return ctx.operations[action], "operation"
    method = _branch_operation(ctx.branches.get(action), ctx.operations)
    return (ctx.operations[method], "operation") if method is not None else None


def _table_cover(action: str, ctx: _Context) -> tuple[str, str] | None:
    from_table = _table_operations(ctx.tables, action, ctx.operations)
    if from_table:
        return ctx.operations[from_table[0]], "table"
    literal = _literal_operation(ctx.literals, action, ctx.operations)
    return (ctx.operations[literal], "table") if literal is not None else None


def _coverage(action: str, ctx: _Context) -> tuple[str, str] | None:
    """``(serving_tool, reason)`` when an operation already serves ``action``."""
    split = f"{ctx.prefix}_{action}"
    if split in ctx.taken:
        return split, "name"
    return _operation_cover(action, ctx) or _table_cover(action, ctx)
