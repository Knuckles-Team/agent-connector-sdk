"""A split action never duplicates or collides with an operation tool.

SCION-CONNECTOR-CONTROL-R020.2: minimal fixtures for the three collision shapes
seen in the fleet (a search branch whose split name is an operation name, a
closure-built action table, a router whose own name is reused by an operation)
and for duplicate splits resolved through action tables.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from functools import partial
from typing import Any, Literal

import pytest
from fastmcp import Client, FastMCP
from pydantic import Field

from scion_sdk.mcp.action_split import SplitDecision, action_split_report
from scion_sdk.mcp.method_tools import operation_tool_names
from scion_sdk.mcp.tool_surface import register_tool_surface


async def run_blocking(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Stand-in for the fleet's thread-boundary adapter."""
    return await asyncio.to_thread(fn, *args, **kwargs)


class SearchApi:
    def search_code(self, query: str = "") -> dict[str, Any]:
        """Search code."""
        return {"code": query}

    def search_issues(self, query: str = "") -> dict[str, Any]:
        """Search issues."""
        return {"issues": query}


def register_search_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool()
    async def sample_search(
        action: Literal["code", "issues", "summary"], params_json: str = "{}"
    ) -> dict[str, Any]:
        """Search, github-agent shape."""
        kwargs = json.loads(params_json)
        client = SearchApi()
        if action == "code":
            response = await run_blocking(client.search_code, **kwargs)
            return {"status": 200, "data": response}
        if action == "issues":
            response = await run_blocking(client.search_issues, **kwargs)
            return {"status": 200, "data": response}
        if action == "summary":
            response = await run_blocking(client.search_code, **kwargs)
            return {"status": 200, "data": _summarize(response)}
        return {"status": 400}


def _summarize(response: dict[str, Any]) -> dict[str, int]:
    return {key: len(str(value)) for key, value in response.items()}


def _report(mcp: FastMCP[Any]) -> dict[str, dict[str, str]]:
    return {entry["split"]: entry for entry in action_split_report(mcp)}


async def _listed(mcp: FastMCP[Any]) -> dict[str, Any]:
    return {tool.name: tool for tool in await mcp.list_tools()}


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020.2")
async def test_split_name_equal_to_an_operation_name_is_covered() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp,
        service="sample-mcp",
        client_cls=SearchApi,
        get_client=SearchApi,
        registrars=[register_search_tools],
    )
    tools = await _listed(mcp)
    report = _report(mcp)
    assert "operation" in tools["sample_search_code"].tags
    assert report["sample_search_code"]["outcome"] == "covered"
    assert report["sample_search_code"]["reason"] == "name"
    assert report["sample_search_issues"]["served_by"] == "sample_search_issues"
    # A branch that computes over operation data is a capability of its own.
    assert report["sample_search_summary"]["outcome"] == "split"
    assert "sample_search_summary" in tools


class RommApi:
    def search_cover(self, term: str = "") -> dict[str, Any]:
        """Search cover art."""
        return {"cover": term}

    def list_roms(self) -> list[str]:
        """List ROMs."""
        return ["a"]


ROMM_TOOLS: list[tuple[str, dict[str, str]]] = [
    ("sample_search", {"cover": "search_cover"}),
    ("sample_roms", {"list": "list_roms"}),
]


def _romm_tool(mcp: FastMCP[Any], name: str, actions: dict[str, str]) -> None:
    action_list = ", ".join(f"'{key}'" for key in actions)

    async def romm_tool(
        action: str = Field(description=f"One of: {action_list}."),
        params_json: str = "{}",
    ) -> Any:
        method = getattr(RommApi(), actions[action])
        return method(**json.loads(params_json))

    mcp.tool(name=name, description=f"RomM {name}.")(romm_tool)


def register_romm_tools(mcp: FastMCP[Any]) -> None:
    for name, actions in ROMM_TOOLS:
        _romm_tool(mcp, name, actions)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020.2")
