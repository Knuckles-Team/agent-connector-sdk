"""Serve host-admitted NOAA storm events and weather-system relationships."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import Any

import anyio

from agent_connector_sdk._extras import require_mcp_extra
from agent_connector_sdk.earth_observations._stream_policy import (
    _validate_stream_policy,
)
from agent_connector_sdk.earth_observations.records import WeatherEvent
from agent_connector_sdk.earth_observations.storm import NoaaStormArchive
from agent_connector_sdk.ingest.live_declaration import source_meta

require_mcp_extra("agent_connector_sdk.earth_observations.storm_stream")

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
    binding = hashlib.sha256(
        json.dumps(
            [
                tenant,
                name,
                policy_revision,
                archive.policy.sha256,
                batch_size,
                identifiers,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    async def _serve(
        ctx: Context, mode: str, state: dict[str, Any] | None
    ) -> dict[str, Any]:
        if mode != "delta" or not await authorize(tenant, ctx):
            raise ValueError("access refused")
        offset = 0
        if state is not None:
            if (
                set(state) != {"binding", "offset", "generation"}
                or state["binding"] != binding
                or not isinstance(state["generation"], str)
                or type(state["offset"]) is not int
                or not 0 <= state["offset"] < len(identifiers)
            ):
                raise ValueError("invalid storm checkpoint")
            offset = state["offset"]
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

    async def storm_stream(
        ctx: Context, mode: str = "delta", state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Read a bounded archive page and its approved system relations."""
        try:
            return await _serve(ctx, mode, state)
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
