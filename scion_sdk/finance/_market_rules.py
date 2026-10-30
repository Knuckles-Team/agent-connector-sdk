"""Per-kind payload rules for market sources."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from scion_sdk.finance._market_cmc import _cmc_global, _cmc_listing
from scion_sdk.finance._stock_fields import _date, _number, _text, _time

if TYPE_CHECKING:
    from scion_sdk.finance.market_source import MarketSourceKind


def _candle(data: dict[str, Any]) -> None:
    for field in ("exchange", "symbol", "interval", "license_tag"):
        _text(data, field)
    _time(data.get("timestamp"))
    open_, high, low, close, _volume = (
        _number(data.get(field), nonnegative=True)
        for field in ("open", "high", "low", "close", "volume")
    )
    if high < max(open_, low, close) or low > min(open_, high, close):
        raise ValueError("invalid candle prices")


def _fred(data: dict[str, Any]) -> None:
    series = _text(data, "series_id")
    _date(data.get("date"))
    _date(data.get("realtime_start"))
    if data.get("realtime_end") is not None:
        _date(data["realtime_end"])
    if (
        data.get("observation_id")
        != f"{series}:{data['date']}:{data['realtime_start']}"
    ):
        raise ValueError("invalid observation identity")
    if "value" in data:
        _number(data["value"])


def _fomc(data: dict[str, Any]) -> None:
    _date(data.get("decision_date"))
    if data.get("id") != data["decision_date"]:
        raise ValueError("invalid announcement identity")
    _time(data.get("announcement_time_utc"))
    source = urlsplit(_text(data, "source_url"))
    if source.scheme != "https" or source.netloc != "www.federalreserve.gov":
        raise ValueError("invalid announcement provenance")
    if data.get("outcome") not in {"hike", "cut", "hold"}:
        raise ValueError("invalid announcement outcome")


def _etf(data: dict[str, Any]) -> None:
    _text(data, "ticker")
    _number(data.get("net_flow_usd"))


def _sentiment(data: dict[str, Any]) -> None:
    _number(data.get("value"))


def _onchain(data: dict[str, Any]) -> None:
    wallet = _text(data, "wallet")
    if not re.fullmatch(r"0x[0-9a-f]{40}", wallet):
        raise ValueError("invalid on-chain identity")
    _text(data, "symbol")
    _number(data.get("position_size"))
    _number(data.get("entry_price"), nonnegative=True)
    _number(data.get("mark_price"), nonnegative=True)


def _panel(data: dict[str, Any], kind: MarketSourceKind) -> None:
    if data.get("dataset") != kind.value or data.get("provider") != "coinglass":
        raise ValueError("invalid macro source provenance")
    _text(data, "license_tag")
    _time(data.get("event_time"))
    _time(data.get("observed_at"))
    {"etf": _etf, "sentiment": _sentiment, "onchain": _onchain}[kind.value](data)


_BY_KIND = {
    "exchange_candle": _candle,
    "cmc_listing": _cmc_listing,
    "cmc_global": _cmc_global,
    "fred": _fred,
    "fomc": _fomc,
}


def _check_market(kind: MarketSourceKind, data: dict[str, Any]) -> None:
    """Validate one market payload by kind."""
    rule = _BY_KIND.get(kind.value)
    if rule is not None:
        rule(data)
    else:
        _panel(data, kind)