async def test_closure_table_actions_are_covered_by_their_operations() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp,
        service="sample-mcp",
        client_cls=RommApi,
        get_client=RommApi,
        registrars=[register_romm_tools],
    )
    tools = await _listed(mcp)
    report = _report(mcp)
    assert set(tools) == {"sample_search_cover", "sample_list_roms"}
    assert operation_tool_names(RommApi, prefix="sample") == {
        "list_roms": "sample_list_roms",
        "search_cover": "sample_search_cover",
    }
    assert report["sample_search_cover"]["reason"] == "name"
    assert report["sample_roms_list"] == asdict(
        SplitDecision(
            tool="sample_roms",
            action="list",
            split="sample_roms_list",
            outcome="covered",
            served_by="sample_list_roms",
            reason="table",
        )
    )


class SqlApi:
    def execute(self, sql: str) -> dict[str, Any]:
        """Run one statement."""
        return {"rows": len(sql)}

    def execute_script(self, statements: list[str]) -> dict[str, Any]:
        """Run statements in one transaction."""
        return {"rows": len(statements)}


def get_api() -> SqlApi:
    return SqlApi()


async def _invoke(call: Any) -> Any:
    return call()


def register_execute_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool()
    async def sample_execute(
        action: Literal["execute", "script"], params_json: str = "{}"
    ) -> Any:
        """Write statements, sql-mcp shape."""
        api = get_api()
        p = json.loads(params_json)
        if action == "execute":
            return await _invoke(partial(api.execute, p["sql"]))
        if action == "script":
            return await _invoke(partial(api.execute_script, p["statements"]))
        raise ValueError(action)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020.2")
async def test_router_name_reused_by_an_operation_is_not_a_collision() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp,
        service="sample-mcp",
        client_cls=SqlApi,
        get_client=SqlApi,
        registrars=[register_execute_tools],
    )
    tools = await _listed(mcp)
    report = _report(mcp)
    assert set(tools) == {"sample_execute", "sample_execute_script"}
    assert "operation" in tools["sample_execute"].tags
    assert report["sample_execute_execute"]["served_by"] == "sample_execute"
    assert report["sample_execute_script"]["outcome"] == "covered"
    async with Client(mcp) as client:
        result = await client.call_tool(
            "sample_execute_script", {"statements": ["a", "b"]}
        )
    assert result.structured_content == {"rows": 2}


class HubApi:
    def get_branch(self, branch: str) -> dict[str, Any]:
        """One branch."""
        return {"branch": branch}

    def get_branches(self) -> list[str]:
        """Every branch."""
        return ["main"]

    def get_org_settings(self, org: str) -> dict[str, Any]:
        """Org settings."""
        return {"org": org}


def _by_keys(keys: tuple[str, ...], single: str, many: str) -> Any:
    def select(kwargs: dict[str, Any]) -> str:
        return single if all(k in kwargs for k in keys) else many

    return select


_BRANCH_ACTIONS: dict[str, Any] = {
    "get": _by_keys(("branch",), "get_branch", "get_branches")
}


def register_duplicate_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool()
    async def sample_branches(
        action: str = Field(description="Must be one of: 'get'"),
        params_json: str = "{}",
    ) -> Any:
        """Branches, gitlab-api shape."""
        kwargs = json.loads(params_json)
        target = _BRANCH_ACTIONS[action]
        return getattr(HubApi(), target(kwargs))(**kwargs)

    @mcp.tool()
    async def sample_org(
        action: Literal["get_settings", "audit"], params_json: str = "{}"
    ) -> Any:
        """Org administration, dockerhub shape."""
        client = HubApi()
        handlers = {"get_settings": client.get_org_settings}
        if action == "audit":
            return {"audited": True}
        return handlers[action](**json.loads(params_json))


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020.2")
async def test_table_duplicates_are_covered_and_nothing_is_dropped() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp,
        service="sample-mcp",
        client_cls=HubApi,
        get_client=HubApi,
        registrars=[register_duplicate_tools],
    )
    tools = await _listed(mcp)
    report = _report(mcp)
    assert report["sample_branches_get"]["served_by"] in {
        "sample_get_branch",
        "sample_get_branches",
    }
    assert report["sample_org_get_settings"]["served_by"] == "sample_get_org_settings"
    assert set(tools) == {
        "sample_get_branch",
        "sample_get_branches",
        "sample_get_org_settings",
        "sample_org_audit",
    }
    # Every action is served by its split tool or by the operation tool.
    assert all(entry["served_by"] in tools for entry in report.values())


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020.2")
def test_two_different_tools_with_one_name_still_raise() -> None:
    def register_clash(mcp: FastMCP[Any]) -> None:
        @mcp.tool()
        def sample_get_branches() -> str:
            """Not an operation wrapper, but it takes an operation's name."""
            return "clash"

    mcp: FastMCP[Any] = FastMCP("sample")
    with pytest.raises(ValueError, match="operation tool name collides"):
        register_tool_surface(
            mcp,
            service="sample-mcp",
            client_cls=HubApi,
            get_client=HubApi,
            registrars=[register_clash],
        )


