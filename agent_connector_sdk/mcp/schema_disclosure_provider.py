"""Expose schema resources through the existing authorized tool catalog."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.server.transforms.catalog import CatalogTransform
from fastmcp.server.transforms.search.base import serialize_tools_for_output_markdown
from fastmcp.tools import Tool

from .concurrency import run_blocking
from .schema_disclosure import (
    SchemaDisclosure,
    SchemaManifest,
    _verify_document,
    read_schema_fragment,
)
from .schema_disclosure_models import FRAGMENT_URI_TEMPLATE, MANIFEST_URI_TEMPLATE

__all__ = ["describe_schema_tools", "register_schema_resources"]


def _current_manifest(tool: Tool) -> SchemaManifest:
    manifest = SchemaManifest.model_validate((tool.meta or {}).get("openapi_schema"))
    if manifest.alias != tool.name:
        raise ValueError("Navigation alias differs from schema identity")
    _verify_document(
        {"inputSchema": tool.parameters, "outputSchema": tool.output_schema}, manifest
    )
    return manifest


def describe_schema_tools(tools: Sequence[Tool]) -> list[dict[str, Any]]:
    """Bounded navigation for the existing authorized FastMCP search transform."""
    result = []
    for tool in tools:
        manifest = _current_manifest(tool)
        result.append(
            {
                "kind": "schema-navigation",
                "name": tool.name,
                "manifest": manifest.model_dump(),
                "summary": serialize_tools_for_output_markdown([tool]),
            }
        )
    if len(json.dumps(result, ensure_ascii=False).encode()) > 32 * 1024:
        raise ValueError("Schema navigation exceeds disclosure budget")
    return result


async def _selected(
    catalog: CatalogTransform,
    disclosures: Mapping[str, SchemaDisclosure],
    ctx: Context,
    *,
    alias: str,
    schema_sha256: str,
) -> SchemaDisclosure:
    visible = await catalog.get_tool_catalog(ctx)
    tool = next((item for item in visible if item.name == alias), None)
    selected = disclosures.get(alias)
    if tool is None or selected is None:
        raise ValueError("Schema is not available in the authorized tool catalog")
    manifest = selected.manifest.model_dump()
    if (
        selected.manifest.schema_sha256 != schema_sha256
        or _current_manifest(tool).model_dump() != manifest
    ):
        raise ValueError("Stale schema identity in authorized catalog")
    return selected


def register_schema_resources(
    server: FastMCP,
    catalog: CatalogTransform,
    disclosures: Mapping[str, SchemaDisclosure],
) -> None:
    """Register two resource templates; each read rechecks tool visibility.

    ``catalog`` must be the same transform attached to this server for search.
    Resources carry no credentials and use the caller's normal MCP session.
    """

    @server.resource(MANIFEST_URI_TEMPLATE, mime_type="application/json")
    async def schema_manifest(alias: str, schema_sha256: str, ctx: Context) -> str:
        selected = await _selected(
            catalog, disclosures, ctx, alias=alias, schema_sha256=schema_sha256
        )
        return selected.manifest.model_dump_json()

    @server.resource(FRAGMENT_URI_TEMPLATE, mime_type="application/json")
    async def schema_fragment(
        alias: str, schema_sha256: str, index: str, *, ctx: Context
    ) -> str:
        selected = await _selected(
            catalog, disclosures, ctx, alias=alias, schema_sha256=schema_sha256
        )
        if (
            not index.isascii()
            or not index.isdecimal()
            or len(index) > 4
            or str(int(index)) != index
        ):
            raise ValueError("Invalid schema fragment index")
        value = await run_blocking(
            read_schema_fragment, selected, int(index), expected_sha256=schema_sha256
        )
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
