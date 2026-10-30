"""Stock source adapter validates pages before source-to-sink delivery."""

from __future__ import annotations

import base64
import hashlib

import pytest
from finance_source_support import record_server, served_session, sync_page

from scion_sdk.adapters.mcp_tool import McpToolSourceAdapter
from scion_sdk.finance.stock_source import StockSourceAdapter, StockSourceKind
from scion_sdk.manifest.presets import ToolPreset
from scion_sdk.ports.errors import (
    MalformedSourceDataError,
    SourceContractError,
)
from scion_sdk.runner.syncing import SyncTarget, sync_stream
from scion_sdk.testing.sinks import InMemorySink

PNG = b"\x89PNG\r\n\x1a\nfixture"
COMMON = {"symbol": "AAPL", "license_tag": "operator-license"}
COMPANY = {
    **COMMON,
    "record_id": "1",
    "provider": "financialmodelingprep",
    "observed_at": "2026-01-01T00:00:00Z",
}
CASES = {
    StockSourceKind.BAR: {
        **COMMON,
        "bar_id": "1",
        "timestamp": "2026-01-02T14:30:00Z",
        "feed": "iex",
        "timeframe": "1Min",
        "adjustment": "split",
        "session_scope": "alpaca_calendar",
        "session": "regular",
        "open": 1,
        "high": 2,
        "low": 1,
        "close": 2,
        "volume": 5,
    },
    StockSourceKind.QUOTE: {
        **COMMON,
        "quote_id": "1",
        "timestamp": "2026-01-02T14:30:00Z",
        "feed": "iex",
        "session_scope": "feed_native",
        "bid": 1,
        "ask": 2,
        "bid_size": 3,
        "ask_size": 4,
    },
    StockSourceKind.NEWS: {
        **COMMON,
        "news_id": "1",
        "headline": "News",
        "author": "Reporter",
        "source": "wire",
        "created_at": "2026-01-02T14:30:00Z",
        "updated_at": "2026-01-02T14:31:00Z",
    },
    StockSourceKind.DIVIDEND: {
        **COMMON,
        "dividend_id": "1",
        "kind": "cash",
        "rate": 0.5,
        "process_date": "2026-01-02",
        "ex_date": "2026-01-01",
    },
    StockSourceKind.PROFILE: {**COMPANY, "dataset": "profile", "company_name": "Apple"},
    StockSourceKind.INCOME: {
        **COMPANY,
        "dataset": "income",
        "period_date": "2025-09-27",
        "period": "FY",
        "currency": "USD",
        "revenue": 100,
        "net_income": -2,
    },
    StockSourceKind.EARNINGS: {
        **COMPANY,
        "dataset": "earnings",
        "announcement_date": "2026-07-30",
        "eps_estimated": 1.88,
    },
    StockSourceKind.LOGO: {
        **COMPANY,
        "dataset": "logo",
        "image_media_type": "image/png",
        "image_base64": base64.b64encode(PNG).decode(),
        "image_sha256": hashlib.sha256(PNG).hexdigest(),
    },
}
IDS = {kind: "record_id" for kind in StockSourceKind} | {
    StockSourceKind.BAR: "bar_id",
    StockSourceKind.QUOTE: "quote_id",
    StockSourceKind.NEWS: "news_id",
    StockSourceKind.DIVIDEND: "dividend_id",
}


def _server(record):
    return record_server(record)


def _adapter(kind, *, mode="delta"):
    preset = ToolPreset(
        name="stock",
        server="finance",
        tool="read",
        id_field=IDS[kind],
        params_style="args",
        params={"mode": mode},
    )
    return StockSourceAdapter(
        McpToolSourceAdapter(
            preset,
            connector="finance",
            mapping_reference="connector:finance#mappings/Record",
        ),
        stock_kind=kind,
        symbol="AAPL",
    )


@pytest.mark.spec("SCION-FINANCE-SOURCES-R002.1")
@pytest.mark.parametrize("kind", list(StockSourceKind))
async def test_served_stock_records_reach_sink(kind):
    sink = InMemorySink()
    async with served_session(_server(CASES[kind])) as session:
        outcome = await sync_page(session, _adapter(kind), sink, "finance")
    assert outcome.accepted == 1
    assert next(iter(sink.batches.values())).records[0].payload == CASES[kind]


@pytest.mark.parametrize(
    "kind,changes",
    [
        (StockSourceKind.BAR, {"close": float("inf")}),
        (StockSourceKind.BAR, {"session": "made-up"}),
        (StockSourceKind.NEWS, {"symbol": "private-other"}),
        (StockSourceKind.DIVIDEND, {"rate": -1}),
        (StockSourceKind.INCOME, {"dataset": "profile"}),
        (StockSourceKind.LOGO, {"image_sha256": "bad"}),
    ],
)
async def test_bad_records_refuse_before_sink(kind, changes):
    sink = InMemorySink()
    async with served_session(_server({**CASES[kind], **changes})) as session:
        with pytest.raises(MalformedSourceDataError) as error:
            await sync_page(session, _adapter(kind), sink, "finance")
    assert "private-other" not in str(error.value)
    assert not sink.batches


async def test_bounded_source_never_claims_full_reconciliation():
    async with served_session(_server(CASES[StockSourceKind.BAR])) as session:
        with pytest.raises(SourceContractError, match="complete reconciliation"):
            await _adapter(StockSourceKind.BAR).reconcile(session, frozenset({"old"}))


async def test_bounded_source_refuses_full_mode_before_sink():
    sink = InMemorySink()
    async with served_session(_server(CASES[StockSourceKind.BAR])) as session:
        with pytest.raises(SourceContractError, match="delta pages"):
            await sync_stream(
                session,
                _adapter(StockSourceKind.BAR, mode="full"),
                SyncTarget("finance", sink, max_pages=1),
            )
    assert not sink.batches


@pytest.mark.spec("SCION-FINANCE-SOURCES-R002.1")
@pytest.mark.parametrize("adjustment", ["raw", "split", "dividend", "spin-off", "all"])
@pytest.mark.parametrize(
    "session_label", ["pre_market", "regular", "post_market", "outside_session"]
)
async def test_stock_source_preserves_adjustment_and_calendar_session(
    adjustment, session_label
):
    record = {
        **CASES[StockSourceKind.BAR],
        "adjustment": adjustment,
        "session": session_label,
    }
    sink = InMemorySink()
    async with served_session(_server(record)) as session:
        outcome = await sync_page(
            session, _adapter(StockSourceKind.BAR), sink, "finance"
        )
    assert outcome.accepted == 1
    actual = next(iter(sink.batches.values())).records[0].payload
    assert (actual["adjustment"], actual["session"]) == (adjustment, session_label)
