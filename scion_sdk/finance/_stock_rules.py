"""Per-kind payload rules for stock sources."""

from __future__ import annotations

from typing import Any

from scion_sdk.finance._stock_company import _check_company
from scion_sdk.finance._stock_fields import _date, _number, _text, _time

_ADJUSTMENTS = {"raw", "split", "dividend", "spin-off", "all"}
_SESSIONS = {"pre_market", "regular", "post_market", "outside_session"}
_PRICE_FIELDS = ("open", "high", "low", "close", "volume")
_QUOTE_FIELDS = ("bid", "ask", "bid_size", "ask_size")


def _bar(data: dict[str, Any], scope: str) -> None:
    _text(data, "timeframe")
    if data.get("adjustment") not in _ADJUSTMENTS:
        raise ValueError("invalid stock adjustment")
    o, h, low, close, _volume = (
        _number(data.get(k), nonnegative=True) for k in _PRICE_FIELDS
    )
    if h < max(o, low, close) or low > min(o, h, close):
        raise ValueError("invalid stock prices")
    if scope == "alpaca_calendar" and data.get("session") not in _SESSIONS:
        raise ValueError("invalid stock session")


def _quote(data: dict[str, Any], scope: str) -> None:
    del scope
    for field in _QUOTE_FIELDS:
        _number(data.get(field), nonnegative=True)


def _market(data: dict[str, Any], kind: str) -> None:
    _time(data.get("timestamp"))
    _text(data, "feed")
    scope = _text(data, "session_scope")
    if scope not in {"feed_native", "alpaca_calendar"}:
        raise ValueError("invalid stock session scope")
    (_bar if kind == "bar" else _quote)(data, scope)


def _news(data: dict[str, Any]) -> None:
    for field in ("headline", "author", "source"):
        _text(data, field)
    _time(data.get("created_at"))
    _time(data.get("updated_at"))


def _dividend(data: dict[str, Any]) -> None:
    if data.get("kind") not in {"cash", "stock"}:
        raise ValueError("invalid dividend type")
    _number(data.get("rate"), nonnegative=True)
    _date(data.get("process_date"))
    _date(data.get("ex_date"))
    for field in ("record_date", "payable_date"):
        if field in data:
            _date(data[field])


def _check_payload(kind: str, data: dict[str, Any]) -> None:
    """Validate the kind-specific fields of one stock payload."""
    if kind in ("bar", "quote"):
        _market(data, kind)
    elif kind == "news":
        _news(data)
    elif kind == "dividend":
        _dividend(data)
    else:
        _check_company(kind, data)
