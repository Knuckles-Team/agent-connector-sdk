"""Query and parameter validation for the bounded database connector."""

from __future__ import annotations

import datetime as dt
import decimal
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

_MAX_QUERY_BYTES = 65_536
_MAX_PARAM_BYTES = 1_048_576


class _ParamChecks:
    """Read-only SELECT and bound-parameter validation."""

    @staticmethod
    def _validate_sql_read(query: str) -> None:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("database read query is invalid")
        if len(query.encode("utf-8")) > _MAX_QUERY_BYTES or "\x00" in query:
            raise ValueError("database read query is invalid")
        value = query.strip()
        if not _ParamChecks._is_single_readonly_select(value):
            raise PermissionError("database connector permits one read-only SELECT")

    _SQL_READ_FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(?is)\binto\b"),
        re.compile(r"(?is)\bfor\s+(update|share)\b"),
        re.compile(
            r"(?is)\b(pg_read_file|pg_ls_dir|lo_import|load_file|sleep|benchmark)\s*\("
        ),
    )

    @staticmethod
    def _is_single_readonly_select(value: str) -> bool:
        if not re.match(r"(?is)^select\b", value):
            return False
        if any(token in value for token in (";", "--", "/*", "*/")):
            return False
        return not any(
            pattern.search(value)
            for pattern in _ParamChecks._SQL_READ_FORBIDDEN_PATTERNS
        )

    @classmethod
    def _validate_params(cls, params: Any) -> None:
        if params is not None:
            cls._validate_param_value(params, 0, [0])

    @classmethod
    def _validate_param_value(cls, value: Any, depth: int, budget: list[int]) -> None:
        if depth > 12:
            raise ValueError("database query parameters are too deeply nested")
        if cls._accumulate_scalar_budget(value, budget):
            pass
        elif isinstance(value, Mapping):
            cls._validate_param_mapping(value, depth, budget)
        elif isinstance(value, Sequence):
            cls._validate_param_sequence(value, depth, budget)
        else:
            raise ValueError("database query parameter type is unsupported")
        if budget[0] > _MAX_PARAM_BYTES:
            raise ValueError("database query parameters are too large")

    @staticmethod
    def _accumulate_scalar_budget(value: Any, budget: list[int]) -> bool:
        """Add ``value``'s byte cost to ``budget`` if scalar; return whether it was."""
        if value is None or isinstance(value, bool | int | float):
            budget[0] += 16
            return True
        if isinstance(value, str | bytes | bytearray | memoryview):
            raw = value.encode("utf-8") if isinstance(value, str) else bytes(value)
            budget[0] += len(raw)
            return True
        if isinstance(value, dt.date | dt.time | decimal.Decimal | uuid.UUID):
            budget[0] += 64
            return True
        return False

    @classmethod
    def _validate_param_mapping(
        cls, value: Mapping[str, Any], depth: int, budget: list[int]
    ) -> None:
        if len(value) > 1_000:
            raise ValueError("database query has too many parameters")
        for key, item in value.items():
            if not isinstance(key, str) or len(key.encode("utf-8")) > 255:
                raise ValueError("database parameter name is invalid")
            budget[0] += len(key.encode("utf-8"))
            cls._validate_param_value(item, depth + 1, budget)

    @classmethod
    def _validate_param_sequence(
        cls, value: Sequence[Any], depth: int, budget: list[int]
    ) -> None:
        if len(value) > 1_000:
            raise ValueError("database query has too many parameters")
        for item in value:
            cls._validate_param_value(item, depth + 1, budget)
