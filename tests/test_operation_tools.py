"""One typed, annotated MCP tool per API operation (SCION-CONNECTOR-CONTROL-R020)."""

from __future__ import annotations

import inspect
from typing import Any, Literal

import pytest
from fastmcp import Client, FastMCP
from pydantic import BaseModel

from agent_connector_sdk.mcp.method_tools import (
    GATED_TAG,
    GRANULAR_TAG,
    OPERATION_TAG,
    UNTYPED_TOOLS_ATTRIBUTE,
    jsonable_result,
    operation_annotations,
    operation_verb,
    register_method_tools,
)
from agent_connector_sdk.mcp.tool_surface import (
    ACTION_DISPATCH_TAG,
    gated_tool_names,
    operation_prefix,
    register_tool_surface,
)


class SampleBase:
    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Transport machinery, never a tool."""
        return {"method": method, "path": path, **kwargs}


class SampleApi(SampleBase):
    def get_widget(self, widget_id: str, expand: bool | None = None) -> Any:
        """Fetch one widget."""
        return self.request("GET", f"/widgets/{widget_id}", expand=expand)

    def create_widget(self, name: str, body: dict[str, Any] | None = None) -> Any:
        """Create a widget."""
        return self.request("POST", "/widgets", name=name, body=body)

    def replace_widget(self, widget_id: str, body: dict[str, Any]) -> Any:
        """Replace a widget."""
        return self.request("PUT", f"/widgets/{widget_id}", body=body)

    def delete_widget(self, widget_id: str) -> Any:
        """Delete a widget."""
        return self.request("DELETE", f"/widgets/{widget_id}")


class SearchModel(BaseModel):
    query: str
    limit: int = 10


class ModelledApi:
    def search_widgets(self, **kwargs: Any) -> Any:
        """Search widgets.

        GET /widgets/search
        """
        model = SearchModel(**kwargs)
        return model.model_dump()

    def untyped(self, **kwargs: Any) -> Any:
        """Pass-through with no typed surface."""
        return kwargs


EXPECTED = {
    "sample_get_widget": (True, False, True),
    "sample_create_widget": (False, False, False),
    "sample_replace_widget": (False, False, True),
    "sample_delete_widget": (False, True, True),
}


def register_condensed_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool()
    def sample_widgets(action: Literal["get_widget"], params_json: str = "{}") -> str:
        """Action-dispatch tool."""
        return action


def register_ingest_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool()
    def sample_ingest(limit: int = 5) -> int:
        """Not a client-method wrapper."""
        return limit


async def _listed(mcp: FastMCP[Any]) -> dict[str, Any]:
    async with Client(mcp) as client:
        return {tool.name: tool for tool in await client.list_tools()}


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020")
async def test_default_surface_is_one_typed_annotated_tool_per_operation() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp,
        service="sample-mcp",
        client_cls=SampleApi,
        get_client=SampleApi,
        registrars=[register_condensed_tools, register_ingest_tools],
    )
    tools = await _listed(mcp)
    assert set(tools) == set(EXPECTED) | {"sample_ingest"}
    for name, (read_only, destructive, idempotent) in EXPECTED.items():
        hints = tools[name].annotations
        assert hints.read_only_hint is read_only, name
        assert hints.destructive_hint is destructive, name
        assert hints.idempotent_hint is idempotent, name
    get_schema = tools["sample_get_widget"].input_schema
    assert get_schema["required"] == ["widget_id"]
    assert get_schema["properties"]["widget_id"] == {"type": "string"}
    assert "expand" in get_schema["properties"]
    assert tools["sample_replace_widget"].input_schema["required"] == [
        "widget_id",
        "body",
    ]
    assert tools["sample_create_widget"].description == "Create a widget."
    assert gated_tool_names(mcp) >= set(EXPECTED)
    assert getattr(mcp, UNTYPED_TOOLS_ATTRIBUTE) == set()


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020")
async def test_operation_tool_calls_the_client_with_typed_arguments() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp, service="sample-mcp", client_cls=SampleApi, get_client=SampleApi
    )
    async with Client(mcp) as client:
        result = await client.call_tool("sample_get_widget", {"widget_id": "w1"})
    assert result.data == {"method": "GET", "path": "/widgets/w1", "expand": None}


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020")
async def test_action_dispatch_is_opt_in_compatibility() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp,
        service="sample-mcp",
        client_cls=SampleApi,
        get_client=SampleApi,
        registrars=[register_condensed_tools],
        action_dispatch=True,
    )
    tools = await _listed(mcp)
    assert set(tools) == set(EXPECTED) | {"sample_widgets"}
    assert ACTION_DISPATCH_TAG in tools["sample_widgets"].meta["fastmcp"]["tags"]
    assert {OPERATION_TAG, GRANULAR_TAG, GATED_TAG} <= set(
        tools["sample_get_widget"].meta["fastmcp"]["tags"]
    )


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020")
async def test_registrars_alone_are_the_surface_without_a_client() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp, service="sample-mcp", registrars=[register_condensed_tools]
    )
    assert set(await _listed(mcp)) == {"sample_widgets"}


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020")
async def test_manifest_supplies_schema_name_description_and_verb() -> None:
    manifest = [
        {
            "method": "untyped",
            "name": "patch_widget",
            "http": "PATCH",
            "summary": "Patch a widget.",
            "parameters": [
                {
                    "name": "widgetId",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                },
                {"name": "dryRun", "in": "query", "schema": {"type": "boolean"}},
            ],
            "requestBody": {"required": True},
        }
    ]
    mcp: FastMCP[Any] = FastMCP("sample")
    names = register_method_tools(
        mcp, ModelledApi, ModelledApi, prefix="sample", manifest=manifest
    )
    tools = await _listed(mcp)
    assert set(names) == {"sample_patch_widget", "sample_search_widgets"}
    patch = tools["sample_patch_widget"]
    assert patch.description == "Patch a widget."
    assert patch.input_schema["required"] == ["widget_id", "body"]
    assert patch.input_schema["properties"]["dry_run"]["anyOf"][0] == {
        "type": "boolean"
    }
    assert patch.annotations.read_only_hint is False
    assert patch.annotations.idempotent_hint is False
    search = tools["sample_search_widgets"]
    assert search.input_schema["required"] == ["query"]
    assert search.annotations.read_only_hint is True
    async with Client(mcp) as client:
        result = await client.call_tool("sample_search_widgets", {"query": "q"})
    assert result.data == {"query": "q", "limit": 10}


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020")
async def test_operation_may_reuse_a_retired_action_tool_name() -> None:
    class WidgetsApi:
        def widgets(self) -> list[str]:
            """List widgets."""
            return []

    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp,
        service="sample-mcp",
        client_cls=WidgetsApi,
        get_client=WidgetsApi,
        registrars=[register_condensed_tools],
    )
    tools = await _listed(mcp)
    # The action tool's get_widget action is no served operation here, so it
    # is split (never dropped) and the operation reuses the freed name.
    assert set(tools) == {"sample_widgets", "sample_widgets_get_widget"}
    assert "action" not in tools["sample_widgets"].input_schema["properties"]
    with pytest.raises(ValueError, match="collides"):
        register_tool_surface(
            FastMCP("x"),
            service="sample-mcp",
            client_cls=WidgetsApi,
            get_client=WidgetsApi,
            registrars=[register_condensed_tools],
            action_dispatch=True,
        )


def test_bare_kwargs_method_falls_back_to_params_json_and_is_recorded() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_method_tools(mcp, ModelledApi, ModelledApi, prefix="sample")
    assert getattr(mcp, UNTYPED_TOOLS_ATTRIBUTE) == {"sample_untyped"}


def test_name_collision_and_malformed_manifest_fail() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_method_tools(mcp, SampleApi, SampleApi, prefix="sample")
    with pytest.raises(ValueError, match="collides"):
        register_method_tools(mcp, SampleApi, SampleApi, prefix="sample")
    with pytest.raises(ValueError, match="method"):
        register_method_tools(
            FastMCP("x"), SampleApi, SampleApi, prefix="s", manifest=[{}]
        )
    with pytest.raises(ValueError, match="duplicate"):
        register_method_tools(
            FastMCP("x"),
            SampleApi,
            SampleApi,
            prefix="s",
            manifest=[{"method": "get_widget"}, {"method": "get_widget"}],
        )
    with pytest.raises(ValueError, match="verbose target"):
        register_tool_surface(
            FastMCP("x"), service="s", verbose_targets=[{"client_cls": SampleApi}]
        )


def test_verb_and_name_classification() -> None:
    assert operation_verb(SampleApi.get_widget) == "GET"
    assert operation_verb(ModelledApi.search_widgets) == "GET"
    assert operation_verb(ModelledApi.untyped) is None
    assert operation_verb(ModelledApi.untyped, {"http": "delete"}) == "DELETE"
    listed = operation_annotations("list_widgets", None)
    assert listed.read_only_hint is True and listed.idempotent_hint is True
    removed = operation_annotations("remove_widget", None)
    assert removed.read_only_hint is False and removed.destructive_hint is True
    assert operation_prefix("home-assistant-agent") == "home_assistant"
    assert operation_prefix("jellyfin-mcp") == "jellyfin"
    assert operation_prefix("x", "custom") == "custom"


def test_default_result_coercion_is_json_ready() -> None:
    class Model(BaseModel):
        a: int

    class Raw:
        status_code = 204

    assert jsonable_result(Model(a=1)) == {"a": 1}
    assert jsonable_result(b"\x00\xff") == "AP8="
    assert jsonable_result({"r": Raw()}) == {"r": {"status_code": 204}}
    assert jsonable_result(inspect) == str(inspect)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020")
async def test_plain_json_return_hint_becomes_the_output_schema() -> None:
    class StatusApi:
        def get_status(self) -> dict[str, Any]:
            """Status."""
            return {"ok": True}

        def get_model(self) -> SearchModel:
            """A model the coercer reshapes."""
            return SearchModel(query="q")

    mcp: FastMCP[Any] = FastMCP("sample")
    register_method_tools(mcp, StatusApi, StatusApi, prefix="sample")
    tools = await _listed(mcp)
    assert tools["sample_get_status"].output_schema["type"] == "object"
    assert tools["sample_get_model"].output_schema is None
    async with Client(mcp) as client:
        result = await client.call_tool("sample_get_status", {})
    assert result.structured_content == {"ok": True}


class _Ledger:
    def get_balance(self, account: str) -> dict[str, Any]:
        """Read one balance."""
        return {"account": account, "balance": 10.0}


def register_analytic_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool()
    def sample_risk(
        action: Literal["get_balance", "kelly", "drawdown_check"],
        account: str = "",
        win_rate: float = 0.5,
        ratio: float = 1.5,
        drawdown: float = 0.0,
    ) -> dict[str, Any]:
        """Risk analytics."""
        if action == "get_balance":
            return _Ledger().get_balance(account)
        if action == "kelly":
            return {"fraction": win_rate - (1 - win_rate) / ratio}
        if action == "drawdown_check":
            return {"breached": drawdown > 0.1}
        return {"error": "unknown"}

    @mcp.tool()
    def sample_opaque(action: str, value: int = 0) -> int:
        """Actions cannot be enumerated from this tool."""
        return value


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020")
async def test_action_tools_are_split_never_dropped() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp,
        service="sample-mcp",
        client_cls=_Ledger,
        get_client=_Ledger,
        registrars=[register_analytic_tools],
    )
    tools = await _listed(mcp)
    # get_balance only passes the served operation through: covered by it.
    assert "sample_get_balance" in tools
    assert "sample_risk_get_balance" not in tools
    # Computed actions become typed tools with only the parameters they read.
    kelly = tools["sample_risk_kelly"].input_schema["properties"]
    assert set(kelly) == {"win_rate", "ratio"}
    assert set(tools["sample_risk_drawdown_check"].input_schema["properties"]) == {
        "drawdown"
    }
    assert tools["sample_risk_kelly"].annotations.read_only_hint is False
    assert tools["sample_risk_drawdown_check"].annotations.read_only_hint is True
    # A tool whose actions cannot be enumerated is kept whole, not dropped.
    assert "sample_opaque" in tools
    async with Client(mcp) as client:
        result = await client.call_tool(
            "sample_risk_kelly", {"win_rate": 0.6, "ratio": 2.0}
        )
    assert result.data == {"fraction": pytest.approx(0.4)}


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R026.2")
async def test_keyword_field_is_exposed_under_its_wire_name() -> None:
    class LogsApi:
        def search_logs(self, **kwargs: Any) -> dict[str, Any]:
            """Search logs."""
            return dict(kwargs)

    manifest = [
        {
            "method": "search_logs",
            "http": "POST",
            "path": "/logs/search",
            "summary": "Search logs.",
            "parameters": [
                {
                    "name": "from",
                    "python_name": "from_",
                    "in": "body",
                    "schema": {"type": "integer"},
                },
                {
                    "name": "in",
                    "python_name": "in_",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                },
            ],
        }
    ]
    mcp: FastMCP[Any] = FastMCP("logs")
    register_method_tools(mcp, LogsApi, LogsApi, prefix="logs", manifest=manifest)
    tool = (await _listed(mcp))["logs_search_logs"]
    assert set(tool.input_schema["properties"]) == {"from", "in"}
    assert tool.input_schema["required"] == ["in"]
    async with Client(mcp) as client:
        result = await client.call_tool("logs_search_logs", {"from": 3, "in": "team"})
    # The client receives the Python-safe names declared as python_name.
    assert result.data == {"from_": 3, "in_": "team"}
