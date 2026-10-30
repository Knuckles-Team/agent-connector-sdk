"""Profile targets, limits, results and evidence references."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import (
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from scion_sdk.data_prep._base import ProtocolModel

from ._types import (
    Digest,
    OpaqueReference,
    ProfileScalar,
    ProfileTargetKind,
    ProfileWarningCode,
)


class ProfileTarget(ProtocolModel):
    """Exact identity of the data snapshot being profiled."""

    target_kind: ProfileTargetKind
    target_ref: OpaqueReference
    schema_digest: Digest
    as_of_lsn: StrictInt | None = Field(default=None, ge=0)


class ProfileSelector(ProtocolModel):
    """Ordinal column selector pinned to one exact schema digest."""

    schema_digest: Digest
    ordinals: list[StrictInt] = Field(min_length=1, max_length=1_024)

    @model_validator(mode="after")
    def ordinals_are_unique_and_sorted(self) -> ProfileSelector:
        if any(ordinal < 0 for ordinal in self.ordinals):
            raise ValueError("profile selector ordinals must be non-negative")
        if len(set(self.ordinals)) != len(self.ordinals):
            raise ValueError("profile selector ordinals must be unique")
        if self.ordinals != sorted(self.ordinals):
            raise ValueError("profile selector ordinals must be sorted")
        return self


class ProfileLimits(ProtocolModel):
    """Finite local/remote profiling budget; no implicit unbounded work."""

    max_columns: StrictInt = Field(default=1_024, ge=1, le=1_024)
    max_cardinality: StrictInt = Field(default=100_000, ge=1, le=1_000_000)
    max_bytes: StrictInt = Field(
        default=64 * 1024 * 1024,
        ge=1,
        le=512 * 1024 * 1024,
    )
    deadline_ms: StrictInt = Field(default=30_000, ge=1, le=120_000)
    max_top_k: StrictInt = Field(default=10, ge=0, le=20)
    max_quantiles: StrictInt = Field(default=3, ge=0, le=9)
    disclosure_threshold: StrictInt = Field(default=2, ge=2, le=1_000_000)
    max_warnings: StrictInt = Field(default=32, ge=1, le=64)


class QuantilePoint(ProtocolModel):
    """A fixed probability/value pair from a numeric column."""

    probability: StrictFloat = Field(ge=0.0, le=1.0)
    value: StrictFloat

    @model_validator(mode="after")
    def values_are_finite(self) -> QuantilePoint:
        if not math.isfinite(self.probability) or not math.isfinite(self.value):
            raise ValueError("profile quantiles must be finite")
        return self


class TopKEntry(ProtocolModel):
    """A disclosed value whose frequency meets the privacy threshold."""

    value: ProfileScalar
    count: StrictInt = Field(ge=1, le=1_000_000)

    @model_validator(mode="after")
    def value_is_finite(self) -> TopKEntry:
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("profile top-k values must be finite")
        return self


class ColumnProfile(ProtocolModel):
    """Bounded, privacy-aware quality signals for one ordinal field."""

    ordinal: StrictInt = Field(ge=0, le=1_023)
    dtype: StrictStr = Field(min_length=1, max_length=128)
    null_count: StrictInt = Field(ge=0, le=1_000_000)
    null_rate: StrictFloat = Field(ge=0.0, le=1.0)
    distinct_count: StrictInt | None = Field(default=None, ge=0, le=1_000_000)
    min_value: StrictInt | StrictFloat | None = None
    max_value: StrictInt | StrictFloat | None = None
    mean: StrictFloat | None = None
    quantiles: list[QuantilePoint] = Field(default_factory=list, max_length=9)
    top_k: list[TopKEntry] = Field(default_factory=list, max_length=20)
    warning_codes: list[ProfileWarningCode] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def numeric_values_are_finite(self) -> ColumnProfile:
        numbers = (self.min_value, self.max_value, self.mean, self.null_rate)
        if any(
            isinstance(value, float) and not math.isfinite(value) for value in numbers
        ):
            raise ValueError("profile numeric values must be finite")
        return self


class ProfileResult(ProtocolModel):
    """The one typed result shared by local Arrow and engine profiling."""

    evidence_version: Literal["data-prep-profile.v1"]
    algorithm: Literal["arrow-local-profile", "epistemic-graph-profile"]
    algorithm_version: Literal["1"]
    target: ProfileTarget
    schema_digest: Digest
    as_of_lsn: StrictInt | None = Field(default=None, ge=0)
    rows: StrictInt = Field(ge=0, le=1_000_000)
    columns: StrictInt = Field(ge=0, le=1_024)
    null_cells: StrictInt = Field(ge=0, le=1_000_000_000)
    bytes_in_memory: StrictInt = Field(ge=0, le=512 * 1024 * 1024)
    disclosure_threshold: StrictInt = Field(ge=2, le=1_000_000)
    truncated: bool = False
    warnings: list[ProfileWarningCode] = Field(default_factory=list, max_length=64)
    column_profiles: list[ColumnProfile] = Field(
        min_length=0,
        max_length=1_024,
    )

    @model_validator(mode="after")
    def identity_is_exact(self) -> ProfileResult:
        if self.target.schema_digest != self.schema_digest:
            raise ValueError("profile target and result schema digests differ")
        if self.target.as_of_lsn != self.as_of_lsn:
            raise ValueError("profile target and result LSNs differ")
        ordinals = [item.ordinal for item in self.column_profiles]
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("profile column ordinals must be unique")
        if self.columns != len(self.column_profiles):
            raise ValueError("profile column count does not match column profiles")
        if self.null_cells != sum(item.null_count for item in self.column_profiles):
            raise ValueError("profile null cells do not match column profiles")
        for column in self.column_profiles:
            _check_column_profile(column, self.rows, self.disclosure_threshold)
        return self


def _check_column_profile(
    column: ColumnProfile, rows: int, disclosure_threshold: int
) -> None:
    if column.null_count > rows:
        raise ValueError("profile null count exceeds row count")
    expected_null_rate = column.null_count / rows if rows else 0.0
    if abs(column.null_rate - expected_null_rate) > 1e-6:
        raise ValueError("profile null rate does not match null count")
    non_null = rows - column.null_count
    if column.distinct_count is not None and column.distinct_count > non_null:
        raise ValueError("profile cardinality exceeds non-null rows")
    if any(entry.count < disclosure_threshold for entry in column.top_k):
        raise ValueError("profile top-k contains a below-threshold value")
    discloses = (
        column.min_value is not None
        or column.max_value is not None
        or column.mean is not None
        or column.quantiles
        or column.top_k
    )
    if non_null < disclosure_threshold and discloses:
        raise ValueError("profile discloses a small-group statistic")


class ProfileRequest(ProtocolModel):
    """Versioned, read-only request accepted by a future engine profile client."""

    schema_version: Literal["data-prep-profile.v1"]
    target: ProfileTarget
    selector: ProfileSelector | None = None
    limits: ProfileLimits = Field(default_factory=ProfileLimits)

    @model_validator(mode="after")
    def selector_matches_target(self) -> ProfileRequest:
        if self.selector is not None and (
            self.selector.schema_digest != self.target.schema_digest
        ):
            raise ValueError("profile selector schema digest is stale")
        return self


class ProfileEvidenceReference(ProtocolModel):
    """Reference returned only by a separately authorized native authority."""

    schema_version: Literal["data-prep-profile-evidence.v1"]
    authority: Literal["native_change_envelope"]
    profile_digest: Digest
    artifact_ref: OpaqueReference
    change_envelope_ref: OpaqueReference
