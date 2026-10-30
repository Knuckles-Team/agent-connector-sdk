"""Bounded local table profiling."""

from __future__ import annotations

import math
import time
from typing import Any, NamedTuple

from ._kernel_common import (
    ProfileLimitError,
    ProfileSelectorError,
    _canonical_json,
    _require_pyarrow,
)
from ._kernel_registry import _check_profile, schema_digest
from ._kernel_scan import (
    _check_profile_deadline,
    _column_null_and_distinct,
    _column_shape_warnings,
    _ColumnFindings,
    _ColumnScanContext,
    _profile_deadline,
    _profile_dtype,
    _profile_warning,
    _suppressed_column_profile,
)
from ._kernel_stats import _column_numeric_stats, _column_quantiles
from .models import (
    ColumnProfile,
    LocalProfile,
    ProfileLimits,
    ProfileResult,
    ProfileSelector,
    ProfileTarget,
    ProfileTargetKind,
    ProfileWarningCode,
    TopKEntry,
)


def _normalize_topk_counts(
    counts: list[Any], disclosure_threshold: int
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in counts:
        if not isinstance(item, dict):
            continue
        count = item.get("counts", item.get("count"))
        value = item.get("values")
        if (
            not isinstance(count, int)
            or count < disclosure_threshold
            or not isinstance(value, (bool, int, float, str))
        ):
            continue
        normalized.append({"values": value, "count": count})
    return normalized


def _read_top_k(ctx: _ColumnScanContext, non_null: Any, out: _ColumnFindings) -> None:
    counts = _normalize_topk_counts(
        ctx.pc.value_counts(non_null).to_pylist(), ctx.limits.disclosure_threshold
    )
    counts.sort(key=lambda item: (-int(item["count"]), _canonical_json(item["values"])))
    if len(counts) > ctx.limits.max_top_k:
        out.truncated = True
        out.warnings.append(_profile_warning("topk_truncated"))
    for item in counts[: ctx.limits.max_top_k]:
        value = item["values"]
        if isinstance(value, float) and not math.isfinite(value):
            continue
        out.top_k.append(TopKEntry(value=value, count=int(item["count"])))


def _column_top_k(ctx: _ColumnScanContext, non_null: Any, out: _ColumnFindings) -> None:
    if not ctx.limits.max_top_k:
        return
    try:
        _read_top_k(ctx, non_null, out)
    except (ctx.pa.ArrowException, NotImplementedError, TypeError, ValueError):
        out.warnings.append(_profile_warning("topk_suppressed"))


def _numeric_disclosure_safe(ctx: _ColumnScanContext, non_null: Any) -> bool:
    """Suppress numeric statistics if an observed value is below threshold."""
    try:
        counts = ctx.pc.value_counts(non_null).field("counts")
        rare = ctx.pc.any(ctx.pc.less(counts, ctx.limits.disclosure_threshold)).as_py()
        return not bool(rare)
    except (ctx.pa.ArrowException, NotImplementedError, TypeError, ValueError):
        return False


def _scan_findings(
    ctx: _ColumnScanContext,
    non_null: Any,
    warnings: list[ProfileWarningCode],
    *,
    numeric: bool,
) -> _ColumnFindings:
    out = _ColumnFindings(warnings=warnings)
    if numeric and not _numeric_disclosure_safe(ctx, non_null):
        out.warnings.append(_profile_warning("stats_suppressed"))
        _check_profile_deadline(ctx.deadline)
    elif numeric:
        _column_numeric_stats(ctx, non_null, out)
        _check_profile_deadline(ctx.deadline)
        _column_quantiles(ctx, non_null, out)
        _check_profile_deadline(ctx.deadline)
    _column_top_k(ctx, non_null, out)
    _check_profile_deadline(ctx.deadline)
    return out


def _column_profile(
    table: Any,
    ordinal: int,
    *,
    pa: Any,
    pc: Any,
    limits: ProfileLimits,
    deadline: float,
) -> tuple[ColumnProfile, int, bool]:
    """Profile one bounded Arrow column without retaining field names."""

    _check_profile_deadline(deadline)
    values = table.column(ordinal).combine_chunks()
    rows = table.num_rows
    ctx = _ColumnScanContext(pa=pa, pc=pc, limits=limits, deadline=deadline)

    stats, warnings = _column_null_and_distinct(ctx, values, rows)
    warnings += _column_shape_warnings(rows, stats)

    numeric = pa.types.is_integer(values.type) or pa.types.is_floating(values.type)
    if rows - stats.null_count < limits.disclosure_threshold:
        profile = _suppressed_column_profile(
            ctx, stats, warnings, ordinal=ordinal, values=values, numeric=numeric
        )
        return profile, stats.null_count, False

    found = _scan_findings(ctx, pc.drop_null(values), warnings, numeric=numeric)
    profile = ColumnProfile(
        ordinal=ordinal,
        dtype=_profile_dtype(values.type, pa),
        null_count=stats.null_count,
        null_rate=stats.null_rate,
        distinct_count=stats.distinct_count,
        min_value=found.min_value,
        max_value=found.max_value,
        mean=found.mean,
        quantiles=found.quantiles,
        top_k=found.top_k,
        warning_codes=found.warnings,
    )
    return profile, stats.null_count, found.truncated


def _resolve_profile_ordinals(
    table: Any, selector: ProfileSelector | None, digest: str
) -> list[int]:
    if selector is not None and selector.schema_digest != digest:
        raise ProfileSelectorError("profile selector schema digest is stale")
    if selector is None:
        return list(range(table.num_columns))
    ordinals = list(selector.ordinals)
    if any(ordinal >= table.num_columns for ordinal in ordinals):
        raise ProfileSelectorError("profile selector ordinal is outside the schema")
    return ordinals


class _ColumnsScan(NamedTuple):
    profiles: list[ColumnProfile]
    null_cells: int
    truncated: bool
    warnings: list[ProfileWarningCode]


def _profile_columns(
    table: Any,
    ordinals: list[int],
    *,
    pa: Any,
    pc: Any,
    limits: ProfileLimits,
    deadline: float,
) -> _ColumnsScan:
    scan = _ColumnsScan([], 0, False, [])
    for ordinal in ordinals:
        column_profile, null_count, column_truncated = _column_profile(
            table, ordinal, pa=pa, pc=pc, limits=limits, deadline=deadline
        )
        scan = _ColumnsScan(
            [*scan.profiles, column_profile],
            scan.null_cells + null_count,
            scan.truncated or column_truncated,
            [*scan.warnings, *column_profile.warning_codes],
        )
    return scan


def _cap_profile_warnings(
    warnings: list[ProfileWarningCode], truncated: bool, max_warnings: int
) -> tuple[list[ProfileWarningCode], bool]:
    warning_values = list(dict.fromkeys(warnings))
    if len(warning_values) > max_warnings:
        truncated = True
        warning_values = warning_values[: max_warnings - 1]
        warning_values.append(_profile_warning("profile_truncated"))
    return warning_values, truncated


def profile_table(
    table: Any,
    profile: LocalProfile,
    *,
    target_ref: str | None = None,
    target_kind: ProfileTargetKind = "local_arrow",
    as_of_lsn: int | None = None,
    selector: ProfileSelector | None = None,
    limits: ProfileLimits | None = None,
) -> ProfileResult:
    """Build one bounded, privacy-aware result for local or future engine use."""

    _check_profile(table, profile)
    pa, pc = _require_pyarrow()
    effective_limits = limits or ProfileLimits(
        max_columns=profile.max_columns,
        max_bytes=profile.max_bytes,
    )
    if table.nbytes > effective_limits.max_bytes:
        raise ProfileLimitError("profile bytes exceed the declared limit")
    digest = schema_digest(table)
    ordinals = _resolve_profile_ordinals(table, selector, digest)
    if len(ordinals) > effective_limits.max_columns:
        raise ProfileLimitError("profile columns exceed the declared limit")
    started = time.monotonic()
    deadline = _profile_deadline(started, effective_limits)
    warnings: list[ProfileWarningCode] = []
    if table.num_rows == 0:
        warnings.append(_profile_warning("empty_dataset"))
    scan = _profile_columns(
        table, ordinals, pa=pa, pc=pc, limits=effective_limits, deadline=deadline
    )
    warnings.extend(scan.warnings)
    warning_values, truncated = _cap_profile_warnings(
        warnings, scan.truncated, effective_limits.max_warnings
    )
    _check_profile_deadline(deadline)
    target = ProfileTarget(
        target_kind=target_kind,
        target_ref=target_ref or "local:anonymous",
        schema_digest=digest,
        as_of_lsn=as_of_lsn,
    )
    return ProfileResult(
        evidence_version="data-prep-profile.v1",
        algorithm="arrow-local-profile",
        algorithm_version="1",
        target=target,
        schema_digest=digest,
        as_of_lsn=as_of_lsn,
        rows=table.num_rows,
        columns=len(ordinals),
        null_cells=scan.null_cells,
        bytes_in_memory=table.nbytes,
        disclosure_threshold=effective_limits.disclosure_threshold,
        truncated=truncated,
        warnings=warning_values,
        column_profiles=scan.profiles,
    )
