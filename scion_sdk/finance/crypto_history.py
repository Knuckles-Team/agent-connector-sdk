"""Bounded exchange OHLCV history for the market data provider."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from scion_sdk.finance.errors import (
    InvalidIntervalError,
    ProviderRequestError,
)

_PAGE_SIZE = 1000
_MAX_PAGES = 128
_INTERVAL_MS = {"5m": 300_000, "1h": 3_600_000, "1d": 86_400_000}
_PERIODS = {
    "1mo": ("months", 1),
    "3mo": ("months", 3),
    "1y": ("years", 1),
    "5y": ("years", 5),
}


def _fetch_crypto_history(
    exchange: Any, symbol: str, *, period: str, interval: str
) -> pd.DataFrame:
    """Fetch a requested time window, refusing malformed or incomplete pages."""
    if period not in _PERIODS or interval not in _INTERVAL_MS:
        raise InvalidIntervalError("unsupported exchange history period or interval")
    now = _utc_now()
    unit, amount = _PERIODS[period]
    start = now - pd.DateOffset(**{unit: amount})
    cursor = int(start.timestamp() * 1000)
    end = int(now.timestamp() * 1000)
    rows: list[list[Any]] = []
    for _ in range(_MAX_PAGES):
        page = exchange.fetch_ohlcv(
            symbol, timeframe=interval, since=cursor, limit=_PAGE_SIZE
        )
        if not isinstance(page, list) or len(page) > _PAGE_SIZE:
            raise ProviderRequestError("invalid exchange history page")
        if not page:
            return _frame(rows)
        cursor = _append_page(rows, page, cursor=cursor, end=end)
        if cursor > end - _INTERVAL_MS[interval]:
            return _frame(rows)
    raise ProviderRequestError("exchange history exceeds page limit")


def _append_page(
    rows: list[list[Any]], page: list[Any], *, cursor: int, end: int
) -> int:
    previous = cursor - 1
    for bar in page:
        if not isinstance(bar, (list, tuple)) or len(bar) != 6:
            raise ProviderRequestError("invalid exchange history bar")
        stamp = bar[0]
        if type(stamp) is not int or stamp <= previous or stamp > end:
            raise ProviderRequestError("exchange history timestamps are invalid")
        if any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in bar[1:]
        ):
            raise ProviderRequestError("exchange history values are invalid")
        rows.append(list(bar))
        previous = stamp
    return previous + 1


def _frame(rows: list[list[Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(
        rows, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"]
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    return frame.set_index("timestamp")


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")
