"""Numeric statistics and quantiles for one disclosable column."""

from __future__ import annotations

from typing import Any

from ._kernel_scan import (
    _ColumnFindings,
    _ColumnScanContext,
    _profile_number,
    _profile_warning,
)
from .models import QuantilePoint


def _read_numeric_stats(
    ctx: _ColumnScanContext, non_null: Any, out: _ColumnFindings
) -> None:
    pc = ctx.pc
    out.min_value = _profile_number(pc.min(non_null).as_py())
    out.max_value = _profile_number(pc.max(non_null).as_py())
    mean_value = _profile_number(pc.mean(non_null).as_py())
    if out.min_value is None or out.max_value is None or mean_value is None:
        out.warnings.append(_profile_warning("stats_suppressed"))
    else:
        out.mean = float(mean_value)


def _column_numeric_stats(
    ctx: _ColumnScanContext, non_null: Any, out: _ColumnFindings
) -> None:
    try:
        _read_numeric_stats(ctx, non_null, out)
    except (ctx.pa.ArrowException, NotImplementedError, TypeError, ValueError):
        out.warnings.append(_profile_warning("stats_suppressed"))


def _read_quantiles(
    ctx: _ColumnScanContext,
    non_null: Any,
    *,
    probabilities: list[float],
    out: _ColumnFindings,
) -> None:
    values = ctx.pc.quantile(non_null, q=probabilities, interpolation="linear")
    for probability, value in zip(probabilities, values, strict=False):
        number = _profile_number(value.as_py())
        if number is not None:
            out.quantiles.append(
                QuantilePoint(probability=float(probability), value=float(number))
            )


def _column_quantiles(
    ctx: _ColumnScanContext, non_null: Any, out: _ColumnFindings
) -> None:
    probabilities = [0.25, 0.5, 0.75]
    if len(probabilities) > ctx.limits.max_quantiles:
        probabilities = probabilities[: ctx.limits.max_quantiles]
        out.truncated = True
        out.warnings.append(_profile_warning("quantiles_truncated"))
    if not ctx.limits.max_quantiles:
        return
    try:
        _read_quantiles(ctx, non_null, probabilities=probabilities, out=out)
    except (ctx.pa.ArrowException, NotImplementedError, TypeError, ValueError):
        out.warnings.append(_profile_warning("quantiles_unavailable"))
