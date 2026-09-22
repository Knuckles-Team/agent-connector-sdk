"""Fixture servers standing in for the freshrss-agent and archivebox-api connectors.

The real connector servers still import agent-utilities, so the suite cannot
start them. These fixtures serve the same condensed tools with the same input
schemas and fake upstream data. ``*_CURRENT_SHA256`` values fingerprint the real
servers' current free-string action schemas as listed over stdio ``tools/list``
on 2026-09-13.
The default builders preserve those schemas so certification proves that a
migration is required. The ``build_enumerated_*`` builders serve the future
schema that the fixture packages pin and the positive runner tests consume;
its fingerprint is named ``*_ENUM_SHA256``.

The presets in ``fleet_packages`` are copied from the connector repositories,
except that archivebox-api's ``page_kind: page`` is written ``page_kind: number``,
the one spelling the SDK accepts; the manifests keep only the ``sync`` section
and provenance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastmcp import FastMCP

from agent_connector_sdk.mcp.change_events import serve_change_subscriptions
from agent_connector_sdk.mcp.content import ConnectorContent, register_connector_content

FLEET_PACKAGES = Path(__file__).parent / "fleet_packages"
FRESHRSS_ROOT = FLEET_PACKAGES / "freshrss-agent"
ARCHIVEBOX_ROOT = FLEET_PACKAGES / "archivebox-api"
FRESHRSS_CONNECTORS = FRESHRSS_ROOT / "freshrss_agent" / "connectors"
ARCHIVEBOX_CONNECTORS = ARCHIVEBOX_ROOT / "archivebox_api" / "connectors"
FRESHRSS_ENUM_SHA256 = (
    "7e18bf9ed1c48cadece180e17777cc68da409d0e86cb79fbebcf69172794d3b4"
)
ARCHIVEBOX_ENUM_SHA256 = (
    "f86ef345d867f55d1a343f684357291f80a1071bccdef5bde8ff859fea3dcc8d"
)
FRESHRSS_CURRENT_SHA256 = (
    "853fb6e29803342a2b48e6000d1669a50b029a6414cf36f64fffd035d5838f5f"
)
ARCHIVEBOX_CURRENT_SHA256 = (
    "a8227dfe8c93b062ebea2f1e055fbf14621d3e21972594b5fddfb64b9b549fe8"
)
FRESHRSS_READING_LIST = "data://freshrss-agent/reading-list"


def freshrss_items(first: int, count: int) -> list[dict[str, Any]]:
    """Google Reader items with unix-second ``published`` stamps."""
    return [
        {
            "id": f"tag:google.com,2005:reader/item/{number:016x}",
            "title": f"Article {number}",
            "text": f"Body of article {number}",
            "published": 1_757_000_000 + number,
        }
        for number in range(first, first + count)
    ]


def archivebox_snapshots(count: int) -> list[dict[str, Any]]:
    """ArchiveBox snapshots with ISO ``modified_at`` stamps."""
    base = datetime(2026, 9, 1, tzinfo=UTC)
    return [
        {
            "abid": f"snp_{number:05d}",
            "url": f"https://example.invalid/page/{number}",
            "title": f"Page {number}",
            "modified_at": (base + timedelta(minutes=number)).isoformat(),
        }
        for number in range(count)
    ]


@dataclass
class FakeFreshRss:
    """The reading-list stream of a FreshRSS instance."""

    items: list[dict[str, Any]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def stream_contents(self, params: dict[str, Any]) -> dict[str, Any]:
        """``stream_contents``: ``count`` items after ``continuation``, newer than ``newer_than``."""
        self.calls.append(params)
        newer = params.get("newer_than")
        selected = [
            item
            for item in self.items
            if newer is None or item["published"] > int(newer)
        ]
        start, count = int(params.get("continuation") or 0), int(params["count"])
        following = start + count
        return {
            "items": selected[start:following],
            "continuation": str(following) if following < len(selected) else None,
        }


@dataclass
class FakeArchiveBox:
    """The snapshot list of an ArchiveBox instance (0-based pages)."""

    snapshots: list[dict[str, Any]]
    pages: list[int] = field(default_factory=list)

    def get_snapshots(self, params: dict[str, Any]) -> dict[str, Any]:
        """``get_snapshots``: page ``page`` of ``limit`` snapshots."""
        page, limit = int(params["page"]), int(params["limit"])
        self.pages.append(page)
        return {"items": self.snapshots[page * limit : (page + 1) * limit]}


def _content(mcp: FastMCP[Any], root: Path, module: str) -> None:
    register_connector_content(
        mcp,
        ConnectorContent(
            connector=root.name,
            package_root=root / module,
            package_version="2.1.0",
            manifest_path=root / "connector_manifest.yml",
        ),
    )


def _freshrss_server(
    upstream: FakeFreshRss, *, listen: bool, action_contract: object
) -> FastMCP[Any]:
    mcp: FastMCP[Any] = FastMCP("FreshRSS MCP", version="2.1.0")

    async def freshrss_reader(action: str, params_json: str = "{}") -> dict[str, Any]:
        """Read FreshRSS streams via the Google Reader API."""
        if action != "stream_contents":
            raise ValueError("unknown action")
        return upstream.stream_contents(json.loads(params_json))

    freshrss_reader.__annotations__["action"] = action_contract
    mcp.tool()(freshrss_reader)
    _content(mcp, FRESHRSS_ROOT, "freshrss_agent")
    if listen:
        serve_change_subscriptions(mcp)
    return mcp


def build_freshrss_server(
    upstream: FakeFreshRss, *, listen: bool = True
) -> FastMCP[Any]:
    """The fleet's current free-string FreshRSS contract."""
    return _freshrss_server(upstream, listen=listen, action_contract=str)


