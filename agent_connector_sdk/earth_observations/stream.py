"""Register admitted occurrence pages through certified MCP discovery."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agent_connector_sdk._extras import require_mcp_extra
from agent_connector_sdk.earth_observations._stream_policy import (
    _authorized_offset,
    _stream_binding,
    _validate_stream_policy,
)
from agent_connector_sdk.earth_observations.occurrence import OccurrenceProvider
from agent_connector_sdk.ingest.live_declaration import source_meta

require_mcp_extra("agent_connector_sdk.earth_observations.stream")

from fastmcp import Context  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402


def register_occurrence_stream(
    server: Any,
    provider: OccurrenceProvider,
    identifiers: Sequence[str],
    *,
    tenant: str,
    batch_size: int,
    policy_revision: str,
    authorize: Callable[[str, Any], Awaitable[bool]],
    name: str,
    connector: str,
) -> None:
    """Publish only a host-admitted tenant, provider and bounded ID set."""
    identifiers = tuple(identifiers)
    _validate_stream_policy(
        tenant,
        name,
        connector,
        revision=policy_revision,
        identifiers=identifiers,
        batch_size=batch_size,
    )
    digest = _stream_binding(
        [
            tenant,
            name,
            policy_revision,
            provider.provider,
            provider.http.base_url,
            batch_size,
            identifiers,
        ]
    )

    async def _serve(
        ctx: Context, mode: str, state: dict[str, Any] | None
    ) -> dict[str, Any]:
        offset = await _authorized_offset(
            authorize,
            tenant=tenant,
            context=ctx,
            mode=mode,
            state=state,
            key="digest",
            binding=digest,
            size=len(identifiers),
        )
        page_ids = identifiers[offset : offset + batch_size]
        rows = await provider.read(
            page_ids, tenant=tenant, source=name, max_records=batch_size
        )
        next_offset = offset + len(page_ids)
        more = next_offset < len(identifiers)
        return {
            "records": [
                dict(
                    row.model_dump(mode="json", exclude_none=True),
                    id=f"{provider.provider}:{row.source_event_id}",
                )
                for row in rows
            ],
            "next": str(next_offset) if more else None,
            "checkpoint": {
                "digest": digest,
                "offset": next_offset if more else 0,
                "generation": uuid.uuid4().hex,
            },
        }

    async def occurrence_stream(
        ctx: Context, mode: str = "delta", state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Read the next admitted provider page."""
        try:
            return await _serve(ctx, mode, state)
        except Exception:
            raise ToolError("occurrence source page refused") from None

    metadata = source_meta(
        source_id=name,
        record_type="OrganismObservation",
        id_field="id",
        records_path="records",
        title_field="scientific_name",
        server=connector,
        preset={
            "params_style": "args",
            "params": {"mode": "delta"},
            "pagination": "cursor",
            "cursor_param": "cursor",
            "cursor_path": "next",
            "updated_since_param": "state",
            "checkpoint_path": "checkpoint",
        },
    )
    server.tool(name=name, annotations={"readOnlyHint": True}, meta=metadata)(
        occurrence_stream
    )
