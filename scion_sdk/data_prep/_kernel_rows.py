"""Deduplication and strict row-model validation steps."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from ._kernel_common import (
    _MAX_BATCH_ROWS,
    InvalidRowsError,
    PlanExecutionError,
    ProfileLimitError,
    _require_pyarrow,
)
from ._kernel_names_cast import _require_columns
from .models import (
    Dedupe,
    LocalProfile,
    RowOutcome,
)

_INTERNAL_INDEX = "__au_data_prep_row_index__"


def _sorted_by_keys(table: Any, keys: Sequence[str], *, pa: Any, pc: Any) -> Any:
    key_table = table.select(list(keys)).append_column(
        _INTERNAL_INDEX,
        pa.array(range(table.num_rows), type=pa.uint64()),
    )
    # The row index is a secondary key, so equal user keys have a deterministic
    # first occurrence even if Arrow changes its equal-key sort implementation.
    sort_keys = [(key, "ascending") for key in keys]
    sort_keys.append((_INTERNAL_INDEX, "ascending"))
    return pc.sort_indices(key_table, sort_keys=sort_keys)


def _adjacent_equal(ordered: Any, keys: Sequence[str], *, pa: Any, pc: Any) -> Any:
    row_count = ordered.num_rows
    equal_adjacent = pa.array([True] * (row_count - 1))
    for key in keys:
        values = ordered[key].combine_chunks()
        previous = values.slice(0, row_count - 1)
        current = values.slice(1)
        equal = pc.equal(previous, current)
        both_null = pc.and_(pc.is_null(previous), pc.is_null(current))
        key_equal = pc.fill_null(pc.or_kleene(equal, both_null), False)
        equal_adjacent = pc.and_(equal_adjacent, key_equal)
    return equal_adjacent


def _apply_dedupe(table: Any, step: Dedupe) -> tuple[Any, int, tuple[int, ...]]:
    _require_columns(table, step.keys)
    if table.num_rows < 2:
        return table, 0, tuple(range(table.num_rows))
    pa, pc = _require_pyarrow()
    if _INTERNAL_INDEX in table.column_names:
        raise PlanExecutionError("input schema uses a reserved data-prep field name")
    order = _sorted_by_keys(table, step.keys, pa=pa, pc=pc)
    equal_adjacent = _adjacent_equal(table.take(order), step.keys, pa=pa, pc=pc)
    keep = pa.concat_arrays([pa.array([True]), pc.invert(equal_adjacent)])
    selected = order.filter(keep)
    # Keep the first occurrence in original input order, not sort order.
    restore_order = pc.sort_indices(
        pa.table({"row_index": selected}),
        sort_keys=[("row_index", "ascending")],
    )
    selected = selected.take(restore_order)
    selected_indexes = tuple(int(index.as_py()) for index in selected)
    return table.take(selected), table.num_rows - len(selected), selected_indexes


def _validate_row_model_class(row_model: type[BaseModel] | Any) -> None:
    """Require an approved strict model class before it enters the registry."""

    if not isinstance(row_model, type) or not issubclass(row_model, BaseModel):
        raise PlanExecutionError("row_model must be a Pydantic BaseModel class")
    config = row_model.model_config
    if config.get("strict") is not True or config.get("extra") != "forbid":
        raise PlanExecutionError("row_model must use strict=True and extra='forbid'")
    fields = row_model.model_fields
    if not fields:
        raise PlanExecutionError("row_model must declare at least one field")
    if any(field.annotation is Any for field in fields.values()):
        raise PlanExecutionError("row_model fields cannot use unconstrained Any")


def _validate_row_model_schema(table: Any, row_model: type[BaseModel]) -> None:
    """Require an approved strict model with an exact Arrow schema."""

    _validate_row_model_class(row_model)
    fields = row_model.model_fields
    if len(table.column_names) != len(set(table.column_names)):
        raise PlanExecutionError("Arrow schema field names must be unique")
    if set(fields) != set(table.column_names):
        raise PlanExecutionError("row_model fields must exactly match the Arrow schema")


def _row_is_valid(row_model: type[BaseModel], row: Any) -> bool:
    try:
        row_model.model_validate(row)
    except ValidationError:
        return False
    return True


def _record_row_outcome(
    row_id: int,
    accepted: bool,
    *,
    outcome_codes: bytearray | None,
    outcomes: list[RowOutcome],
) -> None:
    if outcome_codes is not None:
        outcome_codes[row_id] = 1 if accepted else 4
        return
    outcomes.append(
        RowOutcome(
            row_index=row_id,
            status="accepted" if accepted else "quarantined",
            reason_code="accepted" if accepted else "model_rejected",
        )
    )


def _validate_rows(
    table: Any,
    row_model: type[BaseModel],
    *,
    row_ids: Sequence[int],
    disposition: str,
    profile: LocalProfile,
    outcome_codes: bytearray | None = None,
) -> tuple[Any, list[RowOutcome], int]:
    """Validate bounded Arrow rows and return only redacted dispositions."""

    pa, _ = _require_pyarrow()
    _validate_row_model_schema(table, row_model)
    if len(row_ids) != table.num_rows:
        raise PlanExecutionError("row identity accounting does not match the table")
    if outcome_codes is None and table.num_rows > profile.max_outcome_rows:
        raise ProfileLimitError("row outcomes exceed the local profile limit")
    valid_flags: list[bool] = []
    outcomes: list[RowOutcome] = []
    row_index = 0
    for batch in table.to_batches(max_chunksize=_MAX_BATCH_ROWS):
        for row in batch.to_pylist():
            accepted = _row_is_valid(row_model, row)
            valid_flags.append(accepted)
            _record_row_outcome(
                row_ids[row_index],
                accepted,
                outcome_codes=outcome_codes,
                outcomes=outcomes,
            )
            row_index += 1
    rejected = valid_flags.count(False)
    if rejected and disposition == "fail":
        raise InvalidRowsError(rejected, reason="strict row-model validation")
    if rejected > min(
        profile.max_quarantine_rows,
        profile.max_outcome_rows if outcome_codes is None else profile.max_rows,
        profile.max_rows,
    ):
        raise ProfileLimitError("model quarantine rows exceed the local profile limit")
    return table.filter(pa.array(valid_flags, type=pa.bool_())), outcomes, rejected
