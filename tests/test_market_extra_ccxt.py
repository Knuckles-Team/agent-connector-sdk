"""The market extra includes the exchange client used by the provider."""

from __future__ import annotations

import pytest


@pytest.mark.spec("SDK-FINANCE-SOURCES-R001.8")
def test_market_extra_supplies_real_exchange_client() -> None:
    ccxt = pytest.importorskip("ccxt")
    from agent_connector_sdk.finance.market_data import CryptoProvider

    exchange = ccxt.binance({"enableRateLimit": True})
    assert callable(exchange.fetch_ohlcv)
    assert CryptoProvider().supports("BTC/USDT")
