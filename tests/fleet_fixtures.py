"""Fixture servers standing in for the freshrss-agent and archivebox-api connectors.

The real connector servers still import agent-utilities, so the suite cannot
start them. These fixtures serve the same condensed tools with the same input
schemas and fake upstream data. ``FRESHRSS_WIRE_SHA256`` and
``ARCHIVEBOX_WIRE_SHA256`` are the compatibility fingerprints of the real
servers' ``freshrss_reader`` and ``archivebox_core`` tools as listed over stdio
``tools/list`` (freshrss-agent 2.1.0 and archivebox-api, measured 2026-09-13);
the fixture packages pin them, and a test proves the fixtures serve schemas
with exactly those fingerprints. The fleet packages themselves pin the
fingerprint of an empty schema, which no live server matches.

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
from typing import Any

from fastmcp import FastMCP

from agent_connector_sdk.mcp.change_events import serve_change_subscriptions
from agent_connector_sdk.mcp.content import ConnectorContent, register_connector_content

FLEET_PACKAGES = Path(__file__).parent / "fleet_packages"
FRESHRSS_ROOT = FLEET_PACKAGES / "freshrss-agent"
ARCHIVEBOX_ROOT = FLEET_PACKAGES / "archivebox-api"
FRESHRSS_CONNECTORS = FRESHRSS_ROOT / "freshrss_agent" / "connectors"
ARCHIVEBOX_CONNECTORS = ARCHIVEBOX_ROOT / "archivebox_api" / "connectors"
FRESHRSS_WIRE_SHA256 = (
    "77979de11db9df14f10b6c76249162c8b43569503e54cc732ca6e50bcddd74b6"
)
ARCHIVEBOX_WIRE_SHA256 = (
    "1f2a33c31bd6b000bbb4954863f4d41e0710faf38c5a040c6415837e9ce3f21f"
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
            manifest_path=root / "connector_manifest.yml",
        ),
    )


def build_freshrss_server(
    upstream: FakeFreshRss, *, listen: bool = True
) -> FastMCP[Any]:
    """A freshrss-agent server over ``upstream``; ``listen`` serves change subscriptions."""
    mcp: FastMCP[Any] = FastMCP("FreshRSS MCP", version="2.1.0")

    @mcp.tool()
    async def freshrss_reader(action: str, params_json: str = "{}") -> dict[str, Any]:
        """Read FreshRSS streams via the Google Reader API."""
        if action != "stream_contents":
            raise ValueError("unknown action")
        return upstream.stream_contents(json.loads(params_json))

    _content(mcp, FRESHRSS_ROOT, "freshrss_agent")
    if listen:
        serve_change_subscriptions(mcp)
    return mcp


def build_archivebox_server(
    upstream: FakeArchiveBox, *, malformed: bool = False
) -> FastMCP[Any]:
    """An archivebox-api server over ``upstream``; ``malformed`` breaks the records."""
    mcp: FastMCP[Any] = FastMCP("ArchiveBox MCP", version="1.0.0")

    @mcp.tool()
    async def archivebox_core(action: str, params_json: str = "{}") -> dict[str, Any]:
        """Manage archivebox core operations."""
        if action != "get_snapshots":
            raise ValueError("unknown action")
        if malformed:
            return {"items": "not-a-list"}
        return upstream.get_snapshots(json.loads(params_json))

    _content(mcp, ARCHIVEBOX_ROOT, "archivebox_api")
    return mcp


def build_table_server(
    rows: list[dict[str, Any]], *, malformed: bool = False
) -> FastMCP[Any]:
    """A ServiceNow-style table tool paginated by record offset."""
    mcp: FastMCP[Any] = FastMCP("Table MCP", version="1.0.0")

    @mcp.tool()
    async def table_records(action: str, params_json: str = "{}") -> dict[str, Any]:
        """List table records by ``sysparm_offset`` and ``sysparm_limit``."""
        params = json.loads(params_json)
        offset, limit = int(params["sysparm_offset"]), int(params["sysparm_limit"])
        return {"result": "not-a-list" if malformed else rows[offset : offset + limit]}

    return mcp
