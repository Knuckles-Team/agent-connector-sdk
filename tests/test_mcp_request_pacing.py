"""Optional MCP request pacing stays at the transport/session boundary."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.shared.exceptions import MCPError

from agent_connector_sdk.httpsupport.rate_limit import RateLimiter
from agent_connector_sdk.ports.errors import McpTransportError
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.transports import mcp as mcp_transport
from agent_connector_sdk.transports.mcp_changes import ChangeFeed
from agent_connector_sdk.transports.mcp_session import McpClientSession

pytestmark = pytest.mark.spec("SDK-CENTRALIZED-CAPABILITIES-R005")


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _Client:
    server_info = SimpleNamespace(name="test", version="1")

    def __init__(self, *, error: BaseException | None = None) -> None:
        self.error = error
        self.reads: list[str] = []
        self.tools: list[str] = []

    async def read_resource(self, uri: str) -> list[Any]:
        self.reads.append(uri)
        if self.error is not None:
            raise self.error
        return [SimpleNamespace(text=uri)]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.tools.append(name)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(content=[SimpleNamespace(text='{"ok": true}')])


class _ContextClient(_Client):
    async def __aenter__(self) -> _ContextClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def _session(client: _Client, limiter: RateLimiter | None = None) -> McpClientSession:
    return McpClientSession(client, feed=ChangeFeed(), request_limiter=limiter)


async def test_concurrent_reads_share_the_configured_fake_clock_limiter() -> None:
    clock = _Clock()
    client = _Client()
    session = _session(client, RateLimiter(1.0, clock=clock, sleep=clock.sleep))

    await asyncio.gather(
        *(session.read_resource(f"data://{index}") for index in range(3))
    )

    assert client.reads == ["data://0", "data://1", "data://2"]
    assert clock.sleeps == [pytest.approx(1.0), pytest.approx(1.0)]


async def test_mcp_error_is_propagated_without_a_blind_retry() -> None:
    error = MCPError(-32000, "Rate limit exceeded for client: anonymous")
    client = _Client(error=error)
    session = _session(client)

    with pytest.raises(MCPError) as raised:
        await session.read_resource("data://limited")

    assert raised.value is error
    assert client.reads == ["data://limited"]


async def test_tool_mcp_error_is_not_retried_or_reissued() -> None:
    error = MCPError(-32000, "Rate limit exceeded for client: anonymous")
    client = _Client(error=error)
    session = _session(client)

    with pytest.raises(McpTransportError) as raised:
        await session.call_tool("lookup", {})

    assert isinstance(raised.value.__cause__, MCPError)
    assert client.tools == ["lookup"]


@pytest.mark.parametrize("interval", [float("nan"), float("inf"), -0.1])
def test_endpoint_rejects_invalid_mcp_pacing(interval: float) -> None:
    with pytest.raises(ValueError, match="mcp_min_interval_seconds"):
        TransportEndpoint(in_process=object(), mcp_min_interval_seconds=interval)


@pytest.mark.parametrize("interval", [0.0, 0.25])
async def test_transport_wires_endpoint_pacing_without_changing_default(
    monkeypatch: pytest.MonkeyPatch, interval: float
) -> None:
    client = _ContextClient()
    monkeypatch.setattr(mcp_transport, "_client", lambda _endpoint, _feed: client)

    endpoint = TransportEndpoint(in_process=object(), mcp_min_interval_seconds=interval)
    async with mcp_transport.McpTransport().session(endpoint) as session:
        assert isinstance(session, McpClientSession)
        limiter = session.request_limiter
        if interval == 0.0:
            assert limiter is None
        else:
            assert limiter is not None
            assert limiter.min_interval_seconds == interval
