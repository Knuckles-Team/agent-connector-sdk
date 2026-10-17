"""Crypto market data clients: DEX volume, protocol TVL and funding rates.

Requests go through the DNS-pinned egress boundary of
:mod:`agent_connector_sdk.source_connectors.http_safety`. A missing or
malformed upstream answer raises
:class:`~agent_connector_sdk.finance.errors.ProviderRequestError`; no client
returns a placeholder value.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_connector_sdk.source_connectors.http_safety import (
    SourceEgressError,
    safe_get_json,
)

from .errors import ProviderRequestError

logger = logging.getLogger(__name__)

_DEFILLAMA_BASE = "https://api.llama.fi"
_BINANCE_FUTURES = "https://fapi.binance.com"


def _http_get_json(url: str, timeout: float = 10.0) -> Any:
    """GET bounded JSON through the canonical DNS-pinned egress boundary."""
    try:
        return safe_get_json(
            url,
            timeout=timeout,
            max_bytes=2 * 1024 * 1024,
            max_redirects=0,
        )
    except (SourceEgressError, TimeoutError, ValueError) as exc:
        raise ProviderRequestError("finance provider request failed") from exc


@dataclass
class FundingRate:
    """A perpetual-futures funding rate observation."""

    symbol: str
    rate: float
    timestamp: float
    exchange: str


GetJson = Callable[[str], Any]


class OnChainAnalytics:
    """Keyless DeFi metrics from the DeFiLlama API."""

    def __init__(self, get_json: GetJson = _http_get_json) -> None:
        self._get_json = get_json

    def get_dex_volume(self, protocol: str = "uniswap") -> float:
        """24-hour DEX volume in USD."""
        data = self._get_json(
            f"{_DEFILLAMA_BASE}/summary/dexs/{protocol}?dataType=dailyVolume"
        )
        volume = data.get("total24h") if isinstance(data, dict) else None
        if volume is None:
            raise ProviderRequestError(f"no 24h volume for protocol {protocol!r}")
        return float(volume)

    def get_tvl(self, protocol: str) -> float:
        """Total value locked in USD."""
        data = self._get_json(f"{_DEFILLAMA_BASE}/tvl/{protocol}")
        try:
            return float(data)
        except (TypeError, ValueError) as exc:
            raise ProviderRequestError(f"no TVL for protocol {protocol!r}") from exc


class CryptoDerivatives:
    """Keyless perpetual-futures data from the Binance futures API."""

    def __init__(self, get_json: GetJson = _http_get_json) -> None:
        self._get_json = get_json

    def get_funding_rate(self, symbol: str) -> FundingRate:
        """The current funding rate for ``symbol`` (for example ``BTC/USDT``)."""
        pair = symbol.replace("/", "").upper()
        data = self._get_json(f"{_BINANCE_FUTURES}/fapi/v1/premiumIndex?symbol={pair}")
        if not isinstance(data, dict) or "lastFundingRate" not in data:
            raise ProviderRequestError(f"no funding rate for symbol {symbol!r}")
        return FundingRate(
            symbol=symbol,
            rate=float(data["lastFundingRate"]),
            timestamp=float(data.get("time", time.time() * 1000)) / 1000.0,
            exchange="binance",
        )