def build_enumerated_freshrss_server(
    upstream: FakeFreshRss, *, listen: bool = True
) -> FastMCP[Any]:
    """The future action-enumerated FreshRSS contract."""
    return _freshrss_server(
        upstream, listen=listen, action_contract=Literal["stream_contents"]
    )


def _archivebox_server(
    upstream: FakeArchiveBox, *, malformed: bool, action_contract: object
) -> FastMCP[Any]:
    mcp: FastMCP[Any] = FastMCP("ArchiveBox MCP", version="1.0.0")

    async def archivebox_core(action: str, params_json: str = "{}") -> dict[str, Any]:
        """Manage archivebox core operations."""
        if action != "get_snapshots":
            raise ValueError("unknown action")
        if malformed:
            return {"items": "not-a-list"}
        return upstream.get_snapshots(json.loads(params_json))

    archivebox_core.__annotations__["action"] = action_contract
    mcp.tool()(archivebox_core)
    _content(mcp, ARCHIVEBOX_ROOT, "archivebox_api")
    return mcp


def build_archivebox_server(
    upstream: FakeArchiveBox, *, malformed: bool = False
) -> FastMCP[Any]:
    """The fleet's current free-string ArchiveBox contract."""
    return _archivebox_server(upstream, malformed=malformed, action_contract=str)


def build_enumerated_archivebox_server(
    upstream: FakeArchiveBox, *, malformed: bool = False
) -> FastMCP[Any]:
    """The future action-enumerated ArchiveBox contract."""
    return _archivebox_server(
        upstream,
        malformed=malformed,
        action_contract=Literal["get_snapshots"],
    )


def build_table_server(
    rows: list[dict[str, Any]], *, malformed: bool = False
) -> FastMCP[Any]:
    """A ServiceNow-style table tool paginated by record offset."""
    mcp: FastMCP[Any] = FastMCP("Table MCP", version="1.0.0")

    @mcp.tool()
    async def table_records(
        action: Literal["list"], params_json: str = "{}"
    ) -> dict[str, Any]:
        """List table records by ``sysparm_offset`` and ``sysparm_limit``."""
        params = json.loads(params_json)
        offset, limit = int(params["sysparm_offset"]), int(params["sysparm_limit"])
        return {"result": "not-a-list" if malformed else rows[offset : offset + limit]}

    return mcp
