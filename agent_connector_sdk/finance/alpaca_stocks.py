"""Alpaca stock historical bars, normalized to ``OhlcvBar``.

Maps one Alpaca ``GET /v2/stocks/{symbol}/bars`` page onto the existing
``OhlcvBar`` shape. ``adjustment_mode`` is always the caller's explicit,
requested mode: Alpaca's response carries no adjustment label of its own, so
this module never infers one. A page that carries a ``next_page_token``
reports ``Completeness.PARTIAL`` rather than silently claiming the full
requested interval; the caller's pagination loop supplies the next token.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from agent_connector_sdk.finance.records import AdjustmentMode, Completeness, OhlcvBar

__all__ = ["ohlcv_bars_from_alpaca"]


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _bar_event_id(symbol: str, timeframe: str, bar_time: str) -> str:
    return f"{symbol}:{timeframe}:{bar_time}"


def _bar_from_alpaca(
    raw: Mapping[str, Any],
    *,
    tenant_id: str,
    source_id: str,
    provider: str,
    symbol: str,
    license_tag: str,
    timeframe: str,
    session_calendar: str,
    currency: str,
    adjustment_mode: AdjustmentMode,
    completeness: Completeness,
    observed_at_utc: datetime,
) -> OhlcvBar:
    bar_time = str(raw["t"])
    return OhlcvBar(
        tenant_id=tenant_id,
        source_id=source_id,
        provider=provider,
        instrument_id=symbol,
        source_event_id=_bar_event_id(symbol, timeframe, bar_time),
        event_time_utc=_parse_utc(bar_time),
        observed_at_utc=observed_at_utc,
        license_tag=license_tag,
        source_digest=_bar_event_id(symbol, timeframe, bar_time),
        timeframe=timeframe,
        session_calendar=session_calendar,
        currency=currency,
        adjustment_mode=adjustment_mode,
        completeness=completeness,
        open=float(raw["o"]),
        high=float(raw["h"]),
        low=float(raw["l"]),
        close=float(raw["c"]),
        volume=float(raw["v"]),
    )


def ohlcv_bars_from_alpaca(
    payload: Mapping[str, Any],
    *,
    tenant_id: str,
    source_id: str,
    provider: str,
    symbol: str,
    license_tag: str,
    timeframe: str,
    session_calendar: str,
    currency: str,
    adjustment_mode: AdjustmentMode,
    observed_at_utc: datetime,
) -> tuple[OhlcvBar, ...]:
    """Normalize one Alpaca bars page; never fabricates a complete series."""
    raw_bars = payload.get("bars")
    if not isinstance(raw_bars, Sequence) or isinstance(raw_bars, (str, bytes)):
        raise ValueError("Alpaca bars must be an array")
    if payload.get("symbol") != symbol:
        raise ValueError("Alpaca bars symbol must match the request")
    if "next_page_token" not in payload:
        raise ValueError("Alpaca bars require a pagination token")
    token = payload["next_page_token"]
    if token is not None and (not isinstance(token, str) or not token):
        raise ValueError(
            "Alpaca bars pagination token must be a nonempty string or null"
        )
    if not raw_bars and token is not None:
        raise ValueError("Alpaca empty page has a continuation token")
    completeness = (
        Completeness.PARTIAL
        if payload.get("next_page_token")
        else Completeness.COMPLETE
    )
    return tuple(
        _bar_from_alpaca(
            raw,
            tenant_id=tenant_id,
            source_id=source_id,
            provider=provider,
            symbol=symbol,
            license_tag=license_tag,
            timeframe=timeframe,
            session_calendar=session_calendar,
            currency=currency,
            adjustment_mode=adjustment_mode,
            completeness=completeness,
            observed_at_utc=observed_at_utc,
        )
        for raw in raw_bars
    )
