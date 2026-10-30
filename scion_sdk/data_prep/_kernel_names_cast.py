"""Canonical-name, null-policy and safe-cast plan steps."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ._kernel_common import (
    _ARROW_TYPE_BUILDERS,
    _CANONICAL_NAME,
    _SIGNED_RANK,
    _UNSIGNED_RANK,
    InvalidRowsError,
    PlanExecutionError,
    ProfileLimitError,
    _require_pyarrow,
)
from .models import (
    CanonicalNames,
    LocalProfile,
    NullPolicy,
    SafeCast,
)


def _canonical_name(name: str) -> str:
    normalized = _CANONICAL_NAME.sub("_", name.strip().lower()).strip("_")
    if not normalized:
        raise PlanExecutionError("a field name cannot be canonicalized")
    if normalized[0].isdigit():
        normalized = f"field_{normalized}"
    if len(normalized) > 128:
        raise PlanExecutionError("canonical field name exceeds 128 characters")
    return normalized


def _require_columns(table: Any, columns: Sequence[str]) -> None:
    available = set(table.column_names)
    missing = [column for column in columns if column not in available]
    if missing:
        raise PlanExecutionError(
            "plan refers to a field absent from the current schema"
        )


def _count_true(mask: Any, pc: Any) -> int:
    value = pc.sum(pc.cast(mask, "int64")).as_py()
    return int(value or 0)


def _apply_canonical_names(table: Any, step: CanonicalNames) -> Any:
    del step
    names = tuple(_canonical_name(name) for name in table.column_names)
    if len(set(names)) != len(names):
        raise PlanExecutionError("canonical field names collide")
    return table.rename_columns(names)


def _apply_null_policy(
    table: Any,
    step: NullPolicy,
    *,
    disposition: str,
    profile: LocalProfile,
) -> tuple[Any, tuple[int, ...]]:
    _require_columns(table, step.columns)
    if step.action == "allow":
        return table, ()
    _pa, pc = _require_pyarrow()
    invalid = None
    for column in step.columns:
        mask = pc.is_null(table[column])
        invalid = mask if invalid is None else pc.or_(invalid, mask)
    if invalid is None:  # pragma: no cover - columns are validated as non-empty
        return table, ()
    invalid = pc.fill_null(invalid, False)
    count = _count_true(invalid, pc)
    if count == 0:
        return table, ()
    if disposition == "fail":
        raise InvalidRowsError(count, reason="declared null policy")
    if count > min(profile.max_quarantine_rows, profile.max_rows):
        raise ProfileLimitError("quarantine rows exceed the local profile limit")
    indexes = tuple(int(index.as_py()) for index in pc.indices_nonzero(invalid))
    return table.filter(pc.invert(invalid)), indexes


def _arrow_type_name(data_type: Any, pa: Any) -> str | None:
    # A dispatch TABLE (scan, not an unrolled if/elif chain): each predicate
    # is evaluated once and matched by position, so cccc counts one loop, not
    # twelve branches.
    checks: list[tuple[bool, str]] = [
        (pa.types.is_boolean(data_type), "bool"),
        (pa.types.is_int8(data_type), "int8"),
        (pa.types.is_int16(data_type), "int16"),
        (pa.types.is_int32(data_type), "int32"),
        (pa.types.is_int64(data_type), "int64"),
        (pa.types.is_uint8(data_type), "uint8"),
        (pa.types.is_uint16(data_type), "uint16"),
        (pa.types.is_uint32(data_type), "uint32"),
        (pa.types.is_uint64(data_type), "uint64"),
        (pa.types.is_float32(data_type), "float32"),
        (pa.types.is_float64(data_type), "float64"),
        (pa.types.is_string(data_type), "string"),
    ]
    for matched, name in checks:
        if matched:
            return name
    return None


def _lossless_cast_allowed(source: str, target: str) -> bool:
    if source == target or (source == "string" and target == "string"):
        return True
    if source in _SIGNED_RANK and target in _SIGNED_RANK:
        return _SIGNED_RANK[source] <= _SIGNED_RANK[target]
    if source in _UNSIGNED_RANK and target in _UNSIGNED_RANK:
        return _UNSIGNED_RANK[source] <= _UNSIGNED_RANK[target]
    return source == "float32" and target == "float64"


def _apply_safe_cast(table: Any, step: SafeCast) -> Any:
    _require_columns(table, (step.column,))
    pa, pc = _require_pyarrow()
    actual = _arrow_type_name(table[step.column].type, pa)
    if actual != step.source_type:
        raise PlanExecutionError(
            "safe-cast source type does not match the current schema"
        )
    if not _lossless_cast_allowed(step.source_type, step.target_type):
        raise PlanExecutionError(
            "requested cast is not an allow-listed lossless widening"
        )
    if step.source_type == step.target_type:
        return table
    target = _ARROW_TYPE_BUILDERS[step.target_type](pa)
    try:
        casted = pc.cast(table[step.column], target, safe=True)
    except (pa.ArrowException, ValueError) as exc:
        raise PlanExecutionError("safe cast failed") from exc
    index = table.column_names.index(step.column)
    return table.set_column(index, step.column, casted)
