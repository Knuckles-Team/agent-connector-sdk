"""Plan, row-model and schema digests plus the row-model registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from ._kernel_common import (
    PlanExecutionError,
    ProfileLimitError,
    _canonical_json,
    _digest,
    _require_pyarrow,
    _scalar_shape,
)
from ._kernel_rows import _validate_row_model_class
from .models import (
    CleanPlan,
    LocalProfile,
)


def _structural_plan(plan: CleanPlan) -> dict[str, Any]:
    """Copy a plan while replacing fill literals with type-only markers."""

    structural = plan.model_dump(mode="json")
    for step in structural["steps"]:
        if step["verb"] == "fill_nulls":
            step["fills"] = {
                column: {"type": _scalar_shape(value)}
                for column, value in sorted(step["fills"].items())
            }
    return structural


def plan_digest(plan: CleanPlan) -> str:
    """Return a stable structural digest that never hashes fill literals."""

    return _digest(_canonical_json(_structural_plan(plan)))


@dataclass(frozen=True, slots=True)
class RegisteredRowModel:
    """Immutable approved model entry selected by reference, never import path."""

    ref: str
    model: type[BaseModel]
    digest: str


def row_model_digest(row_model: type[BaseModel]) -> str:
    """Digest a model's JSON schema for immutable registry pinning."""

    try:
        schema = row_model.model_json_schema(mode="validation")
    except (TypeError, ValueError) as exc:
        raise PlanExecutionError("row_model schema cannot be inspected") from exc
    return _digest(_canonical_json(schema))


class RowModelRegistry:
    """Small immutable registry for approved strict Pydantic row models.

    The plan supplies only ``model_ref`` (and may pin ``model_digest``).  Model
    classes are registered by trusted application code, so the plan can never
    name an import path or execute caller-selected code.
    """

    __slots__ = ("_entries",)

    def __init__(self, models: Mapping[str, type[BaseModel]]) -> None:
        entries: dict[str, RegisteredRowModel] = {}
        for ref, model in models.items():
            if not isinstance(ref, str) or not ref:
                raise PlanExecutionError(
                    "row-model registry references must be non-empty"
                )
            _validate_row_model_class(model)
            entries[ref] = RegisteredRowModel(
                ref=ref,
                model=model,
                digest=row_model_digest(model),
            )
        self._entries = MappingProxyType(entries)

    def resolve(
        self, ref: str, expected_digest: str | None = None
    ) -> RegisteredRowModel:
        """Resolve an approved model and optionally enforce its pinned digest."""

        entry = self._entries.get(ref)
        if entry is None:
            raise PlanExecutionError("row-model reference is not approved")
        _validate_row_model_class(entry.model)
        if row_model_digest(entry.model) != entry.digest:
            raise PlanExecutionError(
                "approved row-model entry changed after registration"
            )
        if expected_digest is not None and expected_digest != entry.digest:
            raise PlanExecutionError(
                "row-model digest does not match the approved registry entry"
            )
        return entry


def schema_digest(table: Any) -> str:
    """Digest field names/types/nullability, excluding Arrow metadata."""

    pa, _ = _require_pyarrow()
    if not isinstance(table, pa.Table):
        raise TypeError("schema_digest expects a pyarrow.Table")
    schema = [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
        }
        for field in table.schema
    ]
    return _digest(_canonical_json(schema))


def _check_profile(table: Any, profile: LocalProfile) -> None:
    pa, _ = _require_pyarrow()
    if not isinstance(table, pa.Table):
        raise TypeError("data-prep operations require a pyarrow.Table")
    if table.num_rows > profile.max_rows:
        raise ProfileLimitError("table exceeds the local row limit")
    if table.num_columns > profile.max_columns:
        raise ProfileLimitError("table exceeds the local column limit")
    if table.nbytes > profile.max_bytes:
        raise ProfileLimitError("table exceeds the local byte limit")
