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
    added = split_action_tool(mcp, "demo", _tools(mcp)["demo"], operations={})
    tools = _tools(mcp)
    assert added == ["demo_status", "demo_purge"] and "demo" not in tools
    assert set(tools["demo_status"].parameters["properties"]) == {"target"}
    assert set(tools["demo_purge"].parameters["properties"]) == {"force"}
    assert SPLIT_ACTION_TAG in tools["demo_purge"].tags
    assert tools["demo_purge"].annotations.destructiveHint is True
    assert tools["demo_status"].annotations.readOnlyHint is True


def _split_server() -> FastMCP[Any]:
    mcp = _server()
    split_action_tool(mcp, "demo", _tools(mcp)["demo"], operations={})
    return mcp


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R020.5")
def test_split_tools_inherit_parent_and_per_action_class() -> None:
    from agent_connector_sdk.mcp.action_split import split_tool_classes

    mcp = _split_server()
    assert split_tool_classes(mcp, {"demo": "op"}) == {
        "demo_status": "op",
        "demo_purge": "op",
    }
    per_action = {"demo": {"status": "read", "purge": "mutate"}}
    assert split_tool_classes(mcp, per_action) == {
        "demo_status": "read",
        "demo_purge": "mutate",
    }


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R020.5")
def test_mutating_split_never_inherits_a_read_class() -> None:
    from agent_connector_sdk.mcp.action_split import (
        assert_tools_classified,
        split_tool_classes,
    )

    mcp = _split_server()
    got = split_tool_classes(mcp, {"demo": "read"}, read_classes={"read"})
    assert got == {"demo_status": "read"}
    with pytest.raises(RuntimeError, match="demo_purge"):
        assert_tools_classified(mcp, set(), {"demo": "read"}, read_classes={"read"})


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R020.5")
def test_unknown_and_undeclared_tools_stay_unclassified() -> None:
    from agent_connector_sdk.mcp.action_split import (
        assert_tools_classified,
        unclassified_tools,
    )

    mcp = _split_server()

    @mcp.tool()
    def stray() -> str:
        """Stray."""
        return "x"

    assert unclassified_tools(mcp, set(), {"demo": "op"}) == ["stray"]
    assert unclassified_tools(mcp, {"stray"}, {"demo": "op"}) == []
    with pytest.raises(RuntimeError, match="Unclassified MCP tools prevent startup"):
        assert_tools_classified(mcp, set())


@pytest.mark.spec("SDK-CONNECTOR-CONTROL-R020.5")
def test_parent_declared_read_only_passes_its_read_class_to_every_action() -> None:
    from agent_connector_sdk.mcp.action_split import split_tool_classes

    mcp: FastMCP[Any] = FastMCP("ro")

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def health(action: Literal["report", "faults", "raid"]) -> str:
        """Health."""
        if action == "report":
            return "r"
        if action == "faults":
            return "f"
        return "x"

    split_action_tool(mcp, "health", _tools(mcp)["health"], operations={})
    got = split_tool_classes(mcp, {"health": "read"}, read_classes={"read"})
    assert got == {f"health_{a}": "read" for a in ("report", "faults", "raid")}
