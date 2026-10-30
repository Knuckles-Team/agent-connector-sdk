"""Account snapshot field rules."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from scion_sdk.finance._stock_fields import _number, _text


def _position(data: dict[str, Any]) -> None:
    _text(data, "symbol")
    if data.get("exchange") != "alpaca" or data.get("side") not in {"long", "short"}:
        raise ValueError("invalid position identity")
    for field in ("qty", "avg_entry_price", "current_price", "unrealized_pnl"):
        _number(data.get(field))
    _number(data.get("avg_entry_price"), nonnegative=True)
    _number(data.get("current_price"), nonnegative=True)


def _currency(value: str) -> None:
    if (
        len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or not value.isupper()
    ):
        raise ValueError("invalid account currency")


def _positions(value: Any) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("invalid account positions")
    for item in value:
        _position(item)
    if len({item["symbol"] for item in value}) != len(value):
        raise ValueError("duplicate account positions")


def _identity(values: list[str]) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()
