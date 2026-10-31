"""Result-size bounds and identifier/filter checks for the database connector."""

from __future__ import annotations

import datetime as dt
import decimal
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from scion_sdk.source_connectors._universal_params import _ParamChecks

_MAX_CELL_BYTES = 1_048_576
_MAX_IDENTIFIER_BYTES = 255
_MONGO_OPERATORS = frozenset(
    {
        "$and",
        "$eq",
        "$exists",
        "$gt",
        "$gte",
        "$in",
        "$lt",
        "$lte",
        "$ne",
        "$nin",
        "$nor",
        "$not",
        "$or",
    }
)


class _CellChecks(_ParamChecks):
    """Cell size bounds, schema identifiers and MongoDB filter validation."""

    @classmethod
    def _bounded_cell_size(cls, value: Any, *, depth: int = 0) -> int:
        if depth > 12:
            raise RuntimeError("database result is too deeply nested")
        scalar_size = cls._scalar_cell_size(value)
        if scalar_size is not None:
            size = scalar_size
        elif isinstance(value, Mapping):
            size = cls._mapping_cell_size(value, depth)
        elif isinstance(value, Sequence):
            size = cls._sequence_cell_size(value, depth)
        else:
            raise TypeError("database result contains an unsupported cell type")
        if size > _MAX_CELL_BYTES:
            raise RuntimeError("database result cell exceeds the configured bound")
        return size

    @staticmethod
    def _scalar_cell_size(value: Any) -> int | None:
        if value is None or isinstance(value, bool | int | float):
            return 16
        if isinstance(value, str):
            return len(value.encode("utf-8"))
        if isinstance(value, bytes | bytearray | memoryview):
            return len(value)
        if isinstance(value, dt.date | dt.time | decimal.Decimal | uuid.UUID):
            return 64
        return None

    @classmethod
    def _mapping_cell_size(cls, value: Mapping[str, Any], depth: int) -> int:
        if len(value) > 10_000:
            raise RuntimeError("database result object has too many fields")
        return sum(
            len(str(key).encode("utf-8"))
            + cls._bounded_cell_size(item, depth=depth + 1)
            for key, item in value.items()
        )

    @classmethod
    def _sequence_cell_size(cls, value: Sequence[Any], depth: int) -> int:
        if len(value) > 10_000:
            raise RuntimeError("database result array has too many values")
        return sum(cls._bounded_cell_size(item, depth=depth + 1) for item in value)

    @staticmethod
    def _safe_identifier(value: Any) -> str:
        rendered = str(value or "")
        if (
            not rendered
            or "\x00" in rendered
            or any(ord(char) < 32 for char in rendered)
            or len(rendered.encode("utf-8")) > _MAX_IDENTIFIER_BYTES
        ):
            raise ValueError("database schema identifier is invalid")
        return rendered

    @classmethod
    def _validate_mongo_filter(cls, value: Any, *, depth: int = 0) -> None:
        if depth > 12:
            raise ValueError("MongoDB filter is too deeply nested")
        if isinstance(value, Mapping):
            cls._validate_mongo_filter_mapping(value, depth)
        elif isinstance(value, Sequence) and not isinstance(
            value, str | bytes | bytearray | memoryview
        ):
            cls._validate_mongo_filter_sequence(value, depth)
        elif not cls._is_mongo_filter_scalar(value):
            raise ValueError("MongoDB filter value is unsupported")

    @classmethod
    def _validate_mongo_filter_mapping(
        cls, value: Mapping[str, Any], depth: int
    ) -> None:
        if len(value) > 1_000:
            raise ValueError("MongoDB filter has too many fields")
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("MongoDB filter key is invalid")
            if raw_key.startswith("$") and raw_key not in _MONGO_OPERATORS:
                raise PermissionError("MongoDB filter operator is not permitted")
            cls._safe_identifier(raw_key)
            cls._validate_mongo_filter(item, depth=depth + 1)

    @classmethod
    def _validate_mongo_filter_sequence(cls, value: Sequence[Any], depth: int) -> None:
        if len(value) > 1_000:
            raise ValueError("MongoDB filter has too many values")
        for item in value:
            cls._validate_mongo_filter(item, depth=depth + 1)

    @staticmethod
    def _is_mongo_filter_scalar(value: Any) -> bool:
        return isinstance(
            value,
            type(None)
            | bool
            | int
            | float
            | str
            | bytes
            | bytearray
            | dt.date
            | dt.time
            | decimal.Decimal
            | uuid.UUID,
        )
