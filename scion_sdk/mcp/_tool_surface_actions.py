"""Action-tool settlement for :mod:`scion_sdk.mcp.tool_surface`."""

from __future__ import annotations

from typing import Any

from scion_sdk.mcp._tool_surface_base import (
    ACTION_DISPATCH_TAG,
    _flat_operations,
    _is_action_dispatch,
    _split_registered,
    registered_tools,
)
from scion_sdk.mcp.action_split import SPLIT_ACTION_TAG
from scion_sdk.mcp.method_tools import operation_tool_names


def _settle_action_tools(
    mcp: Any, *, clients: dict[Any, dict[str, str]], keep: bool
) -> None:
    """Keep (``keep``) or split every action-routed registrar tool; never drop one.

    ``clients`` maps each served client class and factory to ``{method: tool}`` for
    the operation tools about to be served; a split action that duplicates one
    is covered by it and recorded in the registration report.
    """
    operations = _flat_operations(clients)
    for name, tool in list(registered_tools(mcp).items()):
        if not _is_action_dispatch(tool) or SPLIT_ACTION_TAG in (tool.tags or set()):
            continue
        if keep:
            tool.tags.add(ACTION_DISPATCH_TAG)
        else:
            _split_registered(mcp, name, tool, operations=operations, clients=clients)


def _operation_methods(
    *,
    prefix: str,
    client_cls: type | None,
    get_client: Any,
    manifest: list[dict[str, Any]] | None,
    verbose_targets: list[dict[str, Any]] | None,
) -> dict[Any, dict[str, str]]:
    """``{client class or factory: {method: tool_name}}`` for every operation tool."""
    targets = (
        [(client_cls, get_client, prefix, manifest)] if client_cls is not None else []
    )
    targets += [
        (
            t["client_cls"],
            t.get("get_client"),
            str(t.get("prefix") or prefix),
            t.get("manifest"),
        )
        for t in verbose_targets or []
        if "client_cls" in t
    ]
    clients: dict[Any, dict[str, str]] = {}
    for cls, factory, target_prefix, target_manifest in targets:
        names = operation_tool_names(
            cls, prefix=target_prefix, manifest=target_manifest
        )
        clients.setdefault(cls, names)
        if factory is not None:
            clients.setdefault(factory, names)
    return clients
