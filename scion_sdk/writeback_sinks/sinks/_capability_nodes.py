"""Node accessors for the capability write-back sink."""

from __future__ import annotations

from typing import Any

from ..models import GraphNode


def _name_of(node: Any) -> str:
    props = node.props if isinstance(node, GraphNode) else (node.get("props") or node)
    nid = node.id if isinstance(node, GraphNode) else node.get("id")
    return str((props or {}).get("name") or nid)


def _node_props(node: Any) -> dict[str, Any]:
    return node.props if isinstance(node, GraphNode) else (node.get("props") or {})


def _type(node: Any) -> str:
    return node.type if isinstance(node, GraphNode) else str(node.get("type") or "")


def _should_push(node: Any) -> bool:
    """Only push provisional/code-derived capabilities (not mirrored upstream ones)."""
    if _type(node) != "BusinessCapability":
        return False
    p = _node_props(node)
    return bool(p.get("provisional") or p.get("derived_from"))
