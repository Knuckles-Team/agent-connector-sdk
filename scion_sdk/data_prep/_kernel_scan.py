"""Per-column scanning helpers for bounded local profiling."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from ._kernel_common import ProfileDeadlineError, ProfileLimitError
from .models import (
    ColumnProfile,
    ProfileLimits,
    ProfileWarningCode,
    QuantilePoint,
    TopKEntry,
)


def _profile_deadline(started: float, limits: ProfileLimits) -> float:
    return started + limits.deadline_ms / 1000


def _check_profile_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise ProfileDeadlineError("profile deadline exceeded")


def _profile_number(value: Any) -> int | float | None:
    """Return finite JSON-safe numeric output, never NaN or infinity."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if isinstance(value, int):
        return value
    return number


def _profile_dtype(dtype: Any, pa: Any) -> str:
    """Return a bounded dtype label without nested field names."""

    if pa.types.is_struct(dtype):
        return "struct"
    rendered = str(dtype)
    if "<" in rendered:
        rendered = rendered.split("<", 1)[0]
    return rendered[:128]


def _profile_warning(value: str) -> ProfileWarningCode:
    # The model is the allow-list authority; this cast keeps the kernel's
    # branch-local warning construction readable without accepting caller text.
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class _ColumnScanContext:
    """Shared Arrow/limit/deadline handles threaded through one column scan."""

    pa: Any
    pc: Any
    limits: ProfileLimits
    deadline: float


@dataclass(frozen=True, slots=True)
class _NullDistinctStats:
    null_count: int
    null_rate: float
    distinct_count: int | None


def _column_null_and_distinct(
    ctx: _ColumnScanContext, values: Any, rows: int
) -> tuple[_NullDistinctStats, list[ProfileWarningCode]]:
    pa, pc = ctx.pa, ctx.pc
    null_count = int(pc.sum(pc.cast(pc.is_null(values), pa.int64())).as_py() or 0)
    null_rate = null_count / rows if rows else 0.0
    warnings: list[ProfileWarningCode] = []
    distinct_count: int | None
    try:
        distinct_count = int(pc.count_distinct(values).as_py() or 0)
    except (pa.ArrowException, NotImplementedError, TypeError, ValueError):
        distinct_count = None
        warnings.append(_profile_warning("cardinality_unavailable"))
    if distinct_count is not None and distinct_count > ctx.limits.max_cardinality:
        raise ProfileLimitError("profile cardinality exceeds the declared limit")
    return _NullDistinctStats(null_count, null_rate, distinct_count), warnings


def _column_shape_warnings(
    rows: int, stats: _NullDistinctStats
) -> list[ProfileWarningCode]:
    warnings: list[ProfileWarningCode] = []
    if rows == 0 or stats.null_count == rows:
        warnings.append(_profile_warning("all_null"))
    if rows and stats.null_rate >= 0.5:
        warnings.append(_profile_warning("high_null_rate"))
    if rows and stats.distinct_count == 1:
        warnings.append(_profile_warning("single_value"))
    if rows > 1 and stats.distinct_count == rows:
        warnings.append(_profile_warning("high_cardinality"))
    return warnings


def _suppressed_column_profile(
    ctx: _ColumnScanContext,
    stats: _NullDistinctStats,
    warnings: list[ProfileWarningCode],
    *,
    ordinal: int,
    values: Any,
    numeric: bool,
) -> ColumnProfile:
    warnings = [*warnings, _profile_warning("small_group_suppressed")]
    if numeric:
        warnings.append(_profile_warning("stats_suppressed"))
    if ctx.limits.max_top_k:
        warnings.append(_profile_warning("topk_suppressed"))
    return ColumnProfile(
        ordinal=ordinal,
        dtype=_profile_dtype(values.type, ctx.pa),
        null_count=stats.null_count,
        null_rate=stats.null_rate,
        distinct_count=stats.distinct_count,
        warning_codes=warnings,
    )


@dataclass
class _ColumnFindings:
    """Mutable accumulator for the statistics of one disclosable column."""

    warnings: list[ProfileWarningCode]
    min_value: int | float | None = None
    max_value: int | float | None = None
    mean: float | None = None
    quantiles: list[QuantilePoint] = field(default_factory=list)
    top_k: list[TopKEntry] = field(default_factory=list)
    truncated: bool = False
