"""Serve host-admitted NOAA storm events and weather-system relationships."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import Any

import anyio

from scion_sdk._extras import require_mcp_extra
from scion_sdk.earth_observations._stream_policy import (
    _authorized_offset,
    _stream_binding,
    _validate_stream_policy,
)
from scion_sdk.earth_observations.records import WeatherEvent
from scion_sdk.earth_observations.storm import NoaaStormArchive
from scion_sdk.ingest.live_declaration import source_meta

require_mcp_extra("scion_sdk.earth_observations.storm_stream")

from fastmcp import Context  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402


def _entities(
    rows: Sequence[WeatherEvent],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    systems: dict[str, str] = {}
    edges: list[dict[str, str]] = []
    for event in rows:
        event_id = f"event:{event.source_event_id}"
        system_id = f"system:{event.weather_system_id}"
        old = systems.setdefault(system_id, event.weather_system_name)
        if old != event.weather_system_name:
            raise ValueError("weather system names conflict")
        records.append(
            dict(
                event.model_dump(mode="json", exclude_none=True),
                id=event_id,
                node_type="WeatherEvent",
            )
        )
        edges.append(
            {"source": event_id, "target": system_id, "relationship": "occursIn"}
        )
    records.extend(
        {"id": key, "node_type": "WeatherSystem", "name": value}
        for key, value in systems.items()
    )
    return records, edges


async def _serve_storm(
    ctx: Context,
    *,
    mode: str,
    state: dict[str, Any] | None,
    authorize: Callable[[str, Any], Awaitable[bool]],
    tenant: str,
    archive: NoaaStormArchive,
    name: str,
    identifiers: Sequence[str],
    batch_size: int,
    binding: str,
) -> dict[str, Any]:
    offset = await _authorized_offset(
        authorize,
        tenant=tenant,
        context=ctx,
        mode=mode,
        state=state,
        key="binding",
        binding=binding,
        size=len(identifiers),
    )
    page = identifiers[offset : offset + batch_size]
    rows = await anyio.to_thread.run_sync(
        partial(
            archive.read,
            page,
            tenant=tenant,
            source=name,
            max_records=batch_size,
        )
    )
    records, relationships = _entities(rows)
    next_offset = offset + len(page)
    more = next_offset < len(identifiers)
    return {
        "records": records,
        "relationships": relationships,
        "next": str(next_offset) if more else None,
        "checkpoint": {
            "binding": binding,
            "offset": next_offset if more else 0,
            "generation": uuid.uuid4().hex,
        },
    }


def register_storm_stream(
    server: Any,
    archive: NoaaStormArchive,
    identifiers: Sequence[str],
    *,
    tenant: str,
    name: str,
    connector: str,
    batch_size: int,
    policy_revision: str,
    authorize: Callable[[str, Any], Awaitable[bool]],
) -> None:
    """Publish admitted storm events and their host-approved systems."""
    identifiers = tuple(identifiers)
    _validate_stream_policy(
        tenant,
        name,
        connector,
        revision=policy_revision,
        identifiers=identifiers,
        batch_size=batch_size,
    )

    binding = _stream_binding(
        [tenant, name, policy_revision, archive.policy.sha256, batch_size, identifiers]
    )

    async def storm_stream(
        ctx: Context, mode: str = "delta", state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Read a bounded archive page and its approved system relations."""
        try:
            return await _serve_storm(
                ctx,
                mode=mode,
                state=state,
                authorize=authorize,
                tenant=tenant,
                archive=archive,
                name=name,
                identifiers=identifiers,
                batch_size=batch_size,
                binding=binding,
            )
        except Exception:
            raise ToolError("storm source page refused") from None

    metadata = source_meta(
        source_id=name,
        record_type="WeatherEvent",
        id_field="id",
        records_path="records",
        title_field="event_type",
        server=connector,
        preset={
            "params_style": "args",
            "params": {"mode": "delta"},
            "record_mode": "typed_entities",
            "node_type_field": "node_type",
            "relationships_path": "relationships",
            "pagination": "cursor",
            "cursor_param": "cursor",
            "cursor_path": "next",
            "updated_since_param": "state",
            "checkpoint_path": "checkpoint",
        },
    )
    server.tool(name=name, annotations={"readOnlyHint": True}, meta=metadata)(
        storm_stream
    )
