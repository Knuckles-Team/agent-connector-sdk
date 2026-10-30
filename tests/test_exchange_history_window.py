"""Offline exchange pagination through the real market-data provider."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from scion_sdk.finance import crypto_history
from scion_sdk.finance.errors import (
    InvalidIntervalError,
    ProviderRequestError,
)
from scion_sdk.finance.market_data import CryptoProvider


class _Exchange:
    def __init__(self, pages: list[list[list[object]]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, str, int, int]] = []

    def fetch_ohlcv(
        self, symbol: str, *, timeframe: str, since: int, limit: int
    ) -> list[list[object]]:
        self.calls.append((symbol, timeframe, since, limit))
        return self.pages.pop(0)


def _bar(stamp: int) -> list[object]:
    return [stamp, 1.0, 2.0, 0.5, 1.5, 10.0]


def _install(monkeypatch: pytest.MonkeyPatch, exchange: _Exchange) -> tuple[int, int]:
    now = pd.Timestamp("2026-01-01T00:00:00Z")
    monkeypatch.setattr(crypto_history, "_utc_now", lambda: now)
    monkeypatch.setitem(
        sys.modules, "ccxt", SimpleNamespace(binance=lambda options: exchange)
    )
    return int((now - pd.DateOffset(years=5)).timestamp() * 1000), int(
        now.timestamp() * 1000
    )


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.7")
def test_exchange_provider_honors_history_window_and_reads_multiple_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = _Exchange([])
    start, end = _install(monkeypatch, exchange)
    exchange.pages = [[_bar(start), _bar(start + 86_400_000)], [_bar(end - 86_400_000)]]
    result = CryptoProvider().fetch("BTC/USDT", period="5y", interval="1d")
    assert len(result) == 3
    assert result.index.tz is not None
    assert exchange.calls == [
        ("BTC/USDT", "1d", start, 1000),
        ("BTC/USDT", "1d", start + 86_400_001, 1000),
    ]


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.7")
def test_exchange_provider_refuses_invalid_requests_and_nonadvancing_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = _Exchange([])
    start, _ = _install(monkeypatch, exchange)
    for period, interval in (("max", "1d"), ("1y", "1m")):
        with pytest.raises(InvalidIntervalError):
            CryptoProvider().fetch("BTC/USDT", period=period, interval=interval)
    assert exchange.calls == []
    exchange.pages = [[_bar(start)], [_bar(start)]]
    with pytest.raises(ProviderRequestError, match="timestamps"):
        CryptoProvider().fetch("BTC/USDT", period="5y", interval="1d")


@pytest.mark.spec("SCION-FINANCE-SOURCES-R001.7")
def test_exchange_history_refuses_incomplete_or_nonfinite_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange = _Exchange([])
    start, _ = _install(monkeypatch, exchange)
    bad = _bar(start)
    bad[4] = float("nan")
    exchange.pages = [[bad]]
    with pytest.raises(ProviderRequestError, match="values"):
        CryptoProvider().fetch("BTC/USDT", period="5y", interval="1d")
    monkeypatch.setattr(crypto_history, "_MAX_PAGES", 2)
    exchange.pages = [[_bar(start)], [_bar(start + 86_400_000)]]
    with pytest.raises(ProviderRequestError, match="page limit"):
        CryptoProvider().fetch("BTC/USDT", period="5y", interval="1d")
