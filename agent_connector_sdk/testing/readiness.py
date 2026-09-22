"""Shared readiness behavior for in-memory testing ports."""

from __future__ import annotations

from agent_connector_sdk.ports.sink import SinkReadiness


async def _in_memory_readiness(_sink: object) -> SinkReadiness:
    """An in-memory fixture has no unavailable external dependency."""
    return SinkReadiness(ready=True)
