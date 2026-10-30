"""Register an admitted bounded weather query as an MCP source."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from scion_sdk._extras import require_mcp_extra
from scion_sdk.earth_observations.weather import (
    WeatherProvider,
    WeatherRequest,
)
from scion_sdk.earth_observations.weather_location import (
    WeatherLocation,
    WeatherQuality,
    _located_records,
)
from scion_sdk.ingest._stream_checkpoint import _authorize_generation
from scion_sdk.ingest.live_declaration import source_meta

require_mcp_extra("scion_sdk.earth_observations.weather_stream")

from fastmcp import Context  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402


def _weather_binding(
    provider: WeatherProvider,
    request: WeatherRequest,
    *,
    name: str,
    policy_revision: str,
    location: WeatherLocation | None,
    quality: WeatherQuality | None,
) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                request.tenant,
                name,
                policy_revision,
                provider.provider,
                provider.http.base_url,
                request.place_id,
                request.start.isoformat(),
                request.end.isoformat(),
                request.latitude,
                request.longitude,
                request.station,
                request.max_records,
                request.license_tag,
                None
                if location is None
                else [
                    location.place.model_dump(mode="json"),
                    location.region.model_dump(mode="json"),
                ],
            ]
            + (
                []
                if quality is None
                else [
                    [
                        quality.quality_id,
                        quality.name,
                        quality.variable,
                        quality.source_unit,
                        quality.unit_code,
                    ]
                ]
            ),
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def register_weather_stream(
    server: Any,
    provider: WeatherProvider,
    request: WeatherRequest,
    *,
    name: str,
    connector: str,
    policy_revision: str,
    authorize: Callable[[str, Any], Awaitable[bool]],
    location: WeatherLocation | None = None,
    quality: WeatherQuality | None = None,
) -> None:
    """Publish a host-admitted bounded query with graph-owned checkpoints."""
    if (
        not name
        or not connector
        or not policy_revision
        or request.source != name
        or (location is not None and location.place.place_id != request.place_id)
        or (quality is not None and location is None)
    ):
        raise ValueError("invalid weather stream binding")

    binding = _weather_binding(
        provider,
        request,
        name=name,
        policy_revision=policy_revision,
        location=location,
        quality=quality,
    )

    async def _serve(
        ctx: Context, mode: str, state: dict[str, Any] | None
    ) -> dict[str, Any]:
        await _authorize_generation(
            authorize,
            tenant=request.tenant,
            context=ctx,
            mode=mode,
            state=state,
            binding=binding,
        )
        rows = await provider.read(request)
        if location is not None:
            records, relationships = _located_records(rows, location, quality)
            return {
                "records": records,
                "relationships": relationships,
                "checkpoint": {"binding": binding, "generation": uuid.uuid4().hex},
            }
        return {
            "records": [
                dict(
                    row.model_dump(mode="json", exclude_none=True),
                    id=row.source_event_id,
                )
                for row in rows
            ],
            "checkpoint": {"binding": binding, "generation": uuid.uuid4().hex},
        }

    async def weather_stream(
        ctx: Context, mode: str = "delta", state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Read the host-admitted weather interval."""
        try:
            return await _serve(ctx, mode, state)
        except Exception:
            raise ToolError("weather source page refused") from None

    preset: dict[str, Any] = {
        "params_style": "args",
        "params": {"mode": "delta"},
        "updated_since_param": "state",
        "checkpoint_path": "checkpoint",
    }
    if location is not None:
        preset.update(
            {
                "record_mode": "typed_entities",
                "node_type_field": "node_type",
                "relationships_path": "relationships",
            }
        )
    metadata = source_meta(
        source_id=name,
        record_type="WeatherObservation",
        id_field="id",
        records_path="records",
        title_field="variable",
        server=connector,
        preset=preset,
    )
    server.tool(name=name, annotations={"readOnlyHint": True}, meta=metadata)(
        weather_stream
    )
