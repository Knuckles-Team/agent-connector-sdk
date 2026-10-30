"""SDK-owned current-plan wire models (SCION-CONNECTOR-CONTROL-R070).

These values assert shape only. The serving owner verifies caller authority,
run ownership, freshness and the live lease before returning a snapshot.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["CurrentPlanRead", "CurrentPlanRequest", "CurrentPlanSnapshot", "PlanItem"]

_RUN_ID = Field(min_length=1, max_length=512)


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


class PlanItem(_Strict):
    """One immutable plan item, in producer order."""

    text: str = Field(min_length=1)
    status: Literal["pending", "in_progress", "done"]


class CurrentPlanSnapshot(_Strict):
    """Immutable plan content and its producer validity interval."""

    run_id: str = _RUN_ID
    revision: int = Field(ge=0)
    observed_at: datetime
    expires_at: datetime
    items: tuple[PlanItem, ...]

    @model_validator(mode="after")
    def _utc_interval(self) -> CurrentPlanSnapshot:
        stamps = (self.observed_at, self.expires_at)
        if any(stamp.utcoffset() != timedelta(0) for stamp in stamps):
            raise ValueError("plan timestamps must use UTC")
        if self.expires_at <= self.observed_at:
            raise ValueError("plan expiry must follow observation")
        return self


class CurrentPlanRead(_Strict):
    """An available plan (possibly empty) or an unavailable read with no items."""

    availability: Literal["available", "unavailable"]
    snapshot: CurrentPlanSnapshot | None = None

    @model_validator(mode="after")
    def _availability_matches(self) -> CurrentPlanRead:
        if (self.availability == "available") != (self.snapshot is not None):
            raise ValueError("plan availability must match snapshot presence")
        return self


class CurrentPlanRequest(_Strict):
    """Select a run; caller authority is never a request field."""

    run_id: str = _RUN_ID
