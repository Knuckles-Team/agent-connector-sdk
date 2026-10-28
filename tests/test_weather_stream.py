import json
from contextlib import asynccontextmanager

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from weather_test_helpers import weather_provider, weather_request

from agent_connector_sdk.earth_observations.weather_stream import (
    register_weather_stream,
)
from agent_connector_sdk.testing.http_server import ScriptedHttpServer, ScriptedResponse


@pytest.mark.asyncio
async def test_weather_authorization_and_checkpoint_binding():
    @asynccontextmanager
    async def quota(name):
        yield

    allowed = False

    async def authorize(tenant, ctx):
        return allowed and tenant == "tenant"

    body = {
        "utc_offset_seconds": 0,
        "latitude": 45.1,
        "longitude": -92.1,
        "hourly_units": {"temperature_2m": "°C"},
        "hourly": {"time": ["2025-01-01T00:00"], "temperature_2m": [1.1]},
    }
    with ScriptedHttpServer(
        ScriptedResponse(body=json.dumps(body).encode()),
        ScriptedResponse(body=json.dumps(body).encode()),
    ) as server:
        provider = weather_provider(
            server.base_url, "open_meteo", quota, lambda code: True
        )
        request = weather_request(tenant="tenant", hours=1, max_records=1)
        mcp = FastMCP("weather")
        register_weather_stream(
            mcp,
            provider,
            request,
            name="weather",
            connector="weather",
            policy_revision="v1",
            authorize=authorize,
        )
        async with Client(mcp) as client:
            with pytest.raises(ToolError):
                await client.call_tool("weather", {})
            assert not server.requests
            allowed = True
            first = (await client.call_tool("weather", {})).structured_content
            checkpoint = first["checkpoint"]
            with pytest.raises(ToolError):
                await client.call_tool(
                    "weather", {"state": {**checkpoint, "binding": "bad"}}
                )
            assert len(server.requests) == 1
            second = (
                await client.call_tool("weather", {"state": checkpoint})
            ).structured_content
            assert first["records"][0]["id"] == second["records"][0]["id"]
            assert len(server.requests) == 2
