"""Register an admitted bounded weather query as an MCP source."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from agent_connector_sdk._extras import require_mcp_extra
from agent_connector_sdk.earth_observations.weather import (
    WeatherProvider,
    WeatherRequest,
)
from agent_connector_sdk.ingest.live_declaration import source_meta

require_mcp_extra("agent_connector_sdk.earth_observations.weather_stream")

from fastmcp import Context  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402


def register_weather_stream(
    server: Any,
    provider: WeatherProvider,
    request: WeatherRequest,
    *,
    name: str,
    connector: str,
    policy_revision: str,
    authorize: Callable[[str, Any], Awaitable[bool]],
) -> None:
    """Publish a host-admitted bounded query with graph-owned checkpoints."""
    if not name or not connector or not policy_revision or request.source != name:
        raise ValueError("invalid weather stream binding")

    binding = hashlib.sha256(
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
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    async def weather_stream(
        ctx: Context, mode: str = "delta", state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Read the host-admitted weather interval."""
        try:
            if mode != "delta" or not await authorize(request.tenant, ctx):
                raise ValueError("access refused")
            if state is not None and (
                set(state) != {"binding", "generation"}
                or state["binding"] != binding
                or not isinstance(state["generation"], str)
            ):
                raise ValueError("invalid weather checkpoint")
            rows = await provider.read(request)
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
        except Exception:
            raise ToolError("weather source page refused") from None

    metadata = source_meta(
        source_id=name,
        record_type="WeatherObservation",
        id_field="id",
        records_path="records",
        title_field="variable",
        server=connector,
        preset={
            "params_style": "args",
            "params": {"mode": "delta"},
            "updated_since_param": "state",
            "checkpoint_path": "checkpoint",
        },
    )
    server.tool(name=name, annotations={"readOnlyHint": True}, meta=metadata)(
        weather_stream
    )
