"""Company-dataset record checks for stock sources."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from scion_sdk.finance._stock_fields import _date, _number, _text, _time

_PERIODS = {"FY", "Q1", "Q2", "Q3", "Q4"}
_ESTIMATE_FIELDS = (
    "eps_actual",
    "eps_estimated",
    "revenue_actual",
    "revenue_estimated",
)


def _profile(data: dict[str, Any]) -> None:
    _text(data, "company_name")


def _income(data: dict[str, Any]) -> None:
    _date(data.get("period_date"))
    if data.get("period") not in _PERIODS:
        raise ValueError("invalid company period")
    _text(data, "currency")
    _number(data.get("revenue"))
    _number(data.get("net_income"))


def _earnings(data: dict[str, Any]) -> None:
    _date(data.get("announcement_date"))
    for field in _ESTIMATE_FIELDS:
        if field in data:
            _number(data[field])


def _logo(data: dict[str, Any]) -> None:
    if data.get("image_media_type") != "image/png":
        raise ValueError("invalid logo format")
    encoded = _text(data, "image_base64")
    if len(encoded) > 1_398_104:
        raise ValueError("invalid logo size")
    image = base64.b64decode(encoded, validate=True)
    if (
        len(image) > 1024 * 1024
        or not image.startswith(b"\x89PNG\r\n\x1a\n")
        or hashlib.sha256(image).hexdigest() != data.get("image_sha256")
    ):
        raise ValueError("invalid logo digest")


_BY_DATASET = {
    "profile": _profile,
    "income": _income,
    "earnings": _earnings,
    "logo": _logo,
}


def _check_company(dataset: str, data: dict[str, Any]) -> None:
    """Validate one company-dataset payload."""
    if data.get("dataset") != dataset:
        raise ValueError("company dataset mismatch")
    _text(data, "provider")
    _time(data.get("observed_at"))
    _BY_DATASET[dataset](data)
