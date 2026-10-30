"""Pure Arrow preparation, bounded profiling and privacy-safe evidence.

This module is the only execution authority for :mod:`scion_sdk.data_prep`.
It accepts an Arrow table, validates a frozen :class:`CleanPlan`, and applies
the five allow-listed verbs with explicit dispatch.  It never imports pandas,
uses dynamic method lookup, or mutates the caller's plan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from ._kernel_common import (
    DataPrepDependencyError,
    DataPrepError,
    InvalidRowsError,
    PlanExecutionError,
    ProfileDeadlineError,
    ProfileLimitError,
    ProfileSelectorError,
    _digest,
    _require_pyarrow,
)
from ._kernel_profile import profile_table
from ._kernel_registry import (
    RegisteredRowModel,
    RowModelRegistry,
    _check_profile,
    plan_digest,
    row_model_digest,
    schema_digest,
)
from ._kernel_results import PagedPrepResult, PrepResult
from ._kernel_run import _finalize_model_validation, _run_one_step, _RunState
from .models import (
    CleanPlan,
    LocalProfile,
    PrepEvidence,
    ProfileResult,
)


class ArrowAdapter:
    """Bounded adapters for Arrow tables and record batches.

    There is intentionally no pandas/JSON/row-list adapter.  A caller that has
    records must materialize them into Arrow at its governed boundary first.
    """

    @staticmethod
    def as_table(value: Any, *, profile: LocalProfile | None = None) -> Any:
        """Validate an existing table and optionally apply profile limits."""

        pa, _ = _require_pyarrow()
        if not isinstance(value, pa.Table):
            raise TypeError(
                "expected pyarrow.Table; row-oriented adapters are not supported"
            )
        if profile is not None:
            _check_profile(value, profile)
        return value

    @staticmethod
    def from_batches(
        batches: Sequence[Any],
        *,
        profile: LocalProfile,
    ) -> Any:
        """Create a table from a finite, profile-bounded batch sequence."""

        pa, _ = _require_pyarrow()
        materialized = []
        row_count = 0
        for batch in batches:
            if not isinstance(batch, pa.RecordBatch):
                raise TypeError("all batches must be pyarrow.RecordBatch instances")
            row_count += batch.num_rows
            if row_count > profile.max_rows:
                raise ProfileLimitError("record batches exceed the local row limit")
            materialized.append(batch)
        if not materialized:
            raise ValueError("at least one Arrow record batch is required")
        table = pa.Table.from_batches(materialized)
        _check_profile(table, profile)
        return table


def _check_outcome_codes(codes: bytes, rows_in: int, state: _RunState) -> None:
    if (
        len(codes) != rows_in
        or 0 in codes
        or codes.count(1) != state.current.num_rows
        or codes.count(2) != state.dropped_rows
        or codes.count(3) + codes.count(4) != state.quarantined_rows
    ):
        raise PlanExecutionError("row outcome accounting is incomplete")


class CleanPipeline:
    """Apply a typed, deterministic clean plan to an Arrow table."""

    __slots__ = ("_plan", "_registry")

    def __init__(
        self,
        plan: CleanPlan | Mapping[str, Any],
        *,
        model_registry: RowModelRegistry | None = None,
    ) -> None:
        validated = CleanPlan.model_validate(plan)
        # Keep an independent deep copy of nested lists/maps.  The executor
        # never writes to a plan, and a caller mutating its own model after
        # construction cannot alter an in-flight pipeline's digest or policy.
        self._plan = validated.model_copy(deep=True)
        self._registry = model_registry

    @property
    def plan(self) -> CleanPlan:
        """The validated immutable plan used by this pipeline."""

        return self._plan.model_copy(deep=True)

    def profile(self, table: Any) -> ProfileResult:
        """Return a bounded local profile without applying transformations."""

        return profile_table(
            table,
            self._plan.profile,
            target_ref=(
                self._plan.artifact_ref or self._plan.source_ref or self._plan.plan_ref
            ),
        )

    def run_paged(self, table: Any) -> PagedPrepResult:
        """Execute the whole plan and expose outcomes through bounded pages."""
        ArrowAdapter.as_table(table, profile=self._plan.profile)
        if self._registry is None:
            raise PlanExecutionError("an approved row-model registry is required")
        model_entry = self._registry.resolve(
            self._plan.model_ref, self._plan.model_digest
        )
        input_schema = schema_digest(table)
        state = _RunState(
            current=table,
            row_ids=list(range(table.num_rows)),
            outcome_codes=bytearray(table.num_rows),
        )
        for step in self._plan.steps:
            _run_one_step(state, step, self._plan)
        rejected = _finalize_model_validation(state, model_entry, self._plan)
        _check_profile(state.current, self._plan.profile)
        codes = bytes(state.outcome_codes or b"")
        _check_outcome_codes(codes, table.num_rows, state)
        return PagedPrepResult(
            table=state.current,
            rows_in=table.num_rows,
            rows_out=state.current.num_rows,
            dropped_rows=state.dropped_rows,
            quarantined_rows=state.quarantined_rows,
            model_rejected_rows=rejected,
            content_checkpoint_eligible=not state.quarantined_rows,
            plan_digest=plan_digest(self._plan),
            input_schema_digest=input_schema,
            output_schema_digest=schema_digest(state.current),
            model_digest=model_entry.digest,
            plan_ref=self._plan.plan_ref,
            policy_ref=self._plan.policy_ref,
            model_ref=self._plan.model_ref,
            source_ref=self._plan.source_ref,
            artifact_ref=self._plan.artifact_ref,
            steps=tuple(state.step_evidence),
            quarantine=tuple(state.quarantine),
            page_size=self._plan.profile.max_outcome_rows,
            outcomes_digest=_digest(codes),
            _codes=codes,
        )

    def run(self, table: Any) -> PrepResult:
        """Apply the plan and return the table plus content-free evidence."""

        ArrowAdapter.as_table(table, profile=self._plan.profile)
        input_rows = table.num_rows
        if input_rows > self._plan.profile.max_outcome_rows:
            raise ProfileLimitError("row outcomes exceed the local profile limit")
        if self._registry is None:
            raise PlanExecutionError("an approved row-model registry is required")
        model_entry = self._registry.resolve(
            self._plan.model_ref,
            self._plan.model_digest,
        )
        input_schema = schema_digest(table)

        state = _RunState(current=table, row_ids=list(range(input_rows)))
        for step in self._plan.steps:
            _run_one_step(state, step, self._plan)

        model_rejected = _finalize_model_validation(state, model_entry, self._plan)
        _check_profile(state.current, self._plan.profile)
        state.row_outcomes.sort(key=lambda item: item.row_index)

        output_schema = schema_digest(state.current)
        outcome: Literal["complete", "quarantined"] = (
            "quarantined" if state.quarantined_rows else "complete"
        )
        evidence = PrepEvidence(
            evidence_version="data-prep-evidence.v1",
            algorithm="arrow-clean-pipeline",
            algorithm_version="1",
            outcome=outcome,
            checkpoint_eligible=not state.quarantined_rows,
            plan_digest=plan_digest(self._plan),
            input_schema_digest=input_schema,
            output_schema_digest=output_schema,
            rows_in=input_rows,
            rows_out=state.current.num_rows,
            dropped_rows=state.dropped_rows,
            quarantined_rows=state.quarantined_rows,
            invalid_row_disposition=self._plan.invalid_row_disposition,
            plan_ref=self._plan.plan_ref,
            policy_ref=self._plan.policy_ref,
            model_ref=self._plan.model_ref,
            model_digest=model_entry.digest,
            source_ref=self._plan.source_ref,
            artifact_ref=self._plan.artifact_ref,
            quarantine=state.quarantine,
            row_outcomes=state.row_outcomes,
            model_rejected_rows=model_rejected,
            steps=state.step_evidence,
        )
        return PrepResult(table=state.current, evidence=evidence)


__all__ = [
    "ArrowAdapter",
    "CleanPipeline",
    "DataPrepDependencyError",
    "DataPrepError",
    "InvalidRowsError",
    "PagedPrepResult",
    "PlanExecutionError",
    "PrepResult",
    "ProfileDeadlineError",
    "ProfileLimitError",
    "ProfileSelectorError",
    "RegisteredRowModel",
    "RowModelRegistry",
    "plan_digest",
    "profile_table",
    "row_model_digest",
    "schema_digest",
]
