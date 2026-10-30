"""CoinGlass macro source records are validated before sink submission."""

import pytest
from fastmcp import FastMCP

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.finance.market_source import (
    MarketSourceAdapter,
    MarketSourceKind,
)
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import MalformedSourceDataError
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.testing.sinks import InMemorySink
from agent_connector_sdk.transports.mcp import McpTransport

COMMON = {
    "record_id": "1",
    "provider": "coinglass",
    "license_tag": "licensed",
    "event_time": "2026-01-01T00:00:00Z",
    "observed_at": "2026-01-02T00:00:00Z",
}
CASES = {
    MarketSourceKind.ETF_FLOW: {
        **COMMON,
        "dataset": "etf",
        "ticker": "IBIT",
        "net_flow_usd": -42,
    },
    MarketSourceKind.SENTIMENT: {**COMMON, "dataset": "sentiment", "value": 45},
    MarketSourceKind.ONCHAIN_POSITION: {
        **COMMON,
        "dataset": "onchain",
        "wallet": "0x" + "ab" * 20,
        "symbol": "ETH",
        "position_size": -3.5,
        "entry_price": 100,
        "mark_price": 101,
    },
}


def _server(record):
    server = FastMCP("macro", version="1.0.0")

    @server.tool()
    def read(mode: str) -> list[dict]:
        return [record]

    return server


def _adapter(kind):
    preset = ToolPreset(
        name="macro",
        server="macro",
        tool="read",
        id_field="record_id",
        params_style="args",
        params={"mode": "delta"},
    )
    source = McpToolSourceAdapter(
        preset, connector="macro", mapping_reference="connector:macro#mappings/Record"
    )
    return MarketSourceAdapter(
        source, market_kind=kind, connector="macro", stream="macro"
    )


@pytest.mark.spec("SCION-FINANCE-SOURCES-R005.1")
@pytest.mark.parametrize("kind", list(CASES))
async def test_macro_sources_keep_source_and_observation_times(kind):
    sink = InMemorySink()
    async with McpTransport().session(
        TransportEndpoint(in_process=_server(CASES[kind]))
    ) as session:
        outcome = await sync_stream(
            session, _adapter(kind), SyncTarget("macro", sink, max_pages=1)
        )
    assert outcome.accepted == 1
    assert next(iter(sink.batches.values())).records[0].payload == CASES[kind]


@pytest.mark.parametrize(
    "kind,changes",
    [
        (MarketSourceKind.ETF_FLOW, {"net_flow_usd": float("nan")}),
        (MarketSourceKind.SENTIMENT, {"provider": "private-provider"}),
        (MarketSourceKind.ONCHAIN_POSITION, {"wallet": "private-wallet"}),
    ],
)
async def test_bad_macro_records_refuse_before_sink(kind, changes):
    sink = InMemorySink()
    async with McpTransport().session(
        TransportEndpoint(in_process=_server({**CASES[kind], **changes}))
    ) as session:
        with pytest.raises(MalformedSourceDataError) as error:
            await sync_stream(
                session, _adapter(kind), SyncTarget("macro", sink, max_pages=1)
            )
    assert "private-" not in str(error.value)
    assert not sink.batches
