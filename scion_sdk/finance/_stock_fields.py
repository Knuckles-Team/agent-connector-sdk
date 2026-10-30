"""Field-level checks shared by stock and market source validators."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any


def _number(value: Any, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid stock value")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise ValueError("invalid stock value")
    return result


def _date(value: Any) -> None:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("invalid stock date")


def _time(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("invalid stock timestamp")
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("stock timestamp must have an offset")


def _text(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("stock field is required")
    return value
