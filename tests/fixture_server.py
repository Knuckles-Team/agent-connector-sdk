"""In-process connector servers used by the test suite and the conformance kit.

``build_reader_server`` serves a paginated ``demo_reader`` tool in the fleet's
action-routed shape (``action`` + ``params_json``) plus the connector content in
``tests/fixture_package``. ``build_malformed_server`` serves the same tool
contract but returns records that do not match the preset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from agent_connector_sdk.mcp.content import ConnectorContent, register_connector_content

PACKAGE_ROOT = Path(__file__).parent / "fixture_package"
CONNECTOR = "demo-agent"
SERVER_NAME = "demo-mcp"
SERVER_VERSION = "1.4.0"

ITEMS: tuple[dict[str, Any], ...] = tuple(
    {
        "id": f"item-{index}",
        "title": f"Item {index}",
        "text": f"Body of item {index}",
        "published": f"2026-09-0{index}T00:00:00Z",
    }
    for index in range(1, 6)
)


def _page(params_json: str) -> dict[str, Any]:
    params = json.loads(params_json or "{}")
    count = int(params.get("count", 2))
    start = int(params.get("continuation") or 0)
    newer_than = params.get("newer_than")
    selected = [
        item for item in ITEMS if not newer_than or item["published"] > newer_than
    ]
    page = selected[start : start + count]
    following = start + count
    return {
        "items": page,
        "continuation": str(following) if following < len(selected) else None,
    }


def build_reader_server(*, with_content: bool = True) -> FastMCP[Any]:
    """The well-formed fixture connector."""
    mcp: FastMCP[Any] = FastMCP(SERVER_NAME, version=SERVER_VERSION)

    @mcp.tool()
    def demo_reader(action: str, params_json: str = "{}") -> dict[str, Any]:
        """Read the demo stream one page at a time."""
        if action != "stream_contents":
            raise ValueError("unknown action")
        return _page(params_json)

    if with_content:
        register_connector_content(
            mcp,
            ConnectorContent(
                connector=CONNECTOR,
                package_root=PACKAGE_ROOT,
                manifest_path=PACKAGE_ROOT / "connector_manifest.yml",
            ),
        )
    return mcp


def build_malformed_server() -> FastMCP[Any]:
    """Same tool contract; the payload is not a record list."""
    mcp: FastMCP[Any] = FastMCP(SERVER_NAME, version=SERVER_VERSION)

    @mcp.tool()
    def demo_reader(action: str, params_json: str = "{}") -> dict[str, Any]:
        """Read the demo stream one page at a time."""
        return {"items": "not-a-list", "continuation": None}

    return mcp
