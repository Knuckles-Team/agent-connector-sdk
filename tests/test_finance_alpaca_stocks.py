"""FS-01/FS-02: Alpaca stock bars map to OhlcvBar; no silent truncation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_connector_sdk.finance.alpaca_stocks import ohlcv_bars_from_alpaca
from agent_connector_sdk.finance.records import AdjustmentMode, Completeness

_OBSERVED = datetime(2026, 1, 2, 0, 5, tzinfo=UTC)

_PAGE = {
    "bars": [
        {
            "t": "2026-01-02T00:00:00Z",
            "o": 100.0,
            "h": 101.0,
            "l": 99.5,
            "c": 100.5,
            "v": 1000.0,
        },
        {
            "t": "2026-01-03T00:00:00Z",
            "o": 100.5,
            "h": 102.0,
            "l": 100.0,
            "c": 101.5,
            "v": 1200.0,
        },
    ],
    "symbol": "AAPL",
    "next_page_token": None,
}


def _bars(**overrides: object) -> tuple:
    fields: dict[str, object] = {
        "payload": _PAGE,
        "tenant_id": "tenant-1",
        "source_id": "alpaca",
        "provider": "alpaca",
        "symbol": "AAPL",
        "license_tag": "licensed",
        "timeframe": "1d",
        "session_calendar": "XNYS",
        "currency": "USD",
        "adjustment_mode": AdjustmentMode.RAW,
        "observed_at_utc": _OBSERVED,
    }
    fields.update(overrides)
    return ohlcv_bars_from_alpaca(**fields)


@pytest.mark.spec("SDK-FINANCE-SOURCES-R002")
def test_every_bar_in_the_page_maps_in_deterministic_order() -> None:
    bars = _bars()

    assert len(bars) == 2
    assert [bar.event_time_utc for bar in bars] == [
        datetime(2026, 1, 2, tzinfo=UTC),
        datetime(2026, 1, 3, tzinfo=UTC),
    ]
    assert bars[0].instrument_id == "AAPL"
    assert bars[0].close == 100.5


@pytest.mark.spec("SDK-FINANCE-SOURCES-R002")
def test_adjustment_mode_is_the_caller_s_explicit_request() -> None:
    bars = _bars(adjustment_mode=AdjustmentMode.ADJUSTED)
    assert all(bar.adjustment_mode is AdjustmentMode.ADJUSTED for bar in bars)


@pytest.mark.spec("SDK-FINANCE-SOURCES-R002")
def test_a_page_with_no_next_token_is_complete() -> None:
    bars = _bars()
    assert all(bar.completeness is Completeness.COMPLETE for bar in bars)


def test_a_page_with_a_next_token_is_partial_not_silently_complete() -> None:
    paged = {**_PAGE, "next_page_token": "cursor-2"}
    bars = _bars(payload=paged)
    assert all(bar.completeness is Completeness.PARTIAL for bar in bars)


def test_rereading_the_same_bar_yields_the_same_identity() -> None:
    first = _bars()
    second = _bars()
    assert [b.source_event_id for b in first] == [b.source_event_id for b in second]
