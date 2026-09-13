"""Parsing and combining client-supplied visibility filter values."""

from __future__ import annotations

import re
from typing import Any

from agent_connector_sdk.config import csv_values

__all__ = [
    "EMPTY_INTERSECTION",
    "bounded_filter_values",
    "narrow_values",
    "request_values",
]

#: Sentinel allowlist entry that no component can match.
EMPTY_INTERSECTION = "__empty_filter_intersection__"

_FILTER_VALUE_RE = re.compile(r"[A-Za-z0-9_.:/-]{1,128}")
_MAX_RAW_BYTES = 16_384
_MAX_VALUES = 256


def bounded_filter_values(values: list[str]) -> list[str]:
    """Split, validate and de-duplicate raw filter values.

    Raises:
        ValueError: a value is oversized, malformed, ``all``, or too many.
    """
    parsed: list[str] = []
    for raw in values:
        if len(raw.encode("utf-8")) > _MAX_RAW_BYTES:
            raise ValueError("visibility filter is too large")
        parsed.extend(csv_values(raw))
    if len(parsed) > _MAX_VALUES or any(
        value.lower() == "all" or not _FILTER_VALUE_RE.fullmatch(value)
        for value in parsed
    ):
        raise ValueError("visibility filter is invalid")
    return list(dict.fromkeys(parsed))


def narrow_values(current: tuple[str, ...], requested: list[str]) -> tuple[str, ...]:
    """Intersect an allowlist with a request, or adopt the request when none exists."""
    if not requested:
        return current
    if not current:
        return tuple(requested)
    wanted = set(requested)
    return tuple(value for value in current if value in wanted) or (EMPTY_INTERSECTION,)


def request_values(source: Any, names: tuple[str, ...]) -> list[str]:
    """Collect and validate every value of ``names`` from query params or headers."""
    getter = getattr(source, "getlist", None)
    collected: list[str] = []
    for name in names:
        raw = getter(name) if getter else [source.get(name)]
        collected.extend(value for value in raw if value)
    return bounded_filter_values(collected)
