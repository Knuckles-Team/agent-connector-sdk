"""Row outcomes and privacy-safe preparation evidence."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    Field,
    model_validator,
)

from scion_sdk.data_prep._base import ProtocolModel

from ._types import Digest, InvalidRowDisposition, OpaqueReference


class QuarantineOutcome(ProtocolModel):
    """Privacy-safe count for one rejected-row reason; never a row payload."""

    reason_code: Literal["null_rejected", "model_rejected"]
    row_count: int = Field(ge=1, le=1_000_000)


class RowOutcome(ProtocolModel):
    """Terminal row disposition with no row payload or validation detail."""

    row_index: int = Field(ge=0, le=1_000_000)
    status: Literal["accepted", "dropped", "quarantined"]
    reason_code: Literal[
        "accepted",
        "deduplicated",
        "null_rejected",
        "model_rejected",
    ]

    @model_validator(mode="after")
    def status_matches_reason(self) -> RowOutcome:
        if self.status == "accepted" and self.reason_code != "accepted":
            raise ValueError("accepted rows must use the accepted reason code")
        if self.status == "dropped" and self.reason_code != "deduplicated":
            raise ValueError("dropped rows must use the deduplicated reason code")
        if self.status == "quarantined" and self.reason_code not in {
            "null_rejected",
            "model_rejected",
        }:
            raise ValueError("quarantined rows require a rejection reason code")
        return self


class StepEvidence(ProtocolModel):
    """Bounded, content-free accounting for one executed plan verb."""

    verb: Literal[
        "canonical_names",
        "null_policy",
        "safe_cast",
        "dedupe",
        "fill_nulls",
    ]
    rows_in: int = Field(ge=0, le=1_000_000)
    rows_out: int = Field(ge=0, le=1_000_000)
    dropped_rows: int = Field(ge=0, le=1_000_000)
    quarantined_rows: int = Field(ge=0, le=1_000_000)


class PrepEvidence(ProtocolModel):
    """Versioned, privacy-safe evidence for one completed Arrow preparation.

    The evidence intentionally contains only schema/plan/model digests, counts,
    policy/reference identifiers and allow-listed reason codes.  It cannot
    carry rows, rejected values, fill values, column names or secrets.  A
    quarantined result is never checkpoint-eligible.
    """

    evidence_version: Literal["data-prep-evidence.v1"]
    algorithm: Literal["arrow-clean-pipeline"]
    algorithm_version: Literal["1"]
    outcome: Literal["complete", "quarantined"]
    checkpoint_eligible: bool
    plan_digest: Digest
    input_schema_digest: Digest
    output_schema_digest: Digest
    rows_in: int = Field(ge=0, le=1_000_000)
    rows_out: int = Field(ge=0, le=1_000_000)
    dropped_rows: int = Field(ge=0, le=1_000_000)
    quarantined_rows: int = Field(ge=0, le=1_000_000)
    invalid_row_disposition: InvalidRowDisposition
    plan_ref: OpaqueReference
    policy_ref: OpaqueReference
    model_ref: OpaqueReference
    model_digest: Digest
    source_ref: OpaqueReference | None = None
    artifact_ref: OpaqueReference | None = None
    quarantine: list[QuarantineOutcome] = Field(default_factory=list)
    row_outcomes: list[RowOutcome] = Field(
        default_factory=list,
        max_length=200_000,
    )
    model_rejected_rows: int = Field(ge=0, le=1_000_000)
    steps: list[StepEvidence] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def checkpoint_follows_outcome(self) -> PrepEvidence:
        _check_evidence_counts(self)
        _check_row_outcomes(self)
        _check_checkpoint_eligibility(self)
        return self


def _check_evidence_counts(evidence: PrepEvidence) -> None:
    counted = sum(item.row_count for item in evidence.quarantine)
    if counted != evidence.quarantined_rows:
        raise ValueError("quarantine counts must equal quarantined_rows")
    terminal = evidence.rows_out + evidence.dropped_rows + evidence.quarantined_rows
    if terminal != evidence.rows_in:
        raise ValueError("terminal row counts must cover every input row")


def _check_row_outcomes(evidence: PrepEvidence) -> None:
    outcomes = evidence.row_outcomes
    row_indexes = [item.row_index for item in outcomes]
    if len(row_indexes) != evidence.rows_in or sorted(row_indexes) != list(
        range(evidence.rows_in)
    ):
        raise ValueError("row outcomes must cover each input ordinal exactly once")
    if sum(item.status == "accepted" for item in outcomes) != evidence.rows_out:
        raise ValueError("accepted outcomes must equal rows_out")
    if sum(item.status == "dropped" for item in outcomes) != evidence.dropped_rows:
        raise ValueError("dropped outcomes must equal dropped_rows")
    if (
        sum(item.status == "quarantined" for item in outcomes)
        != evidence.quarantined_rows
    ):
        raise ValueError("row outcomes must account for every quarantined row")
    rejected = sum(item.reason_code == "model_rejected" for item in outcomes)
    if rejected != evidence.model_rejected_rows:
        raise ValueError("model rejection count must match row outcomes")


def _check_checkpoint_eligibility(evidence: PrepEvidence) -> None:
    if evidence.outcome == "quarantined":
        if evidence.quarantined_rows < 1 or evidence.checkpoint_eligible:
            raise ValueError("quarantined preparation is never checkpoint-eligible")
    elif evidence.quarantined_rows != 0 or not evidence.checkpoint_eligible:
        raise ValueError("complete preparation cannot contain quarantine outcomes")
