"""Register an authorized bounded taxonomy source with certified discovery."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agent_connector_sdk._extras import require_mcp_extra

require_mcp_extra("agent_connector_sdk.taxonomy.stream")

from fastmcp import Context  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402

from agent_connector_sdk.ingest.live_declaration import source_meta  # noqa: E402
from agent_connector_sdk.taxonomy.provider import (  # noqa: E402
    TaxonomyProvider,
    _valid_identifier_batch,
)


async def _page(
    provider: TaxonomyProvider,
    identifiers: tuple[str, ...],
    batch_size: int,
    digest: str,
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    offset = 0
    if state is not None:
        if (
            set(state) != {"digest", "offset", "generation"}
            or state["digest"] != digest
            or not isinstance(state["generation"], str)
            or type(state["offset"]) is not int
            or not 0 <= state["offset"] < len(identifiers)
        ):
            raise ValueError("invalid taxonomy stream checkpoint")
        offset = state["offset"]
    page_ids = identifiers[offset : offset + batch_size]
    rows = await provider.read(page_ids, max_records=batch_size)
    next_offset = offset + len(page_ids)
    more = next_offset < len(identifiers)
    checkpoint = {
        "digest": digest,
        "offset": next_offset if more else 0,
        "generation": uuid.uuid4().hex,
    }
    return {
        "records": [
            dict(
                record.model_dump(mode="json", exclude_none=True), id=record.term_curie
            )
            for record in rows
        ],
        "next": str(next_offset) if more else None,
        "checkpoint": checkpoint,
    }


def register_taxonomy_stream(
    server: Any,
    provider: TaxonomyProvider,
    identifiers: Sequence[str],
    *,
    tenant: str,
    batch_size: int,
    authorize: Callable[[str, Any], Awaitable[bool]],
    name: str,
    connector: str,
) -> None:
    """Publish only a host-admitted tenant, provider and bounded ID set."""
    identifiers = tuple(identifiers)
    if not tenant or not _valid_identifier_batch(identifiers, batch_size):
        raise ValueError("invalid taxonomy stream policy")
    digest = hashlib.sha256(
        json.dumps(
            [
                tenant,
                provider.provider,
                provider.http.base_url,
                batch_size,
                identifiers,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    async def taxonomy_stream(
        ctx: Context, mode: str = "delta", state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Read the next admitted provider page."""
        try:
            if mode != "delta" or not await authorize(tenant, ctx):
                raise ValueError("access refused")
            return await _page(provider, identifiers, batch_size, digest, state)
        except Exception:
            raise ToolError("taxonomy source page refused") from None

    metadata = source_meta(
        source_id=name,
        record_type="Taxon",
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
        taxonomy_stream
    )
