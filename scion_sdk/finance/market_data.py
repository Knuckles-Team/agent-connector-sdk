"""Market data providers with an ordered fallback chain.

Each provider returns real data from its upstream source, or raises or returns
an empty result so :class:`DataRegistry` falls through to the next provider.
No provider fabricates prices. The ``market`` extra supplies pandas and the
provider clients.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

try:
    import pandas as pd
except ImportError as e:
    raise ImportError('market data needs pandas; install "scion-sdk[market]"') from e

from scion_sdk.finance._market_providers import (
    AKShareProvider,
    CryptoProvider,
    YFinanceProvider,
)

logger = logging.getLogger(__name__)


@dataclass
class DataFetchResult:
    """Result of a market data fetch including provenance metadata."""

    data: pd.DataFrame
    provider: str
    symbol: str
    interval: str
    fetched_at: str = ""
    row_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.fetched_at:
            self.fetched_at = datetime.now(UTC).isoformat()
        self.row_count = len(self.data) if self.data is not None else 0


@runtime_checkable
class MarketDataProvider(Protocol):
    """Protocol for market data providers — any class implementing this interface is a valid provider."""

    @property
    def name(self) -> str:
        return "protocol"

    def fetch(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        return pd.DataFrame()

    def supports(self, symbol: str) -> bool:
        return False


__all__ = [
    "AKShareProvider",
    "CryptoProvider",
    "DataFetchResult",
    "DataRegistry",
    "MarketDataProvider",
    "YFinanceProvider",
    "normalize_ohlcv",
]


class DataRegistry:
    """
    Auto-fallback data registry — tries providers in priority order
    and returns the first successful result.
    """

    def __init__(self, providers: list[MarketDataProvider] | None = None) -> None:
        if providers is not None:
            self._providers = providers
        else:
            # Default chain: yfinance → akshare → crypto. Each provider either
            # returns real market data or raises/returns empty — none of them
            # fabricates a result.
            self._providers = [
                YFinanceProvider(),
                AKShareProvider(),
                CryptoProvider(),
            ]

    def add_provider(
        self, provider: MarketDataProvider, priority: int | None = None
    ) -> None:
        """Add a data provider. Lower priority index = higher priority."""
        if priority is not None:
            self._providers.insert(priority, provider)
        else:
            self._providers.append(provider)

    def fetch(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> DataFetchResult:
        """
        Fetch data using the fallback chain. Returns the first successful result.
        """
        warnings: list[str] = []

        for provider in self._providers:
            result = self._try_provider(provider, symbol, period, interval, warnings)
            if result is not None:
                return result

        logger.error(f"All providers failed for {symbol}")
        return DataFetchResult(
            data=pd.DataFrame(),
            provider="none",
            symbol=symbol,
            interval=interval,
            warnings=warnings,
        )

    @staticmethod
    def _try_provider(
        provider: MarketDataProvider,
        symbol: str,
        period: str,
        interval: str,
        warnings: list[str],
    ) -> DataFetchResult | None:
        if not provider.supports(symbol):
            warnings.append(f"{provider.name}: does not support {symbol}")
            return None
        try:
            df = provider.fetch(symbol, period=period, interval=interval)
        except Exception as e:
            warnings.append(f"{provider.name}: {e}")
            logger.warning(f"Provider {provider.name} failed for {symbol}: {e}")
            return None
        if df is None or df.empty:
            warnings.append(f"{provider.name}: returned empty data")
            return None
        logger.info(f"Fetched {len(df)} bars for {symbol} from {provider.name}")
        return DataFetchResult(
            data=df,
            provider=provider.name,
            symbol=symbol,
            interval=interval,
            warnings=warnings,
        )

    @property
    def provider_names(self) -> list[str]:
        """List registered provider names in priority order."""
        return [p.name for p in self._providers]


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize an OHLCV DataFrame to standard column names.
    Handles common variations (lowercase, uppercase, mixed case).
    """
    col_map = {}
    for col in df.columns:
        lower = col.lower().strip()
        if lower in ("open", "o"):
            col_map[col] = "Open"
        elif lower in ("high", "h"):
            col_map[col] = "High"
        elif lower in ("low", "l"):
            col_map[col] = "Low"
        elif lower in ("close", "c", "adj close", "adj_close"):
            col_map[col] = "Close"
        elif lower in ("volume", "vol", "v"):
            col_map[col] = "Volume"

    return df.rename(columns=col_map)
