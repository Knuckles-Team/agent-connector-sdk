"""Concrete market data providers (yfinance, AKShare, ccxt)."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class YFinanceProvider:
    """
    yfinance-based market data provider for global equities, ETFs, indices, and crypto.
    """

    @property
    def name(self) -> str:
        return "yfinance"

    def supports(self, symbol: str) -> bool:
        """yfinance supports most ticker formats."""
        return bool(symbol and len(symbol) <= 20)

    def fetch(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data from yfinance.

        Args:
            symbol: Ticker symbol (e.g., 'AAPL', 'BTC-USD').
            period: Data period ('1mo', '3mo', '1y', '5y', 'max').
            interval: Bar interval ('1d', '1h', '5m').
        """
        try:
            import yfinance as yf
        except ImportError as e:
            raise ImportError("yfinance is required. install scion-sdk[market]") from e

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)

        if df.empty:
            logger.warning(f"No data returned for {symbol} from yfinance")
            return pd.DataFrame()

        # Normalize columns
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.dropna(inplace=True)
        return df


_AKSHARE_COLUMNS = {
    "日期": "Date",
    "开盘": "Open",
    "收盘": "Close",
    "最高": "High",
    "最低": "Low",
    "成交量": "Volume",
}


def _akshare_frame(ak: Any, symbol: str) -> pd.DataFrame:
    """A-share daily bars with standard OHLCV columns (empty when none)."""
    df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="qfq")
    if df.empty:
        return pd.DataFrame()
    df = df.rename(columns=_AKSHARE_COLUMNS)
    df.set_index("Date", inplace=True)
    df.index = pd.to_datetime(df.index)
    return df[["Open", "High", "Low", "Close", "Volume"]]


class AKShareProvider:
    """
    AKShare-based market data provider for Chinese equities (A-shares) and index data.
    """

    @property
    def name(self) -> str:
        return "akshare"

    def supports(self, symbol: str) -> bool:
        """AKShare supports 6-digit Chinese tickers."""
        return bool(symbol and symbol.isdigit() and len(symbol) == 6)

    def fetch(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError as e:
            raise ImportError(
                "akshare is required for Chinese markets. install scion-sdk[market]"
            ) from e

        try:
            return _akshare_frame(ak, symbol)
        except Exception as e:
            logger.warning(f"AKShare fetch failed for {symbol}: {e}")
            return pd.DataFrame()


class CryptoProvider:
    """
    CCXT-based provider for global cryptocurrency exchange data (Binance, Coinbase, etc.).
    """

    @property
    def name(self) -> str:
        return "crypto"

    def supports(self, symbol: str) -> bool:
        """Crypto usually formatted as BASE/QUOTE (e.g. BTC/USDT)."""
        return "/" in symbol

    def fetch(
        self, symbol: str, period: str = "1y", interval: str = "1d"
    ) -> pd.DataFrame:
        try:
            import ccxt
        except ImportError as e:
            raise ImportError(
                "ccxt is required for crypto markets; install the ccxt package"
            ) from e

        from scion_sdk.finance.crypto_history import _fetch_crypto_history

        exchange = ccxt.binance({"enableRateLimit": True})
        return _fetch_crypto_history(exchange, symbol, period=period, interval=interval)
