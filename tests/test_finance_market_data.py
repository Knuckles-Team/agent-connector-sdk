"""Market data registry: ordered fallback, no fabricated data, column normalization."""

from __future__ import annotations

from typing import Any

import pytest

pd = pytest.importorskip("pandas")

from agent_connector_sdk.finance.market_data import (  # noqa: E402
    AKShareProvider,
    CryptoProvider,
    DataFetchResult,
    DataRegistry,
    MarketDataProvider,
    YFinanceProvider,
    normalize_ohlcv,
)


class _Provider:
    """In-memory provider: returns ``frame``, raises ``error`` or skips the symbol."""

    def __init__(
        self,
        name: str,
        frame: Any = None,
        error: Exception | None = None,
        supports=True,
    ) -> None:
        self.name = name
        self._frame = frame
        self._error = error
        self._supports = supports

    def supports(self, symbol: str) -> bool:
        return self._supports

    def fetch(self, symbol: str, **_: Any) -> Any:
        if self._error is not None:
            raise self._error
        return self._frame


BARS = pd.DataFrame(
    {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [9.0]}
)


@pytest.mark.spec("SCION-FINANCE-SOURCES-R900.2")
def test_first_non_empty_provider_wins_and_failures_become_warnings() -> None:
    registry = DataRegistry(
        providers=[
            _Provider("skip", supports=False),
            _Provider("broken", error=ConnectionError("down")),
            _Provider("empty", frame=pd.DataFrame()),
        ]
    )
    registry.add_provider(_Provider("real", frame=BARS))
    result = registry.fetch("TEST")
    assert (result.provider, result.row_count) == ("real", 1)
    assert registry.provider_names == ["skip", "broken", "empty", "real"]
    assert [w.split(":")[0] for w in result.warnings] == ["skip", "broken", "empty"]
    assert result.fetched_at


def test_no_provider_yields_an_empty_result_not_fabricated_data() -> None:
    result = DataRegistry(providers=[_Provider("empty", frame=pd.DataFrame())]).fetch(
        "X"
    )
    assert (result.provider, result.row_count) == ("none", 0)


@pytest.mark.parametrize(
    ("columns", "expected"),
    [
        (
            ["open", "high", "low", "close", "volume"],
            {"Open", "High", "Low", "Close", "Volume"},
        ),
        (
            ["OPEN", "High", "low", "Close", "vol"],
            {"Open", "High", "Low", "Close", "Volume"},
        ),
        (["adj close"], {"Close"}),
    ],
)
def test_normalize_ohlcv_maps_column_variants(
    columns: list[str], expected: set[str]
) -> None:
    frame = pd.DataFrame({name: [1.0] for name in columns})
    assert set(normalize_ohlcv(frame).columns) == expected


@pytest.mark.parametrize(
    ("provider", "symbol", "supported"),
    [
        (YFinanceProvider(), "AAPL", True),
        (YFinanceProvider(), "", False),
        (AKShareProvider(), "600519", True),
        (AKShareProvider(), "AAPL", False),
        (CryptoProvider(), "BTC/USDT", True),
        (CryptoProvider(), "AAPL", False),
    ],
)
def test_default_providers_route_symbols(
    provider: object, symbol: str, supported: bool
) -> None:
    assert isinstance(provider, MarketDataProvider)
    assert provider.supports(symbol) is supported


def test_fetch_result_counts_rows() -> None:
    result = DataFetchResult(data=BARS, provider="p", symbol="S", interval="1d")
    assert result.row_count == 1 and result.fetched_at
