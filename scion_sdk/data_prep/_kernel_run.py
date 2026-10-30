"""Step dispatch and per-run state for the clean pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple

from ._kernel_common import PlanExecutionError, ProfileLimitError
from ._kernel_fill import _apply_fill_nulls
from ._kernel_names_cast import (
    _apply_canonical_names,
    _apply_null_policy,
    _apply_safe_cast,
)
from ._kernel_registry import RegisteredRowModel, _check_profile
from ._kernel_rows import _apply_dedupe, _validate_rows
from .models import (
    CanonicalNames,
    CleanPlan,
    Dedupe,
    FillNulls,
    LocalProfile,
    NullPolicy,
    QuarantineOutcome,
    RowOutcome,
    SafeCast,
    StepEvidence,
)


class _StepResult(NamedTuple):
    table: Any
    quarantined_indexes: tuple[int, ...] = ()
    reason: str | None = None
    retained_indexes: tuple[int, ...] | None = None


def _apply_step(
    table: Any,
    step: Any,
    *,
    disposition: str,
    profile: LocalProfile,
) -> _StepResult:
    """Apply one allow-listed verb with no dynamic dispatch."""

    if isinstance(step, CanonicalNames):
        return _StepResult(_apply_canonical_names(table, step))
    if isinstance(step, NullPolicy):
        result, quarantined_indexes = _apply_null_policy(
            table,
            step,
            disposition=disposition,
            profile=profile,
        )
        return _StepResult(
            result,
            quarantined_indexes,
            "null_rejected" if quarantined_indexes else None,
        )
    if isinstance(step, SafeCast):
        return _StepResult(_apply_safe_cast(table, step))
    if isinstance(step, Dedupe):
        result, dropped, retained_indexes = _apply_dedupe(table, step)
        return _StepResult(
            result, (), None if dropped == 0 else "dedupe", retained_indexes
        )
    if isinstance(step, FillNulls):
        return _StepResult(_apply_fill_nulls(table, step))
    raise PlanExecutionError("unsupported clean-plan verb")


@dataclass(slots=True)
class _RunState:
    """Mutable accumulator threaded through :meth:`CleanPipeline.run`'s step
    loop — bundles what would otherwise be six-plus loop-carried locals into
    one object so each extracted step-handler stays under the parameter cap.
    """

    current: Any
    row_ids: list[int]
    dropped_rows: int = 0
    quarantined_rows: int = 0
    quarantine: list[QuarantineOutcome] = field(default_factory=list)
    row_outcomes: list[RowOutcome] = field(default_factory=list)
    step_evidence: list[StepEvidence] = field(default_factory=list)
    outcome_codes: bytearray | None = None


def _apply_null_quarantine(
    state: _RunState,
    plan: CleanPlan,
    *,
    before_row_ids: tuple[int, ...],
    quarantine_indexes: tuple[int, ...],
) -> None:
    count = len(quarantine_indexes)
    state.quarantined_rows += count
    if state.quarantined_rows > min(
        plan.profile.max_quarantine_rows, plan.profile.max_rows
    ):
        raise ProfileLimitError("quarantine rows exceed the local profile limit")
    state.quarantine.append(
        QuarantineOutcome(reason_code="null_rejected", row_count=count)
    )
    if state.outcome_codes is not None:
        for index in quarantine_indexes:
            state.outcome_codes[before_row_ids[index]] = 3
    else:
        state.row_outcomes.extend(
            RowOutcome(
                row_index=before_row_ids[index],
                status="quarantined",
                reason_code="null_rejected",
            )
            for index in quarantine_indexes
        )
    if len(state.row_outcomes) > plan.profile.max_outcome_rows:
        raise ProfileLimitError("row outcomes exceed the local profile limit")
    invalid_positions = set(quarantine_indexes)
    state.row_ids = [
        row_id
        for index, row_id in enumerate(before_row_ids)
        if index not in invalid_positions
    ]


def _apply_dedupe_drop(
    state: _RunState,
    plan: CleanPlan,
    *,
    before_row_ids: tuple[int, ...],
    rows_in: int,
    retained_indexes: tuple[int, ...],
) -> None:
    if len(retained_indexes) != state.current.num_rows:
        raise PlanExecutionError("row identity accounting does not match the table")
    state.row_ids = [before_row_ids[index] for index in retained_indexes]
    dropped_indexes = set(range(rows_in)) - set(retained_indexes)
    if not dropped_indexes:
        return
    state.dropped_rows += len(dropped_indexes)
    if state.outcome_codes is not None:
        for index in dropped_indexes:
            state.outcome_codes[before_row_ids[index]] = 2
    else:
        state.row_outcomes.extend(
            RowOutcome(
                row_index=before_row_ids[index],
                status="dropped",
                reason_code="deduplicated",
            )
            for index in sorted(dropped_indexes)
        )
    if len(state.row_outcomes) > plan.profile.max_outcome_rows:
        raise ProfileLimitError("row outcomes exceed the local profile limit")


def _run_one_step(state: _RunState, step: Any, plan: CleanPlan) -> None:
    rows_in = state.current.num_rows
    before_row_ids = tuple(state.row_ids)
    applied = _apply_step(
        state.current,
        step,
        disposition=plan.invalid_row_disposition,
        profile=plan.profile,
    )
    state.current = applied.table
    _check_profile(state.current, plan.profile)
    count = len(applied.quarantined_indexes)
    if applied.reason == "null_rejected" and count:
        _apply_null_quarantine(
            state,
            plan,
            before_row_ids=before_row_ids,
            quarantine_indexes=applied.quarantined_indexes,
        )
    elif applied.retained_indexes is not None:
        _apply_dedupe_drop(
            state,
            plan,
            before_row_ids=before_row_ids,
            rows_in=rows_in,
            retained_indexes=applied.retained_indexes,
        )
    if len(state.row_ids) != state.current.num_rows:
        raise PlanExecutionError("row identity accounting does not match the table")
    dropped = max(0, rows_in - state.current.num_rows - count)
    state.step_evidence.append(
        StepEvidence(
            verb=step.verb,
            rows_in=rows_in,
            rows_out=state.current.num_rows,
            dropped_rows=dropped,
            quarantined_rows=count,
        )
    )


def _finalize_model_validation(
    state: _RunState, model_entry: RegisteredRowModel, plan: CleanPlan
) -> int:
    state.current, model_outcomes, model_rejected = _validate_rows(
        state.current,
        model_entry.model,
        row_ids=state.row_ids,
        disposition=plan.invalid_row_disposition,
        profile=plan.profile,
        outcome_codes=state.outcome_codes,
    )
    state.row_outcomes.extend(model_outcomes)
    if len(state.row_outcomes) > plan.profile.max_outcome_rows:
        raise ProfileLimitError("row outcomes exceed the local profile limit")
    if model_rejected:
        state.quarantined_rows += model_rejected
        state.quarantine.append(
            QuarantineOutcome(reason_code="model_rejected", row_count=model_rejected)
        )
        if state.quarantined_rows > min(
            plan.profile.max_quarantine_rows, plan.profile.max_rows
        ):
            raise ProfileLimitError("quarantine rows exceed the local profile limit")
    return model_rejected
