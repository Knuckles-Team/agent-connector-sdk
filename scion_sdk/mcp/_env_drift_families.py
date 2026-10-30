"""Dynamic env-var families and registrar toggles, for :mod:`scion_sdk.mcp.env_drift`."""

from __future__ import annotations

import ast
from pathlib import Path

from scion_sdk.mcp._env_drift_scan import (
    _assign_pairs,
    _attr_assignments,
    _function_params,
    _literal_str,
    _runtime_trees,
    _target_name,
)

_DYNAMIC_ENV_PREFIX_ATTR = "dynamic_env_prefix_arg"
_DYNAMIC_ENV_SUFFIXES_ATTR = "dynamic_env_suffixes"
#: function name -> (prefix parameter, its position or None, suffixes)
DynamicFamily = tuple[str, "int | None", tuple[str, ...]]


def _dynamic_prefix(literal: str) -> str:
    return "".join(
        ch if ch.isalnum() else "_" for ch in str(literal or "").strip().upper()
    ).strip("_")


def _literal_strings(value: ast.expr) -> tuple[str, ...] | None:
    """The strings of a non-empty all-string tuple/list literal, else ``None``."""
    if not isinstance(value, ast.Tuple | ast.List):
        return None
    strings = [_literal_str(e) for e in value.elts]
    if not strings or any(item is None for item in strings):
        return None
    return tuple(item for item in strings if item is not None)


def _string_tuples(tree: ast.AST) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        pair = _assign_pairs(node)
        strings = _literal_strings(pair[1]) if pair else None
        if pair is None or strings is None:
            continue
        out.update({t.id: strings for t in pair[0] if isinstance(t, ast.Name)})
    return out


def _declared_suffixes(
    value: ast.expr, named: dict[str, tuple[str, ...]]
) -> tuple[str, ...] | None:
    if isinstance(value, ast.Name) and value.id in named:
        return named[value.id]
    if isinstance(value, ast.Tuple | ast.List):
        found = [s for e in value.elts if (s := _literal_str(e))]
        return tuple(found) if found else None
    return None


def _position(order: list[str], name: str) -> int | None:
    return order.index(name) if name in order else None


def _families_in_tree(tree: ast.AST) -> dict[str, DynamicFamily]:
    named = _string_tuples(tree)
    params = _function_params(tree)
    nodes = list(ast.walk(tree))
    prefix_args = {
        func: literal
        for node in nodes
        for func, value in _attr_assignments(node, _DYNAMIC_ENV_PREFIX_ATTR)
        if (literal := _literal_str(value))
    }
    suffixes = {
        func: declared
        for node in nodes
        for func, value in _attr_assignments(node, _DYNAMIC_ENV_SUFFIXES_ATTR)
        if (declared := _declared_suffixes(value, named))
    }
    return {
        func: (arg, _position(params.get(func, []), arg), suffixes[func])
        for func, arg in prefix_args.items()
        if func in suffixes
    }


def _scan_dynamic_families(root: Path) -> dict[str, DynamicFamily]:
    """Every dynamic-family declaration in runtime code under ``root``."""
    families: dict[str, DynamicFamily] = {}
    for tree in _runtime_trees(root):
        families.update(_families_in_tree(tree))
    return families


def _call_prefix(node: ast.Call, prefix_arg: str, position: int | None) -> str:
    """The family prefix literal passed to ``node``, normalised; ``""`` when absent."""
    literal = next(
        (_literal_str(k.value) for k in node.keywords if k.arg == prefix_arg), None
    )
    if literal is None and position is not None and len(node.args) > position:
        literal = _literal_str(node.args[position])
    return _dynamic_prefix(literal) if literal else ""


def _family_reads_for_call(
    node: ast.Call, families: dict[str, DynamicFamily]
) -> set[str]:
    name = _target_name(node.func)
    family = families.get(name) if name else None
    if family is None:
        return set()
    prefix_arg, position, suffixes = family
    prefix = _call_prefix(node, prefix_arg, position)
    return {f"{prefix}_{suffix}" for suffix in suffixes} if prefix else set()


def _scan_dynamic_family_reads(
    root: Path, families: dict[str, DynamicFamily]
) -> set[str]:
    """The concrete names composed by calls with a literal family prefix."""
    if not families:
        return set()
    found: set[str] = set()
    for tree in _runtime_trees(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                found.update(_family_reads_for_call(node, families))
    return found
