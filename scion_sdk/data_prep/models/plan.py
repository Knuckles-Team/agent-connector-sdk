"""Local limits and the clean-plan verbs."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    Field,
    model_validator,
)

from scion_sdk.data_prep._base import ProtocolModel

from ._types import (
    ArrowTypeName,
    ColumnName,
    Digest,
    InvalidRowDisposition,
    OpaqueReference,
    ScalarValue,
    SchemaVersion,
)


class LocalProfile(ProtocolModel):
    """Explicit limits for one local, in-memory Arrow operation.

    ``max_bytes`` bounds the Arrow table footprint before any transformation.
    The other limits bound rows, columns, plan steps and redacted quarantine
    outcomes.  The effective quarantine ceiling is the lower of
    ``max_quarantine_rows`` and ``max_rows``.  The defaults are finite and
    conservative; callers still have to choose the row/column/step ceilings
    for each plan.
    """

    max_rows: int = Field(ge=1, le=1_000_000)
    max_columns: int = Field(ge=1, le=1_024)
    max_steps: int = Field(ge=1, le=64)
    max_bytes: int = Field(default=64 * 1024 * 1024, ge=1, le=512 * 1024 * 1024)
    max_quarantine_rows: int = Field(default=100_000, ge=0, le=1_000_000)
    max_outcome_rows: int = Field(default=100_000, ge=1, le=200_000)


class CanonicalNames(ProtocolModel):
    """Canonicalize every input field name to a deterministic safe identifier."""

    verb: Literal["canonical_names"]


class NullPolicy(ProtocolModel):
    """Declare how nulls in selected columns are treated."""

    verb: Literal["null_policy"]
    columns: list[ColumnName] = Field(min_length=1, max_length=1_024)
    action: Literal["allow", "reject"]

    @model_validator(mode="after")
    def columns_are_unique(self) -> NullPolicy:
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("null-policy columns must be unique")
        return self


class SafeCast(ProtocolModel):
    """Request one explicitly declared, lossless Arrow type widening."""

    verb: Literal["safe_cast"]
    column: ColumnName
    source_type: ArrowTypeName
    target_type: ArrowTypeName


class Dedupe(ProtocolModel):
    """Remove repeated rows using explicitly named key columns."""

    verb: Literal["dedupe"]
    keys: list[ColumnName] = Field(min_length=1, max_length=1_024)

    @model_validator(mode="after")
    def keys_are_unique(self) -> Dedupe:
        if len(set(self.keys)) != len(self.keys):
            raise ValueError("dedupe keys must be unique and explicit")
        return self


class FillNulls(ProtocolModel):
    """Fill selected nulls with typed scalar values supplied by the caller."""

    verb: Literal["fill_nulls"]
    fills: dict[ColumnName, ScalarValue] = Field(min_length=1, max_length=1_024)


type CleanStep = Annotated[
    CanonicalNames | NullPolicy | SafeCast | Dedupe | FillNulls,
    Field(discriminator="verb"),
]


STEP_VERBS: tuple[str, ...] = (
    "canonical_names",
    "null_policy",
    "safe_cast",
    "dedupe",
    "fill_nulls",
)


class CleanPlan(ProtocolModel):
    """Versioned, immutable plan for the pure Arrow cleaning kernel."""

    schema_version: SchemaVersion
    steps: list[CleanStep] = Field(min_length=1, max_length=64)
    profile: LocalProfile
    invalid_row_disposition: InvalidRowDisposition
    plan_ref: OpaqueReference
    policy_ref: OpaqueReference
    model_ref: OpaqueReference
    model_digest: Digest | None = None
    source_ref: OpaqueReference | None = None
    artifact_ref: OpaqueReference | None = None

    @model_validator(mode="after")
    def plan_is_bounded(self) -> CleanPlan:
        if len(self.steps) > self.profile.max_steps:
            raise ValueError("clean plan exceeds the local profile step limit")
        return self
