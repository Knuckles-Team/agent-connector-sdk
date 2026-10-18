"""Unit coverage for splitting action-routed tools (SDK-CONNECTOR-CONTROL-R020)."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import pytest
from fastmcp import FastMCP

from agent_connector_sdk.mcp.action_split import (
    SPLIT_ACTION_TAG,
    split_action_tool,
    tool_actions,
)


def _server() -> FastMCP[Any]:
    mcp: FastMCP[Any] = FastMCP("split")

    @mcp.tool()
    def demo(
        action: Literal["status", "purge"], target: str = "", force: bool = False
    ) -> str:
        """Demo."""
        if action == "status":
            return f"ok {target}"
        if action == "purge":
            return f"purged {force}"
        return "unknown"

    return mcp


def _tools(mcp: FastMCP[Any]) -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(mcp.local_provider.list_tools())}


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R020")
def test_tool_actions_reads_literal_and_branches() -> None:
    assert tool_actions(_tools(_server())["demo"]) == ["status", "purge"]


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R020")
def test_split_trims_parameters_and_tags_tools() -> None:
    mcp = _server()
    added = split_action_tool(mcp, "demo", _tools(mcp)["demo"], operations=set())
    tools = _tools(mcp)
    assert added == ["demo_status", "demo_purge"] and "demo" not in tools
    assert set(tools["demo_status"].parameters["properties"]) == {"target"}
    assert set(tools["demo_purge"].parameters["properties"]) == {"force"}
    assert SPLIT_ACTION_TAG in tools["demo_purge"].tags
    assert tools["demo_purge"].annotations.destructiveHint is True
    assert tools["demo_status"].annotations.readOnlyHint is True
