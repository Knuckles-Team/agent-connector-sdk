"""Literal env-var reads found in parsed modules, for :mod:`scion_sdk.mcp.env_drift`."""

from __future__ import annotations

import ast
from pathlib import Path

from scion_sdk.mcp._env_drift_scan import (
    _assign_pairs,
    _literal_env_name,
    _runtime_trees,
    _target_name,
)


def _is_environ(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "environ"
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
        and node.attr == "environ"
    )


def _is_env_reader_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in {"_setting", "setting", "getenv"}
    if isinstance(func, ast.Attribute):
        if func.attr == "getenv":
            return isinstance(func.value, ast.Name) and func.value.id == "os"
        return func.attr == "get" and _is_environ(func.value)
    return False


def _is_field_call(node: ast.Call) -> bool:
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "Field") or (
        isinstance(func, ast.Attribute) and func.attr == "Field"
    )


def _alias_literals(tree: ast.AST) -> dict[str, str]:
    """``NAME = "VAR"`` constants a reader may be passed instead of a literal."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        pair = _assign_pairs(node)
        name = _literal_env_name(pair[1]) if pair else None
        if pair is None or not name:
            continue
        for target in pair[0]:
            key = _target_name(target)
            if key:
                out[key] = name
    return out


def _name_of(node: ast.AST | None, aliases: dict[str, str]) -> str | None:
    literal = _literal_env_name(node)
    if literal:
        return literal
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Attribute):
        return aliases.get(node.attr)
    return None


def _call_names(node: ast.Call, aliases: dict[str, str]) -> set[str]:
    found: set[str] = set()
    if _is_env_reader_call(node) and node.args:
        name = _name_of(node.args[0], aliases)
        if name:
            found.add(name)
    if _is_field_call(node):
        aliased = (
            _literal_env_name(k.value) for k in node.keywords if k.arg == "alias"
        )
        found.update(name for name in aliased if name)
    return found


def _node_names(node: ast.AST, aliases: dict[str, str]) -> set[str]:
    if isinstance(node, ast.Call):
        return _call_names(node, aliases)
    if isinstance(node, ast.Subscript):
        loads = isinstance(node.ctx, ast.Load) and _is_environ(node.value)
        name = _name_of(node.slice, aliases) if loads else None
        return {name} if name else set()
    pair = _assign_pairs(node)
    if pair is None or not any(_target_name(t) == "enable_flag" for t in pair[0]):
        return set()
    name = _literal_env_name(pair[1])
    return {name} if name else set()


def _env_names_from_tree(tree: ast.AST) -> set[str]:
    """Literal configuration reads in one parsed module (writes excluded)."""
    aliases = _alias_literals(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        found |= _node_names(node, aliases)
    return found


def _scan_setting_calls(root: Path) -> set[str]:
    """Every literal env read in runtime ``*.py`` under ``root``."""
    found: set[str] = set()
    for tree in _runtime_trees(root):
        found.update(_env_names_from_tree(tree))
    return found


def _script_reads(root: Path) -> set[str]:
    """Reads in the package's own ``scripts/``: suppress DEAD, never UNDOCUMENTED."""
    scripts = root / "scripts"
    return _scan_setting_calls(scripts) if scripts.is_dir() else set()
