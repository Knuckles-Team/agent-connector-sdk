"""Multi-asset MCP sources validate records before committing to the sink."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from agent_connector_sdk.adapters.mcp_tool import McpToolSourceAdapter
from agent_connector_sdk.finance.multi_asset_source import (
    MultiAssetKind,
    MultiAssetSourceAdapter,
)
from agent_connector_sdk.manifest.presets import ToolPreset
from agent_connector_sdk.ports.errors import MalformedSourceDataError
from agent_connector_sdk.ports.session import TransportEndpoint
from agent_connector_sdk.runner.syncing import SyncTarget, sync_stream
from agent_connector_sdk.testing.sinks import InMemorySink
from agent_connector_sdk.transports.mcp import McpTransport


def _base(event):
    return {
        "tenant_id": "tenant-1",
        "source_id": "finance-source",
        "provider": "fixture",
        "instrument_id": "ABC",
        "source_event_id": event,
        "event_time_utc": "2026-01-01T00:00:00Z",
        "observed_at_utc": "2026-01-31T00:00:00Z",
        "license_tag": "licensed",
        "source_digest": "sha256:fixture",
    }


def _server(records):
    server = FastMCP("finance", version="1.0.0")

    @server.tool()
    def read() -> list[dict[str, object]]:
        return records

    return server


def _adapter(kind, *, age=None):
    preset = ToolPreset(
        name="prices",
        server="finance",
        tool="read",
        id_field="source_event_id",
        params_style="args",
    )
    base = McpToolSourceAdapter(
        preset,
        connector="finance",
        mapping_reference="connector:finance#mappings/Record",
    )
    return MultiAssetSourceAdapter(
        base,
        asset_kind=kind,
        tenant_id="tenant-1",
        source_id="finance-source",
        real_estate_max_age_days=age,
    )


async def _sync(kind, records, *, age=None):
    adapter = _adapter(kind, age=age)
    sink = InMemorySink()
    async with McpTransport().session(
        TransportEndpoint(in_process=_server(records))
    ) as session:
        outcome = await sync_stream(
            session, adapter, SyncTarget("finance", sink, max_pages=1)
        )
    return sink, outcome


@pytest.mark.spec("SDK-FINANCE-SOURCES-R003.1")
async def test_served_sources_preserve_fx_direction_futures_and_staleness():
    fx = {**_base("fx-1"), "base_currency": "usd", "quote_currency": "eur", "rate": 0.9}
    spot = {**_base("spot-1"), "basis": "spot", "price": 2000, "currency": "USD"}
    future = {
        **_base("future-1"),
        "basis": "future",
        "price": 2010,
        "currency": "USD",
        "contract_code": "GCZ26",
        "expiry": "2026-12-01T00:00:00Z",
        "roll_rule": "monthly",
    }
    home = {
        **_base("home-1"),
        "valuation_date": "2026-01-01T00:00:00Z",
        "method": "appraisal",
        "currency": "USD",
        "estimated_value": 500000,
        "staleness_days": 30,
        "stale": True,
    }
    fx_sink, fx_outcome = await _sync(MultiAssetKind.FX, [fx])
    commodity_sink, commodity_outcome = await _sync(
        MultiAssetKind.COMMODITY, [spot, future]
    )
    home_sink, home_outcome = await _sync(MultiAssetKind.REAL_ESTATE, [home], age=10)
    assert (fx_outcome.accepted, commodity_outcome.accepted, home_outcome.accepted) == (
        1,
        2,
        1,
    )
    fx_record = next(iter(fx_sink.batches.values())).records[0]
    assert (
        fx_record.payload["base_currency"],
        fx_record.payload["quote_currency"],
        fx_record.payload["rate"],
    ) == ("USD", "EUR", 0.9)
    assert (
        fx_record.provenance.tool == "read"
        and fx_record.payload["license_tag"] == "licensed"
    )
    commodity = next(iter(commodity_sink.batches.values())).records
    assert commodity[0].payload["basis"] == "spot"
    assert (
        commodity[1].payload["contract_code"],
        commodity[1].payload["roll_rule"],
    ) == ("GCZ26", "monthly")
    valuation = next(iter(home_sink.batches.values())).records[0].payload
    assert (
        valuation["estimated_value"],
        valuation["staleness_days"],
        valuation["stale"],
        valuation["valuation_date"],
    ) == (500000, 30, True, "2026-01-01T00:00:00Z")


@pytest.mark.spec("SDK-FINANCE-SOURCES-R003.1")
@pytest.mark.parametrize(
    ("kind", "record", "age"),
    [
        (
            MultiAssetKind.FX,
            {**_base("x"), "base_currency": "USD", "quote_currency": "USD", "rate": 1},
            None,
        ),
        (
            MultiAssetKind.COMMODITY,
            {**_base("x"), "basis": "future", "price": 10, "currency": "USD"},
            None,
        ),
        (
            MultiAssetKind.REAL_ESTATE,
            {
                **_base("x"),
                "valuation_date": "2026-01-01T00:00:00Z",
                "method": "appraisal",
                "currency": "USD",
                "estimated_value": 500000,
                "staleness_days": 30,
                "stale": False,
            },
            10,
        ),
        (
            MultiAssetKind.REAL_ESTATE,
            {
                **_base("x"),
                "valuation_date": "2026-01-01T00:00:00Z",
                "method": "appraisal",
                "currency": "USD",
                "staleness_days": 30,
                "stale": True,
            },
            10,
        ),
        (
            MultiAssetKind.FX,
            {
                **_base("x"),
                "tenant_id": "private-other",
                "base_currency": "USD",
                "quote_currency": "EUR",
                "rate": 1,
            },
            None,
        ),
    ],
)
async def test_bad_domain_records_refuse_before_sink(kind, record, age):
    adapter = _adapter(kind, age=age)
    sink = InMemorySink()
    async with McpTransport().session(
        TransportEndpoint(in_process=_server([record]))
    ) as session:
        with pytest.raises(MalformedSourceDataError) as error:
            await sync_stream(
                session, adapter, SyncTarget("finance", sink, max_pages=1)
            )
    assert "private-other" not in str(error.value)
    assert not sink.batches


@pytest.mark.spec("SDK-FINANCE-SOURCES-R003.1")
async def test_duplicate_page_identity_refuses_before_sink():
    record = {
        **_base("same"),
        "base_currency": "USD",
        "quote_currency": "EUR",
        "rate": 1,
    }
    adapter = _adapter(MultiAssetKind.FX)
    sink = InMemorySink()
    async with McpTransport().session(
        TransportEndpoint(in_process=_server([record, record]))
    ) as session:
        with pytest.raises(MalformedSourceDataError, match="duplicate"):
            await sync_stream(
                session, adapter, SyncTarget("finance", sink, max_pages=1)
            )
    assert not sink.batches


@pytest.mark.spec("SDK-FINANCE-SOURCES-R003.1")
async def test_reconciliation_validates_source_before_comparing_ids():
    record = {
        **_base("fx-1"),
        "base_currency": "USD",
        "quote_currency": "EUR",
        "rate": 1,
    }
    adapter = _adapter(MultiAssetKind.FX)
    async with McpTransport().session(
        TransportEndpoint(in_process=_server([record]))
    ) as session:
        report = await adapter.reconcile(session, frozenset({"old"}))
    assert report.missing_from_source == ("old",)
    assert report.unknown_to_sink == ("fx-1",)
    record["rate"] = 0
    async with McpTransport().session(
        TransportEndpoint(in_process=_server([record]))
    ) as session:
        with pytest.raises(MalformedSourceDataError):
            await adapter.reconcile(session, frozenset({"old"}))
