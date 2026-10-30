"""CoinMarketCap payload rules for market sources."""

from __future__ import annotations

from typing import Any

from scion_sdk.finance._stock_fields import _number, _text, _time

_CMC_LISTING_FIELDS = (
    "price_usd",
    "market_cap_usd",
    "volume_24h_usd",
    "circulating_supply",
    "total_supply",
    "max_supply",
)
_CMC_GLOBAL_FIELDS = (
    "total_market_cap_usd",
    "total_volume_24h_usd",
    "btc_dominance",
    "eth_dominance",
    "active_cryptocurrencies",
)


def _cmc_identifier(identifier: str) -> None:
    if (
        not identifier.isascii()
        or not identifier.isdecimal()
        or str(int(identifier)) != identifier
        or int(identifier) <= 0
    ):
        raise ValueError("invalid CMC identity")


def _cmc_tail(data: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        if field in data:
            _number(data[field], nonnegative=True)
    _time(data.get("last_updated"))
    for field in ("percent_change_24h", "percent_change_7d"):
        if field in data:
            _number(data[field])


def _cmc_listing(data: dict[str, Any]) -> None:
    _text(data, "symbol")
    _text(data, "name")
    _cmc_identifier(_text(data, "cmc_id"))
    _number(data.get("price_usd"), nonnegative=True)
    _cmc_tail(data, _CMC_LISTING_FIELDS)


def _cmc_global(data: dict[str, Any]) -> None:
    if data.get("id") != "global":
        raise ValueError("invalid global market identity")
    _number(data.get("total_market_cap_usd"), nonnegative=True)
    _cmc_tail(data, _CMC_GLOBAL_FIELDS)
