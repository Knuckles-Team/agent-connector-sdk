"""Opt-in per-client-method MCP tool derivation (SDK-CONNECTOR-CONTROL-R026)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from agent_connector_sdk.mcp.method_tools import register_method_tools
from agent_connector_sdk.mcp.tool_surface import GRANULAR_TAG, registered_tools


class DemoApiBase:
    def authenticate(self) -> None:
        """Infrastructure, never a tool."""


class DemoApiItems(DemoApiBase):
    def get_item(self, item_id: str) -> dict[str, str]:
        """Fetch one item."""
        return {"id": item_id}

    def delete_item(self, item_id: str) -> dict[str, str]:
        """Delete one item."""
        return {"deleted": item_id}


class DemoApiUsers(DemoApiItems):
    def list_users(self) -> list[str]:
        """List users."""
        return ["u1"]


def get_client() -> DemoApiUsers:
    return DemoApiUsers()


async def get_client_async() -> DemoApiUsers:
    return DemoApiUsers()


class _AcceptingContext:
    async def elicit(self, _message: str, response_type: Any) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(action="accept", data=True)


class _DecliningContext:
    async def elicit(self, _message: str, response_type: Any) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(action="decline", data=False)


def test_registers_one_tool_per_public_method_with_domain_tags() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    names = register_method_tools(mcp, DemoApiUsers, get_client, prefix="demo")
    assert set(names) == {"demo_get_item", "demo_delete_item", "demo_list_users"}
    tools = registered_tools(mcp)
    assert {GRANULAR_TAG, "items"} <= tools["demo_get_item"].tags
    assert {GRANULAR_TAG, "users"} <= tools["demo_list_users"].tags


def test_base_infrastructure_method_is_excluded() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    register_method_tools(mcp, DemoApiUsers, get_client, prefix="demo")
    assert "demo_authenticate" not in registered_tools(mcp)


def test_no_doubled_prefix_when_method_already_carries_it() -> None:
    class PrefixedApi:
        def postiz_create_post(self) -> str:
            """Create a post."""
            return "ok"

    mcp: FastMCP[Any] = FastMCP("demo")
    names = register_method_tools(
        mcp, PrefixedApi, lambda: PrefixedApi(), prefix="postiz"
    )
    assert names == ["postiz_create_post"]


async def test_non_destructive_tool_dispatches_to_the_client() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    register_method_tools(mcp, DemoApiUsers, get_client, prefix="demo")
    async with Client(mcp) as client:
        result = await client.call_tool(
            "demo_get_item", {"params_json": json.dumps({"item_id": "abc"})}
        )
    assert json.loads(result.content[0].text) == {"id": "abc"}


async def test_destructive_tool_requires_confirmation() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    register_method_tools(mcp, DemoApiUsers, get_client, prefix="demo")
    tool = registered_tools(mcp)["demo_delete_item"]
    accepted = await tool.fn(
        params_json=json.dumps({"item_id": "x"}), ctx=_AcceptingContext()
    )
    assert accepted == {"deleted": "x"}
    declined = await tool.fn(
        params_json=json.dumps({"item_id": "x"}), ctx=_DecliningContext()
    )
    assert declined == {"cancelled": True, "operation": "delete_item"}
    unattended = await tool.fn(params_json=json.dumps({"item_id": "x"}), ctx=None)
    assert unattended == {"cancelled": True, "operation": "delete_item"}


async def test_async_get_client_is_awaited() -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    register_method_tools(mcp, DemoApiUsers, get_client_async, prefix="demo")
    async with Client(mcp) as client:
        result = await client.call_tool("demo_list_users", {})
    assert json.loads(result.content[0].text) == ["u1"]


@pytest.mark.parametrize("prefix", ["demo"])
def test_returns_names_for_every_public_method(prefix: str) -> None:
    mcp: FastMCP[Any] = FastMCP("demo")
    names = register_method_tools(mcp, DemoApiUsers, get_client, prefix=prefix)
    assert len(names) == 3
