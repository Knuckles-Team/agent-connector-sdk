"""Reach served ``source.*`` operations as MCP tools on an authenticated session."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["McpSourceTransport"]


class McpSourceTransport:
    """Calls ``<prefix>_<operation>`` through a connected FastMCP client.

    The session already carries the authenticated caller; no caller identity
    is ever an argument of a client method.
    """

    def __init__(self, session: Any, *, prefix: str = "source") -> None:
        self._session = session
        self._prefix = prefix

    async def call(
        self, operation: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        result = await self._session.call_tool(
            f"{self._prefix}_{operation}", dict(payload)
        )
        data = result.structured_content
        if not isinstance(data, Mapping):
            raise TypeError("served source operation returned no structured reply")
        return data
