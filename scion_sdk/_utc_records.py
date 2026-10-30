"""Frozen record base that requires timezone-aware event and observation times."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

_UTC_FIELDS = ("event_time_utc", "observed_at_utc")


class _FrozenRecord(BaseModel):
    """Immutable record that rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class _UtcTimestampedRecord(_FrozenRecord):
    """A record whose ``event_time_utc`` and ``observed_at_utc`` carry a zone."""

    @model_validator(mode="after")
    def _timestamps_are_utc(self) -> Self:
        for name in _UTC_FIELDS:
            value: datetime = getattr(self, name)
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware UTC")
        return self
