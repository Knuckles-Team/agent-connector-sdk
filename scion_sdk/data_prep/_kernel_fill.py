"""Null-fill plan step and its typed fill validators."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from ._kernel_common import PlanExecutionError, _require_pyarrow
from ._kernel_names_cast import _require_columns
from .models import (
    FillNulls,
)


def _validate_bool_fill(value: Any) -> None:
    if not isinstance(value, bool):
        raise PlanExecutionError("boolean null fills require a strict boolean")


def _validate_int_fill(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanExecutionError("integer null fills require a strict integer")


def _validate_float_fill(value: Any) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, float)
        or not math.isfinite(value)
    ):
        raise PlanExecutionError("floating null fills require a finite strict float")


def _validate_string_fill(value: Any) -> None:
    if not isinstance(value, str):
        raise PlanExecutionError("string null fills require a strict string")


_FILL_VALIDATOR_BY_KIND: tuple[tuple[str, Callable[[Any], None]], ...] = (
    ("is_boolean", _validate_bool_fill),
    ("is_integer", _validate_int_fill),
    ("is_floating", _validate_float_fill),
    ("is_string", _validate_string_fill),
)


def _fill_type_validator(target: Any, pa: Any) -> Callable[[Any], None] | None:
    """The strict-scalar validator for ``target``'s Arrow type kind, dict
    dispatch over ``pa.types.is_*`` predicates in place of an if/elif chain.
    """
    for predicate_name, validator in _FILL_VALIDATOR_BY_KIND:
        if getattr(pa.types, predicate_name)(target):
            return validator
    return None


def _fill_scalar(value: Any, target: Any, pa: Any) -> Any:
    """Create a target-typed scalar without a lossy conversion."""

    validator = _fill_type_validator(target, pa)
    if validator is None:
        raise PlanExecutionError("null fills are unsupported for this Arrow type")
    validator(value)
    try:
        scalar = pa.scalar(value, type=target)
    except (pa.ArrowException, TypeError, ValueError) as exc:
        raise PlanExecutionError(
            "null fill does not fit the target Arrow type"
        ) from exc
    if pa.types.is_float32(target) and float(scalar.as_py()) != value:
        raise PlanExecutionError("float32 null fill would be lossy")
    return scalar


def _apply_fill_nulls(table: Any, step: FillNulls) -> Any:
    _require_columns(table, tuple(step.fills))
    pa, pc = _require_pyarrow()
    result = table
    for column, value in step.fills.items():
        target = result[column].type
        scalar = _fill_scalar(value, target, pa)
        try:
            filled = pc.fill_null(result[column], scalar)
        except (ValueError, pa.ArrowException) as exc:
            raise PlanExecutionError("null fill failed") from exc
        index = result.column_names.index(column)
        result = result.set_column(index, column, filled)
    return result
