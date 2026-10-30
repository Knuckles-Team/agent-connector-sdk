"""Result containers returned by the preparation kernel."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from .models import (
    PrepEvidence,
    QuarantineOutcome,
    RowOutcome,
    StepEvidence,
)


@dataclass(frozen=True, slots=True)
class PrepResult:
    """Prepared Arrow table plus its bounded operation evidence."""

    table: Any
    evidence: PrepEvidence


@dataclass(frozen=True, slots=True)
class PagedPrepResult:
    """Whole-plan result with lazily materialized, bounded row evidence pages.

    The summary is not a statement that a consumer has read every page.
    ``outcomes_digest`` hashes one byte per input ordinal: 1 for accepted,
    2 for deduplicated, 3 for null rejection and 4 for model rejection.
    """

    table: Any = field(repr=False)
    rows_in: int
    rows_out: int
    dropped_rows: int
    quarantined_rows: int
    model_rejected_rows: int
    content_checkpoint_eligible: bool
    plan_digest: str
    input_schema_digest: str
    output_schema_digest: str
    model_digest: str
    plan_ref: str
    policy_ref: str
    model_ref: str
    source_ref: str | None
    artifact_ref: str | None
    steps: tuple[StepEvidence, ...]
    quarantine: tuple[QuarantineOutcome, ...]
    page_size: int
    outcomes_digest: str
    _codes: bytes = field(repr=False)

    def iter_evidence_pages(self) -> Iterator[tuple[RowOutcome, ...]]:
        """Yield every ordinal in order, at most ``page_size`` rows at a time."""
        values: dict[
            int,
            tuple[
                Literal["accepted", "dropped", "quarantined"],
                Literal["accepted", "deduplicated", "null_rejected", "model_rejected"],
            ],
        ] = {
            1: ("accepted", "accepted"),
            2: ("dropped", "deduplicated"),
            3: ("quarantined", "null_rejected"),
            4: ("quarantined", "model_rejected"),
        }
        for offset in range(0, self.rows_in, self.page_size):
            yield tuple(
                RowOutcome(
                    row_index=offset + index,
                    status=values[code][0],
                    reason_code=values[code][1],
                )
                for index, code in enumerate(
                    self._codes[offset : offset + self.page_size]
                )
            )
