"""Shared normalized finance record fields, OHLCV bars, quotes and actions.

Every record keeps instrument identity, time basis, adjustment policy,
completeness and provenance explicit, so a consumer never has to guess
whether a value is a raw or split/dividend-adjusted bar, a partial page, or a
licensed versus unlicensed feed. Trading decisions, portfolio accounting and
order execution are owned elsewhere; this module only normalizes what a
source adapter observed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "FINANCE_SCHEMA_VERSION",
    "AdjustmentMode",
    "Completeness",
    "CorporateAction",
    "FinanceRecordBase",
    "OhlcvBar",
    "Quote",
]

#: Version of the SDK-side normalized finance record shapes.
FINANCE_SCHEMA_VERSION = "agent-connector-sdk.finance/1"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AdjustmentMode(StrEnum):
    """Whether an OHLCV bar reflects raw prints or split/dividend adjustment."""

    RAW = "raw"
    ADJUSTED = "adjusted"


class Completeness(StrEnum):
    """Whether a page or series covers its requested interval in full."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    GAP = "gap"


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


class FinanceRecordBase(_Frozen):
    """Fields every normalized finance source record carries."""

    tenant_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)
    event_time_utc: datetime
    observed_at_utc: datetime
    schema_version: str = FINANCE_SCHEMA_VERSION
    license_tag: str = Field(min_length=1)
    source_digest: str = Field(min_length=1)

    @model_validator(mode="after")
    def _timestamps_are_utc(self) -> Self:
        _require_utc(self.event_time_utc, field_name="event_time_utc")
        _require_utc(self.observed_at_utc, field_name="observed_at_utc")
        return self


class OhlcvBar(FinanceRecordBase):
    """One bar of a historical or live price series.

    ``adjustment_mode`` and ``completeness`` are always explicit: there is no
    implicit default series and no silent truncation of a requested
    interval. A page reporting anything other than ``COMPLETE`` names the gap
    rather than fabricating a full bar.
    """

    timeframe: str = Field(min_length=1)
    session_calendar: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    adjustment_mode: AdjustmentMode
    completeness: Completeness
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(ge=0)

    @model_validator(mode="after")
    def _high_low_bound_open_close(self) -> Self:
        if self.high < max(self.open, self.close) or self.low > min(
            self.open, self.close
        ):
            raise ValueError("high/low must bound open and close")
        return self


class Quote(FinanceRecordBase):
    """One bid/ask snapshot at an exact quote time."""

    bid: float = Field(ge=0)
    ask: float = Field(ge=0)
    quote_time_utc: datetime

    @model_validator(mode="after")
    def _bid_not_above_ask(self) -> Self:
        if self.bid > self.ask:
            raise ValueError("bid must not exceed ask")
        return self


class CorporateAction(FinanceRecordBase):
    """One split, dividend or other adjustment-bearing corporate action."""

    ex_date: datetime
    effective_date: datetime
    action_type: str = Field(min_length=1)
    adjustment_factor: float = Field(gt=0)

    @model_validator(mode="after")
    def _ex_date_not_after_effective(self) -> Self:
        if self.ex_date > self.effective_date:
            raise ValueError("ex_date must not be after effective_date")
        return self
