"""Crypto market data clients parse upstream answers and refuse malformed ones."""

from __future__ import annotations

from typing import Any

import pytest

from agent_connector_sdk.finance.crypto import (
    CryptoDerivatives,
    FundingRate,
    OnChainAnalytics,
)
from agent_connector_sdk.finance.errors import (
    FinanceProviderError,
    InvalidIntervalError,
    ProviderNotConfigured,
    ProviderRequestError,
)


def _serve(answer: Any) -> tuple[list[str], Any]:
    urls: list[str] = []

    def get_json(url: str) -> Any:
        urls.append(url)
        return answer

    return urls, get_json


def test_parses_dex_volume_tvl_and_funding_rate() -> None:
    urls, get_json = _serve({"total24h": "12.5"})
    assert OnChainAnalytics(get_json).get_dex_volume("uniswap") == 12.5
    assert urls[0].endswith("/summary/dexs/uniswap?dataType=dailyVolume")
    _, get_json = _serve("99.0")
    assert OnChainAnalytics(get_json).get_tvl("aave") == 99.0
    urls, get_json = _serve({"lastFundingRate": "0.0001", "time": 1_700_000_000_000})
    rate = CryptoDerivatives(get_json).get_funding_rate("btc/usdt")
    assert (rate.rate, rate.timestamp, rate.exchange) == (
        0.0001,
        1_700_000_000.0,
        "binance",
    )
    assert urls[0].endswith("symbol=BTCUSDT")


# spec: SDK-FINANCE-SOURCES-R900.4
@pytest.mark.parametrize(
    "call",
    [
        lambda g: OnChainAnalytics(g).get_dex_volume(),
        lambda g: OnChainAnalytics(g).get_tvl("aave"),
        lambda g: CryptoDerivatives(g).get_funding_rate("BTC/USDT"),
    ],
)
def test_malformed_answers_raise_provider_request_error(call: Any) -> None:
    with pytest.raises(ProviderRequestError):
        call(_serve({"unexpected": True})[1])


def test_funding_rate_is_a_typed_record() -> None:
    _, get_json = _serve({"lastFundingRate": "0.5", "time": 0})
    assert isinstance(CryptoDerivatives(get_json).get_funding_rate("X/Y"), FundingRate)


@pytest.mark.parametrize(
    ("error", "bases"),
    [
        (ProviderNotConfigured, (FinanceProviderError, RuntimeError)),
        (ProviderRequestError, (FinanceProviderError, RuntimeError)),
        (InvalidIntervalError, (FinanceProviderError, ValueError)),
    ],
)
def test_error_hierarchy_lets_callers_catch_by_family(
    error: type, bases: tuple
) -> None:
    assert issubclass(error, bases)