class OktaApi:
    def list_apps(self, limit: int = 200) -> list[str]:
        """List apps."""
        return ["app"] * min(limit, 1)

    def get_app(self, app_id: str) -> dict[str, Any]:
        """One app."""
        return {"id": app_id}


APP_ACTIONS = "list, get, audit"

_APP_HANDLERS: dict[str, Any] = {
    "list": lambda client, p: client.list_apps(limit=p.get("limit", 200)),
    "get": lambda client, p: client.get_app(p["app_id"]),
    "audit": lambda client, p: _summarize(client.get_app(p["app_id"])),
}


def run_apps(action: str, params_json: str) -> Any:
    return _APP_HANDLERS[action](OktaApi(), json.loads(params_json))


def register_lambda_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool()
    def sample_apps(
        action: str = Field(description=f"Action to perform. One of: {APP_ACTIONS}."),
        params_json: str = "{}",
    ) -> Any:
        """Apps, okta-agent shape."""
        return run_apps(action, params_json)


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020.2")
async def test_listed_actions_and_lambda_handlers_resolve() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp,
        service="sample-mcp",
        client_cls=OktaApi,
        get_client=OktaApi,
        registrars=[register_lambda_tools],
    )
    report = _report(mcp)
    assert report["sample_apps_list"]["served_by"] == "sample_list_apps"
    assert report["sample_apps_get"]["served_by"] == "sample_get_app"
    # A handler that computes over operation data stays a tool of its own.
    assert report["sample_apps_audit"]["outcome"] == "split"
    assert "sample_apps_audit" in await _listed(mcp)


class RadarrApi:
    def get_movie(self, movie_id: int = 0) -> dict[str, Any]:
        """One movie."""
        return {"id": movie_id}

    def get_system_status(self) -> dict[str, Any]:
        """Status."""
        return {"ok": True}


class SonarrApi:
    def get_system_status(self) -> dict[str, Any]:
        """Status."""
        return {"ok": True}


def get_radarr_client() -> RadarrApi:
    return RadarrApi()


def dispatch(client: Any, action: str, kwargs: dict[str, Any]) -> Any:
    return getattr(client, action)(**kwargs)


def register_router_tools(mcp: FastMCP[Any]) -> None:
    @mcp.tool()
    def radarr_action(action: str, params_json: str = "{}") -> Any:
        """Execute any Radarr method, arr-mcp shape."""
        client = get_radarr_client()
        return dispatch(client, action, json.loads(params_json))


@pytest.mark.spec("SCION-CONNECTOR-CONTROL-R020.2")
async def test_generic_router_is_covered_by_its_clients_operations() -> None:
    mcp: FastMCP[Any] = FastMCP("sample")
    register_tool_surface(
        mcp,
        service="arr-mcp",
        registrars=[register_router_tools],
        verbose_targets=[
            {"client_cls": SonarrApi, "get_client": SonarrApi, "prefix": "sonarr"},
            {
                "client_cls": RadarrApi,
                "get_client": get_radarr_client,
                "prefix": "radarr",
            },
        ],
    )
    tools = await _listed(mcp)
    report = _report(mcp)
    assert "radarr_action" not in tools
    assert report["radarr_action_get_system_status"]["served_by"] == (
        "radarr_get_system_status"
    )
    assert {entry["reason"] for entry in report.values()} == {"dispatch"}
    assert all(entry["served_by"] in tools for entry in report.values())
