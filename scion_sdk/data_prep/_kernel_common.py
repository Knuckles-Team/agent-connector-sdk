"""Shared errors, constants and Arrow helpers for the preparation kernel."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


class DataPrepError(ValueError):
    """Base class for fail-closed preparation errors."""


class DataPrepDependencyError(DataPrepError):
    """Raised when an Arrow operation is requested without ``pyarrow``."""


class ProfileLimitError(DataPrepError):
    """Raised before work starts when a table exceeds the local profile."""


class ProfileSelectorError(DataPrepError):
    """Raised when a profile selector is stale or outside the schema."""


class ProfileDeadlineError(ProfileLimitError):
    """Raised when a profile cannot finish inside its declared deadline."""


class PlanExecutionError(DataPrepError):
    """Raised when a typed plan cannot be applied to the current schema."""


class InvalidRowsError(DataPrepError):
    """Raised for rejected rows when the plan selected fail-closed ``fail``."""

    def __init__(self, row_count: int, *, reason: str = "declared validation") -> None:
        self.row_count = row_count
        self.reason = reason
        super().__init__(f"{row_count} row(s) failed {reason}")


_CANONICAL_NAME = re.compile(r"[^a-z0-9]+")


_MAX_BATCH_ROWS = 65_536


_ARROW_TYPE_BUILDERS = {
    "bool": lambda pa: pa.bool_(),
    "int8": lambda pa: pa.int8(),
    "int16": lambda pa: pa.int16(),
    "int32": lambda pa: pa.int32(),
    "int64": lambda pa: pa.int64(),
    "uint8": lambda pa: pa.uint8(),
    "uint16": lambda pa: pa.uint16(),
    "uint32": lambda pa: pa.uint32(),
    "uint64": lambda pa: pa.uint64(),
    "float32": lambda pa: pa.float32(),
    "float64": lambda pa: pa.float64(),
    "string": lambda pa: pa.string(),
}


_SIGNED_RANK = {"int8": 0, "int16": 1, "int32": 2, "int64": 3}


_UNSIGNED_RANK = {"uint8": 0, "uint16": 1, "uint32": 2, "uint64": 3}


def _require_pyarrow() -> Any:
    """Import optional Arrow only at the operation boundary."""

    try:
        import pyarrow as pa
        import pyarrow.compute as pc
    except ImportError as exc:  # pragma: no cover - exercised in lean installs
        raise DataPrepDependencyError(
            "pyarrow is required for the Arrow data-prep kernel; install "
            "scion-sdk[dataprep]"
        ) from exc
    return pa, pc


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _scalar_shape(value: Any) -> str:
    """Return a non-secret type marker for a strict fill scalar."""

    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    raise TypeError("clean-plan scalar has an unsupported type")
