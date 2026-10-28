"""Validate FRED graph provenance and exact liquidity source values."""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, time
from decimal import Decimal, DecimalException, localcontext
from typing import Any

_STREAMS = {
    "macro_series_fed_balance_sheet": ("WALCL", "walcl"),
    "macro_series_treasury_general_account": ("WDTGAL", "wdtgal"),
    "macro_series_reverse_repo_overnight": ("RRPONTSYD", "rrpontsyd"),
}

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _milliseconds(value: datetime, *, round_up: bool = False) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("an aware time is required")
    delta = value.astimezone(UTC) - _EPOCH
    micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    result = (micros + 999) // 1000 if round_up else micros // 1000
    if not 0 <= result <= (1 << 63) - 1:
        raise ValueError("time is outside the supported range")
    return result


def _day(value: Any) -> int:
    if not isinstance(value, str):
        raise ValueError("a canonical FRED date is required")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("a canonical FRED date is required")
    return _milliseconds(datetime.combine(parsed, time.min, UTC))


def _exact(value: Any, numeric: Any) -> Decimal:
    if not isinstance(value, str) or len(value) > 128:
        raise ValueError("an exact FRED value is required")
    if isinstance(numeric, bool) or not isinstance(numeric, (int, float)):
        raise ValueError("a numeric FRED value is required")
    exact = Decimal(value)
    if not exact.is_finite() or not math.isfinite(float(numeric)):
        raise ValueError("a finite FRED value is required")
    if float(exact) != float(numeric):
        raise ValueError("FRED numeric value differs")
    return exact


def _scaled(exact: Decimal) -> int:
    with localcontext() as context:
        context.prec = 160
        scaled = exact * 1000
        if scaled != scaled.to_integral_value():
            raise ValueError("unsupported FRED value precision")
        if not 0 <= scaled <= (1 << 63) - 1:
            raise ValueError("FRED value is outside the supported range")
        return int(scaled)


def _milliunits(value: Any, numeric: Any) -> int:
    try:
        return _scaled(_exact(value, numeric))
    except (DecimalException, OverflowError):
        raise ValueError("invalid FRED value") from None


def _source(node: dict[str, Any]) -> tuple[str, str]:
    stream = node.get("source_stream")
    if not isinstance(stream, str) or stream not in _STREAMS:
        raise ValueError("unknown liquidity source stream")
    series, kind = _STREAMS[stream]
    provenance = node.get("source_provenance")
    if (
        not isinstance(provenance, dict)
        or provenance.get("connector") != "bellwether-mcp"
        or provenance.get("tool") != "fred_series_observations"
        or provenance.get("server") != "bellwether-mcp"
        or node.get("source_mapping_reference")
        != "connector:bellwether-mcp#mappings/EconomicIndicator"
        or node.get("series_id") != series
    ):
        raise ValueError("invalid liquidity source provenance")
    return series, kind


def _reference(node: dict[str, Any], series: str, *, period: Any, vintage: Any) -> str:
    record_id = node.get("source_record_id")
    digest = node.get("source_raw_sha256")
    if record_id != f"{series}:{period}:{vintage}" or not isinstance(digest, str):
        raise ValueError("invalid liquidity observation identity")
    if not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", digest):
        raise ValueError("invalid liquidity source digest")
    provenance = node["source_provenance"]
    if (
        provenance.get("source_uri")
        != f"mcp-tool://bellwether-mcp/fred_series_observations/{record_id}"
    ):
        raise ValueError("invalid liquidity source URI")
    return f"bellwether-mcp:{node['source_stream']}:{record_id}:{digest}"


def _observation(node: dict[str, Any]) -> dict[str, Any] | None:
    series, kind = _source(node)
    period = node.get("date")
    vintage = node.get("realtime_start")
    source_ref = _reference(node, series, period=period, vintage=vintage)
    capture = node.get("observed_at")
    if not isinstance(capture, str):
        raise ValueError("liquidity observation has no capture time")
    observed = _milliseconds(datetime.fromisoformat(capture), round_up=True)
    observation_ms, vintage_ms = _day(period), _day(vintage)
    if node.get("value") is None and node.get("value_text") is None:
        return None
    value = _milliunits(node.get("value_text"), node.get("value"))
    return {
        "series": kind,
        "observation_ms": observation_ms,
        "vintage_ms": vintage_ms,
        "observed_ms": observed,
        "value_milliunits": value,
        "source_ref": source_ref,
    }
