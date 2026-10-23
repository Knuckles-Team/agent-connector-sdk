"""Per-parent fan-out for ``mcp_tool`` presets (SDK-SOURCE-INGEST-R004.28).

A preset with ``for_each`` is extracted once per record of its parent preset:
the parent's ``field`` value is passed as the preset's ``argument``. The
fan-out position (which parent value is being read) rides in the checkpoint
position under ``__fan`` beside the inner page position, so a stopped run
resumes at the same parent and page. Watermarks are held across the parents so
the watermark advances only when the last parent is exhausted.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from epistemic_graph.generated.source_ingestion import (
    SourceCheckpoint,
    SourceIngestionMode,
)

from agent_connector_sdk.adapters.mcp_tool_paging import (
    next_position,
    page_params,
    tool_arguments,
)
from agent_connector_sdk.adapters.mcp_tool_records import raw_records
from agent_connector_sdk.contracts import RecordPage
from agent_connector_sdk.ingest.for_each import MAX_FAN_OUT, ForEachRefusal
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import SourceContractError
from agent_connector_sdk.ports.session import McpSession

__all__ = ["FAN_KEY", "check_parents", "extract_fanned", "parent_values"]

FAN_KEY = "__fan"


def check_parents(preset: ToolPreset, parents: Mapping[str, ToolPreset]) -> None:
    """Refuse an unknown parent or a cycle above ``preset``.

    Raises:
        ForEachRefusal: ``unknown_parent_source`` or ``for_each_cycle``.
    """
    chain = [preset.name]
    link = preset.for_each
    while link is not None:
        parent = parents.get(link.source)
        if parent is None:
            raise ForEachRefusal(
                "unknown_parent_source",
                f"preset {chain[-1]!r} follows {link.source!r}, which has no sync preset",
            )
        if link.source in chain:
            raise ForEachRefusal(
                "for_each_cycle", f"presets {' -> '.join([*chain, link.source])}"
            )
        chain.append(link.source)
        link = parent.for_each


async def parent_values(
    session: McpSession,
    preset: ToolPreset,
    parents: Mapping[str, ToolPreset],
    *,
    limit: int = MAX_FAN_OUT,
) -> list[Any]:
    """The distinct ``field`` values of every record of ``preset``'s parent."""
    check_parents(preset, parents)
    link = preset.for_each
    if link is None:
        return []
    parent = parents[link.source]
    scopes: list[dict[str, Any]] = [{}]
    if parent.for_each is not None:
        scopes = [
            {parent.for_each.argument: value}
            for value in await parent_values(session, parent, parents, limit=limit)
        ]
    values: list[Any] = []
    for scope in scopes:
        scoped = parent.model_copy(
            update={"arguments": {**parent.arguments, **scope}, "for_each": None}
        )
        position: dict[str, Any] = {}
        for _ in range(parent.max_pages):
            params = page_params(scoped, position, None)
            result = await session.call_tool(
                scoped.tool, tool_arguments(scoped, params)
            )
            raw = raw_records(scoped, result)
            for record in raw:
                value = record.get(link.field)
                if value is not None and value not in values:
                    values.append(value)
            if len(values) > limit:
                raise SourceContractError(
                    f"fan_out_exceeded: {parent.name!r} has more than {limit} "
                    "records to fan out over"
                )
            following = next_position(scoped, position, result=result, raw=raw)
            if following is None:
                break
            position = following
        else:
            raise SourceContractError(
                f"parent_budget_exhausted: {parent.name!r} exceeded max_pages"
            )
    return values


def _hold(
    stream: str, position: dict[str, Any], held: SourceCheckpoint, pending: str | None
) -> SourceCheckpoint:
    return SourceCheckpoint(
        stream=stream,
        position=position,
        watermark=held.watermark,
        pending_watermark=pending,
    )


async def extract_fanned(
    adapter: Any,
    session: McpSession,
    checkpoint: SourceCheckpoint,
    values: list[Any],
) -> RecordPage:
    """One page of ``adapter``'s preset for the parent value the checkpoint is at.

    ``adapter`` is the outer ``McpToolSourceAdapter``; ``values`` the parent
    values. The inner page is read by an adapter whose preset carries the
    parent value as its argument.
    """
    preset: ToolPreset = adapter.preset
    link = preset.for_each
    if link is None:
        raise SourceContractError("extract_fanned needs a preset with for_each")
    position = checkpoint.position if isinstance(checkpoint.position, Mapping) else {}
    index = int(position.get(FAN_KEY, 0))
    if index >= len(values):
        return RecordPage(
            records=(),
            mode=SourceIngestionMode.DELTA,
            strict_schema=preset.strict_schema,
            checkpoint=SourceCheckpoint(
                stream=checkpoint.stream,
                position={},
                watermark=max(
                    (
                        m
                        for m in (checkpoint.pending_watermark, checkpoint.watermark)
                        if m
                    ),
                    default=None,
                ),
            ),
            exhausted=True,
        )
    inner = adapter.derive(
        preset.model_copy(
            update={
                "arguments": {**preset.arguments, link.argument: values[index]},
                "for_each": None,
            }
        )
    )
    inner_position = {k: v for k, v in position.items() if k != FAN_KEY}
    page: RecordPage = await inner.extract(
        session,
        SourceCheckpoint(
            stream=checkpoint.stream,
            position=inner_position,
            watermark=checkpoint.watermark,
            pending_watermark=checkpoint.pending_watermark,
        ),
    )
    inner_checkpoint = page.checkpoint
    if not page.exhausted:
        merged = {FAN_KEY: index, **dict(inner_checkpoint.position or {})}
        return page.model_copy(
            update={
                "checkpoint": inner_checkpoint.model_copy(update={"position": merged})
            }
        )
    if index + 1 < len(values):
        return page.model_copy(
            update={
                "exhausted": False,
                "checkpoint": _hold(
                    checkpoint.stream,
                    {FAN_KEY: index + 1},
                    checkpoint,
                    inner_checkpoint.watermark or checkpoint.pending_watermark,
                ),
            }
        )
    return page
