"""Fail closed on an MCP provider continuation that makes no progress."""

from collections.abc import Mapping
from typing import Any

from agent_connector_sdk.ports.errors import SourceContractError


def _require_cursor_progress(token: Any, position: Mapping[str, Any]) -> Any:
    if token == position.get("cursor"):
        raise SourceContractError("provider cursor did not advance")
    return token
