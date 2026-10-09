"""FRED/ALFRED macro series observations, each keyed by its reported vintage.

A FRED/ALFRED observation describes one period (``observation_date``) as it
stood on one reporting date (``vintage_date``, FRED's ``realtime_start``). A
later revision of the same period carries a later vintage and is a new
record, never an overwrite of the earlier one, so a series' full revision
history stays intact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, Self

from pydantic import Field, model_validator

from agent_connector_sdk.finance.records import FinanceRecordBase

__all__ = [
    "MacroSeriesObservation",
    "MissingFredValueError",
    "macro_series_from_fred",
]


class MacroSeriesObservation(FinanceRecordBase):
    """One FRED/ALFRED observation, explicit about period versus vintage."""

    series_id: str = Field(min_length=1)
    observation_date: date
    vintage_date: date
    value: float

    @model_validator(mode="after")
    def _vintage_is_not_before_its_observation(self) -> Self:
        if self.vintage_date < self.observation_date:
            raise ValueError("vintage_date must not precede observation_date")
        return self


class MissingFredValueError(ValueError):
    """FRED reported ``"."`` (no value yet) for this observation."""


def _parse_value(raw: str) -> float:
    if raw == ".":
        raise MissingFredValueError("FRED observation has no reported value")
    return float(raw)


def _observation_event_id(series_id: str, period: str, vintage: str) -> str:
    return f"{series_id}:{period}:{vintage}"


def _macro_observation_from_fred(
    raw: Mapping[str, Any],
    *,
    tenant_id: str,
    source_id: str,
    provider: str,
    series_id: str,
    license_tag: str,
    observed_at_utc: datetime,
) -> MacroSeriesObservation:
    period = str(raw["date"])
    vintage = str(raw["realtime_start"])
    event_id = _observation_event_id(series_id, period, vintage)
    return MacroSeriesObservation(
        tenant_id=tenant_id,
        source_id=source_id,
        provider=provider,
        instrument_id=series_id,
        source_event_id=event_id,
        event_time_utc=datetime.fromisoformat(period).replace(tzinfo=UTC),
        observed_at_utc=observed_at_utc,
        license_tag=license_tag,
        source_digest=event_id,
        series_id=series_id,
        observation_date=date.fromisoformat(period),
        vintage_date=date.fromisoformat(vintage),
        value=_parse_value(str(raw["value"])),
    )


def macro_series_from_fred(
    payload: Mapping[str, Any],
    *,
    tenant_id: str,
    source_id: str,
    provider: str,
    series_id: str,
    license_tag: str,
    observed_at_utc: datetime,
) -> tuple[MacroSeriesObservation, ...]:
    """Normalize one FRED/ALFRED ``observations`` page; one record per vintage."""
    raw_observations: Sequence[Mapping[str, Any]] = payload.get("observations", ())
    return tuple(
        _macro_observation_from_fred(
            raw,
            tenant_id=tenant_id,
            source_id=source_id,
            provider=provider,
            series_id=series_id,
            license_tag=license_tag,
            observed_at_utc=observed_at_utc,
        )
        for raw in raw_observations
    )
