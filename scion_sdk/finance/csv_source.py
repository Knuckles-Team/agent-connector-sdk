"""Serve a validated CSV activity statement for delta ingestion over MCP."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import uuid4

from fastmcp import FastMCP

from scion_sdk.finance.csv_import import (
    AccountContext,
    ColumnMapping,
    import_activities,
)
from scion_sdk.manifest.presets import ToolPreset

__all__ = ["csv_activity_preset", "register_csv_activity_tool"]


def csv_activity_preset(*, stream: str, server: str, tool: str) -> ToolPreset:
    """Configure the SDK adapter for the registered activity tool."""
    return ToolPreset(
        name=stream,
        server=server,
        tool=tool,
        params_style="args",
        params={"mode": "delta"},
        updated_since_param="since",
        checkpoint_path="checkpoint",
        records_path="records",
        id_field="record_id",
        text_field="source_event_id",
        title_field="source_event_id",
    )


def register_csv_activity_tool(
    mcp: FastMCP[Any],
    *,
    name: str,
    content: bytes,
    mapping: ColumnMapping,
    context: AccountContext,
) -> None:
    """Validate a statement and register its records as one MCP delta source.

    Each returned identity scopes the file row to its tenant, provider and
    account. A new checkpoint is issued per read so the graph can compare and
    commit each import; repeated statements still address the same records.
    """
    activities = import_activities(content, mapping, context)
    records = []
    for activity in activities:
        identity = json.dumps(
            [
                context.tenant_id,
                context.source_id,
                context.provider,
                context.account_id,
                activity.source_event_id,
            ],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode()
        records.append(
            {
                **activity.model_dump(mode="json"),
                "record_id": hashlib.sha256(identity).hexdigest(),
            }
        )

    @mcp.tool(name=name)
    def csv_activities(
        mode: Literal["delta"], since: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Return validated activity records with a fresh ingestion checkpoint."""
        return {"records": records, "checkpoint": {"generation": uuid4().hex}}
