"""Cursor-connection helpers for the GraphQL client."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any


def _connection_at(data: Any, path: Sequence[str]) -> dict[str, Any] | None:
    """The connection object ``path`` keys below ``data``, or ``None``."""
    for key in path:
        data = data.get(key) if isinstance(data, dict) else None
    return data if isinstance(data, dict) else None


def _connection_nodes(connection: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Each node of a connection's ``nodes`` (or ``edges[].node``)."""
    nodes = connection.get("nodes")
    if nodes is None:
        nodes = [
            edge.get("node")
            for edge in connection.get("edges") or []
            if isinstance(edge, dict)
        ]
    for node in nodes or []:
        if isinstance(node, dict):
            yield node


def _next_cursor(connection: dict[str, Any]) -> str | None:
    """The ``endCursor`` when another page follows, else ``None``."""
    page_info = connection.get("pageInfo") or {}
    cursor = page_info.get("endCursor")
    return cursor if page_info.get("hasNextPage") and cursor else None
