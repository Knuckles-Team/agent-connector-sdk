"""Market adapters bind provider identity and reject malformed pages."""

import pytest
from fastmcp import FastMCP

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.finance.market_source import (
    MarketSourceAdapter,
    MarketSourceKind,
)
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.testing.sinks import InMemorySink
from agent_connector_sdk.transports.mcp import McpTransport

CASES = {
    MarketSourceKind.EXCHANGE_CANDLE: (
        "candle_id",
        {
            "candle_id": "1",
            "exchange": "binance",
            "symbol": "BTC/USDT",
            "interval": "1m",
            "timestamp": "2026-01-02T14:30:00Z",
            "license_tag": "licensed",
            "open": 1,
            "high": 2,
            "low": 1,
            "close": 2,
            "volume": 5,
        },
    ),
    MarketSourceKind.CMC_LISTING: (
        "cmc_id",
        {
            "cmc_id": "1",
            "symbol": "BTC",
            "name": "Bitcoin",
            "price_usd": 100,
            "last_updated": "2026-01-02T14:30:00Z",
        },
    ),
    MarketSourceKind.CMC_GLOBAL: (
        "id",
        {
            "id": "global",
            "total_market_cap_usd": 1000,
            "last_updated": "2026-01-02T14:30:00Z",
        },
    ),
    MarketSourceKind.FRED: (
        "observation_id",
        {
            "observation_id": "WDTGAL:2020-01-01:2026-12-31",
            "series_id": "WDTGAL",
            "date": "2020-01-01",
            "realtime_start": "2026-12-31",
            "realtime_end": "2026-12-31",
            "value": 10,
        },
    ),
    MarketSourceKind.FOMC: (
        "id",
        {
            "id": "2026-01-28",
            "decision_date": "2026-01-28",
            "announcement_time_utc": "2026-01-28T19:00:00Z",
            "outcome": "hold",
            "source_url": "https://www.federalreserve.gov/pressreleases/monetary20260128a.htm",
        },
    ),
}


def _server(record):
    server = FastMCP("finance", version="1.0.0")

    @server.tool()
    def read(mode: str) -> list[dict]:
        return [record]

    return server


def _fred_server(records):
    server = FastMCP("finance", version="1.0.0")

    @server.tool()
    def read(mode: str) -> list[dict]:
        return records

    return server


def _adapter(kind, *, connector="finance", mode="delta"):
    preset = ToolPreset(
        name="market",
        server="finance",
        tool="read",
        id_field=CASES[kind][0],
        params_style="args",
        params={"mode": mode},
    )
    source = McpToolSourceAdapter(
        preset,
        connector="finance",
        mapping_reference="connector:finance#mappings/Record",
    )
    return MarketSourceAdapter(
        source, market_kind=kind, connector=connector, stream="market"
    )


@pytest.mark.spec("SDK-FINANCE-SOURCES-R001.2")
@pytest.mark.parametrize("kind", list(MarketSourceKind))
async def test_served_market_sources_reach_sink(kind):
    sink = InMemorySink()
    async with McpTransport().session(
        TransportEndpoint(in_process=_server(CASES[kind][1]))
    ) as session:
        outcome = await sync_stream(
            session, _adapter(kind), SyncTarget("finance", sink, max_pages=1)
        )
    assert outcome.accepted == 1
    assert next(iter(sink.batches.values())).records[0].payload == CASES[kind][1]


@pytest.mark.parametrize(
    "kind,changes",
    [
        (MarketSourceKind.EXCHANGE_CANDLE, {"close": float("inf")}),
        (MarketSourceKind.CMC_LISTING, {"price_usd": -1}),
        (MarketSourceKind.CMC_GLOBAL, {"total_market_cap_usd": float("nan")}),
        (MarketSourceKind.FRED, {"realtime_start": "2027-01-01"}),
        (MarketSourceKind.FOMC, {"announcement_time_utc": "2026-01-28T19:00:00"}),
    ],
)
async def test_invalid_market_records_refuse_before_sink(kind, changes):
    sink = InMemorySink()
    async with McpTransport().session(
        TransportEndpoint(in_process=_server({**CASES[kind][1], **changes}))
    ) as session:
        with pytest.raises(MalformedSourceDataError):
            await sync_stream(
                session, _adapter(kind), SyncTarget("finance", sink, max_pages=1)
            )
    assert not sink.batches


async def test_wrong_connector_and_full_sweep_refuse_before_sink():
    for adapter in (
        _adapter(MarketSourceKind.FRED, connector="other"),
        _adapter(MarketSourceKind.FRED, mode="full"),
    ):
        sink = InMemorySink()
        async with McpTransport().session(
            TransportEndpoint(in_process=_server(CASES[MarketSourceKind.FRED][1]))
        ) as session:
            with pytest.raises((MalformedSourceDataError, SourceContractError)):
                await sync_stream(
                    session, adapter, SyncTarget("finance", sink, max_pages=1)
                )
        assert not sink.batches


async def test_bounded_sources_never_claim_full_reconciliation():
    async with McpTransport().session(
        TransportEndpoint(in_process=_server(CASES[MarketSourceKind.FRED][1]))
    ) as session:
        with pytest.raises(SourceContractError, match="complete reconciliation"):
            await _adapter(MarketSourceKind.FRED).reconcile(session, frozenset({"old"}))


@pytest.mark.spec("SDK-FINANCE-SOURCES-R001.2")
async def test_fred_vintages_reach_sink_as_distinct_records():
    first = CASES[MarketSourceKind.FRED][1]
    second = {
        **first,
        "observation_id": "WDTGAL:2020-01-01:2027-01-01",
        "realtime_start": "2027-01-01",
        "realtime_end": "2027-01-01",
        "value": 11,
    }
    sink = InMemorySink()
    async with McpTransport().session(
        TransportEndpoint(in_process=_fred_server([first, second]))
    ) as session:
        outcome = await sync_stream(
            session,
            _adapter(MarketSourceKind.FRED),
            SyncTarget("finance", sink, max_pages=1),
        )
    assert outcome.records == 2
    assert [
        record.payload["realtime_start"]
        for record in next(iter(sink.batches.values())).records
    ] == ["2026-12-31", "2027-01-01"]
