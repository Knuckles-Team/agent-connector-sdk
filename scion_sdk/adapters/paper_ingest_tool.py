"""One host-configured provider stream for certified MCP source ingestion."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from scion_sdk._extras import require_mcp_extra

require_mcp_extra("scion_sdk.adapters.paper_ingest_tool")

from fastmcp import Context  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402

from scion_sdk.adapters.paper_models import (  # noqa: E402
    PaperContinuation,
    PaperQuery,
    PaperRecord,
)
from scion_sdk.adapters.paper_search import PaperSearchService  # noqa: E402
from scion_sdk.ingest.live_declaration import (  # noqa: E402
    _cursor_delta_preset,
    source_meta,
)


def register_paper_provider_stream(
    server: Any,
    service: PaperSearchService,
    query: PaperQuery,
    *,
    name: str,
    connector: str = "",
    record_type: str = "Paper",
) -> None:
    """Register a separate delta stream whose host fixes tenant and provider."""
    if len(query.provider_ids) != 1 or query.continuation:
        raise ValueError("paper stream requires one provider and no initial cursor")

    async def paper_provider_stream(
        ctx: Context, mode: str = "delta", state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Extract one provider page without advancing on failure."""
        if mode != "delta":
            raise ToolError("unsupported paper stream mode")
        try:
            return await _serve_page(service, query, ctx=ctx, state=state)
        except ToolError:
            raise
        except Exception:
            raise ToolError("paper provider page refused") from None

    metadata = source_meta(
        source_id=name,
        record_type=record_type,
        id_field="id",
        records_path="records",
        title_field="title",
        text_field="abstract",
        server=connector,
        preset=_cursor_delta_preset(),
    )
    server.tool(name=name, annotations={"readOnlyHint": True}, meta=metadata)(
        paper_provider_stream
    )


async def _serve_page(
    service: PaperSearchService,
    query: PaperQuery,
    *,
    ctx: Context,
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    continuation = None if state is None else state.get("continuation")
    if state is not None and (
        set(state) != {"continuation", "generation"}
        or not isinstance(state["generation"], str)
    ):
        raise ValueError("invalid stream state")
    if continuation is not None:
        token = PaperContinuation.model_validate(continuation)
        query = PaperQuery.model_validate(
            {**query.model_dump(), "continuation": {query.provider_ids[0]: token}}
        )
    result = await service.search(query, ctx)
    report = result.reports[0]
    if report.outcome != "ok":
        raise ToolError("paper provider page refused")
    records = [_record(paper) for paper in result.records]
    next_token = report.continuation
    checkpoint = {
        "continuation": None
        if next_token is None
        else next_token.model_dump(mode="json"),
        "generation": uuid.uuid4().hex,
    }
    return {
        "records": records,
        "next": None if next_token is None else next_token.cursor,
        "checkpoint": checkpoint,
    }


def _record(paper: PaperRecord) -> dict[str, Any]:
    item = paper.model_dump(mode="json", exclude_none=True)
    identity = json.dumps(
        [paper.canonical_id, paper.revision], ensure_ascii=False, separators=(",", ":")
    ).encode()
    item["id"] = hashlib.sha256(identity).hexdigest()
    return item
