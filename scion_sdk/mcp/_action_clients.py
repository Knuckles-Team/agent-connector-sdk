"""Find the served client a generic action router dispatches to."""

from __future__ import annotations

import ast
import inspect
import typing
from collections.abc import Mapping
from typing import Any

from scion_sdk.mcp._action_enumerate import _function_body


def _returned_class(factory: Any) -> Any:
    """The class a client factory's return annotation names, or ``None``."""
    try:
        return typing.get_type_hints(factory).get("return")
    except Exception:
        return None


def _called_factories(tree: ast.AST, scope: Mapping[str, Any]) -> dict[str, Any]:
    """Variables assigned from a call to a known module-level factory."""
    factories: dict[str, Any] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        factory = scope.get(func.id) if isinstance(func, ast.Name) else None
        if not callable(factory):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                factories[target.id] = factory
    return factories


def _injected_factories(fn: Any) -> dict[str, Any]:
    """Parameters whose default is a dependency-injected factory."""
    factories: dict[str, Any] = {}
    for name, param in inspect.signature(fn).parameters.items():
        factory = getattr(param.default, "dependency", None)
        if callable(factory):
            factories[name] = factory
    return factories


def _client_factories(fn: Any, tree: ast.AST) -> dict[str, list[Any]]:
    """``{variable: [factory, returned class]}`` for clients ``fn`` builds or injects."""
    scope = getattr(inspect.unwrap(fn), "__globals__", {})
    factories = {**_called_factories(tree, scope), **_injected_factories(fn)}
    return {name: [f, _returned_class(f)] for name, f in factories.items()}


def _hashable_in(key: Any, mapping: Mapping[Any, Any]) -> bool:
    try:
        return key is not None and key in mapping
    except TypeError:
        return False


def _action_arg_names(call: ast.Call) -> set[str]:
    """Names passed to ``call`` when one of them is ``action``, else empty."""
    args = [*call.args, *(k.value for k in call.keywords)]
    names = {a.id for a in args if isinstance(a, ast.Name)}
    return names if "action" in names else set()


def _dispatched_client(
    fn: Any, clients: Mapping[Any, Mapping[str, str]]
) -> Mapping[str, str] | None:
    """Operations of the one served client a generic router dispatches to.

    A router whose actions are any method of a client (``getattr(client,
    action)`` or ``dispatch(client, action, ...)``) serves exactly that
    client's operations, each already served as its own tool.
    """
    tree = _function_body(fn)
    if tree is None:
        return None
    factories = _client_factories(fn, tree)
    matches: list[Mapping[str, str]] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        for name in _action_arg_names(call) & set(factories):
            found = [clients[k] for k in factories[name] if _hashable_in(k, clients)]
            matches += [m for m in found[:1] if m not in matches]
    return matches[0] if len(matches) == 1 else None
